"""VAD 斷句狀態機測試。

用假的語音偵測器取代 Silero，讓測試能精確控制「哪一個 frame 是語音」，
驗證的是我們自己的斷句邏輯，而不是 Silero 的模型行為。
"""
import pytest

from livestt.vad import SileroVAD, VADConfig

FRAME_SAMPLES = 512
FRAME_BYTES = FRAME_SAMPLES * 2
#: 16 kHz 下每個 frame 是 32 ms
FRAMES_PER_SECOND = 16000 / FRAME_SAMPLES


class FakeDetector:
    """依照預先給定的腳本回傳語音機率。"""

    def __init__(self, script):
        self.script = list(script)
        self.index = 0

    def chunk_samples(self):
        return FRAME_SAMPLES

    def chunk_bytes(self):
        return FRAME_BYTES

    def __call__(self, frame):
        value = self.script[self.index] if self.index < len(self.script) else 0.0
        self.index += 1
        return value


@pytest.fixture
def make_vad(monkeypatch):
    def _make(script, **config):
        vad = SileroVAD.__new__(SileroVAD)
        vad.config = VADConfig(**config)
        vad._vad = FakeDetector(script)
        vad.chunk_samples = FRAME_SAMPLES
        vad.chunk_bytes = FRAME_BYTES
        per_second = vad.config.sample_rate / FRAME_SAMPLES
        vad._silence_limit = max(1, round(vad.config.min_silence_duration * per_second))
        vad._min_speech = max(1, round(vad.config.min_speech_duration * per_second))
        vad._pad = max(1, round(vad.config.speech_pad_duration * per_second))
        vad.reset()
        return vad

    return _make


def feed(vad, count):
    """餵入 count 個 frame，回傳所有完成的語句。"""
    segments = []
    for _ in range(count):
        segments += vad.process(b"\x01" * FRAME_BYTES)
    return segments


def test_emits_segment_after_enough_silence(make_vad):
    speech = int(FRAMES_PER_SECOND)          # 1 秒語音
    silence = int(FRAMES_PER_SECOND * 0.6)   # 剛好達到靜音門檻
    vad = make_vad([1.0] * speech + [0.0] * (silence + 5), min_silence_duration=0.6)

    segments = feed(vad, speech + silence + 5)

    assert len(segments) == 1


def test_short_blip_is_discarded(make_vad):
    """比 min_speech_duration 短的聲音視為雜訊，不應產生語句。"""
    blip = 2  # 約 64 ms，遠短於預設的 200 ms
    silence = int(FRAMES_PER_SECOND)
    vad = make_vad([1.0] * blip + [0.0] * silence, min_speech_duration=0.2)

    assert feed(vad, blip + silence) == []


def test_brief_pause_does_not_split_sentence(make_vad):
    """句中短暫停頓不應該把一句話切成兩句。"""
    chunk = int(FRAMES_PER_SECOND * 0.5)
    pause = int(FRAMES_PER_SECOND * 0.3)      # 短於 0.6 秒門檻
    tail = int(FRAMES_PER_SECOND * 0.8)       # 長於門檻，句子在此結束
    script = [1.0] * chunk + [0.0] * pause + [1.0] * chunk + [0.0] * tail
    vad = make_vad(script, min_silence_duration=0.6)

    segments = feed(vad, len(script))

    assert len(segments) == 1


def test_two_sentences_produce_two_segments(make_vad):
    speech = int(FRAMES_PER_SECOND)
    silence = int(FRAMES_PER_SECOND * 0.8)
    script = ([1.0] * speech + [0.0] * silence) * 2
    vad = make_vad(script, min_silence_duration=0.6)

    assert len(feed(vad, len(script))) == 2


def test_segment_includes_leading_pad(make_vad):
    """句首前的緩衝要被接回來，避免第一個字被切掉。"""
    lead = int(FRAMES_PER_SECOND)
    speech = int(FRAMES_PER_SECOND)
    silence = int(FRAMES_PER_SECOND * 0.8)
    script = [0.0] * lead + [1.0] * speech + [0.0] * silence
    vad = make_vad(script, speech_pad_duration=0.1, min_silence_duration=0.6)

    segments = feed(vad, len(script))

    frames = len(segments[0]) // FRAME_BYTES
    # 語句 = 前導緩衝 + 語音 + 觸發判定所需的靜音（frame 數與實作同樣取 round）
    assert frames == vad._pad + speech + vad._silence_limit
    assert vad._pad > 0


def test_oversized_input_is_split_into_frames(make_vad):
    """一次餵入多個 frame 的資料時，每個 frame 都要被處理。"""
    vad = make_vad([1.0] * 100)

    vad.process(b"\x01" * (FRAME_BYTES * 4))

    assert vad._vad.index == 4


def test_multiple_segments_in_one_call_are_all_returned(make_vad):
    """一次呼叫內完成多段語音時，不能只回傳最後一段。"""
    speech = int(FRAMES_PER_SECOND)
    silence = int(FRAMES_PER_SECOND * 0.8)
    script = ([1.0] * speech + [0.0] * silence) * 2
    vad = make_vad(script, min_silence_duration=0.6)

    segments = vad.process(b"\x01" * (FRAME_BYTES * len(script)))

    assert len(segments) == 2


def test_flush_returns_unfinished_speech(make_vad):
    """使用者還在講就結束程式時，最後一段也要取得出來。"""
    speech = int(FRAMES_PER_SECOND)
    vad = make_vad([1.0] * speech)
    feed(vad, speech)

    assert vad.flush() is not None
    assert vad.flush() is None  # 取過就沒了
