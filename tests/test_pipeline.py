"""pipeline 的執行緒、佇列與關閉流程測試。"""
import time

import pytest

import livestt.pipeline as pipeline_module
from livestt.engines.base import STTEngine
from livestt.pipeline import MAX_PENDING, Pipeline
from livestt.ui.base import Sink
from livestt.vad import VADConfig

FRAME = b"\x00" * 1024


class FakeMicrophone:
    """吐出固定 frame 的假麥克風，模擬真實裝置持續供應音訊。"""

    released = False

    def __init__(self, device=None):
        FakeMicrophone.released = False

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        FakeMicrophone.released = True

    def chunks(self):
        while True:
            time.sleep(0.005)
            yield FRAME


class FakeVAD:
    """每 n 次呼叫就產生一段語音。"""

    def __init__(self, config=None, every=3):
        self.every = every
        self.calls = 0

    def process(self, chunk):
        self.calls += 1
        return [b"\x01" * 3200] if self.calls % self.every == 0 else []


class RecordingSink(Sink):
    def __init__(self):
        self.texts = []
        self.originals = []
        self.errors = []
        self.statuses = []

    def on_text(self, text, original=None):
        self.texts.append(text)
        self.originals.append(original)

    def on_status(self, message):
        self.statuses.append(message)

    def on_error(self, message):
        self.errors.append(message)


class CountingEngine(STTEngine):
    name = "counting"

    def __init__(self, delay=0.0, fail_prepare=False):
        self.delay = delay
        self.fail_prepare = fail_prepare
        self.count = 0

    def prepare(self):
        if self.fail_prepare:
            raise RuntimeError("模型載入失敗")

    def transcribe(self, audio):
        time.sleep(self.delay)
        self.count += 1
        return f"句子 {self.count}"


@pytest.fixture(autouse=True)
def fake_audio(monkeypatch):
    monkeypatch.setattr(pipeline_module, "Microphone", FakeMicrophone)
    monkeypatch.setattr(pipeline_module, "SileroVAD", FakeVAD)


def run_until(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_transcribes_segments_and_shuts_down_cleanly():
    sink = RecordingSink()
    pipe = Pipeline(CountingEngine(), sink, VADConfig(), convert_tw=False)
    pipe.start()

    assert run_until(lambda: len(sink.texts) >= 2)

    pipe.stop()
    pipe.wait(timeout=3.0)

    assert not any(thread.is_alive() for thread in pipe._threads)
    assert FakeMicrophone.released
    assert not sink.errors


def test_applies_traditional_conversion(monkeypatch):
    monkeypatch.setattr(
        pipeline_module, "to_taiwan_traditional", lambda text: f"繁[{text}]"
    )
    sink = RecordingSink()
    pipe = Pipeline(CountingEngine(), sink, VADConfig(), convert_tw=True)
    pipe.start()

    assert run_until(lambda: sink.texts)
    pipe.stop()
    pipe.wait(timeout=3.0)

    assert sink.texts[0].startswith("繁[")


def test_failed_prepare_stops_pipeline():
    """模型載不起來時要立刻停止，而不是空轉等待。"""
    sink = RecordingSink()
    pipe = Pipeline(CountingEngine(fail_prepare=True), sink, VADConfig())
    pipe.start()

    assert run_until(lambda: pipe.stopped)
    pipe.wait(timeout=3.0)

    assert "模型載入失敗" in sink.errors[0]


def test_engine_error_does_not_kill_the_loop():
    """單句辨識失敗不應該讓整個程式停掉。"""

    class FlakyEngine(CountingEngine):
        def transcribe(self, audio):
            self.count += 1
            if self.count == 1:
                raise RuntimeError("這句壞了")
            return "後續正常"

    sink = RecordingSink()
    pipe = Pipeline(FlakyEngine(), sink, VADConfig())
    pipe.start()

    assert run_until(lambda: sink.texts)
    pipe.stop()
    pipe.wait(timeout=3.0)

    assert sink.errors and "這句壞了" in sink.errors[0]
    assert sink.texts == ["後續正常"]


class UpperTranslator:
    """假翻譯器：把文字轉大寫，方便辨認哪一段是譯文。"""

    def prepare(self):
        pass

    def translate(self, text):
        return text.upper()

    def close(self):
        pass


def test_translator_output_replaces_text():
    sink = RecordingSink()
    pipe = Pipeline(CountingEngine(), sink, VADConfig(), translator=UpperTranslator())
    pipe.start()

    assert run_until(lambda: sink.texts)
    pipe.stop()
    pipe.wait(timeout=3.0)

    assert sink.texts[0] == "句子 1".upper()
    assert sink.originals[0] is None  # 未開雙語時不送原文


def test_bilingual_passes_original_alongside_translation():
    sink = RecordingSink()
    pipe = Pipeline(
        CountingEngine(), sink, VADConfig(),
        translator=UpperTranslator(), bilingual=True,
    )
    pipe.start()

    assert run_until(lambda: sink.texts)
    pipe.stop()
    pipe.wait(timeout=3.0)

    assert sink.texts[0] == "句子 1".upper()
    assert sink.originals[0] == "句子 1"


def test_bilingual_without_translator_is_inert():
    """沒有翻譯器就沒有原文可言，不該送出重複內容。"""
    sink = RecordingSink()
    pipe = Pipeline(CountingEngine(), sink, VADConfig(), bilingual=True)
    pipe.start()

    assert run_until(lambda: sink.texts)
    pipe.stop()
    pipe.wait(timeout=3.0)

    assert sink.originals[0] is None


def test_original_uses_its_own_conversion_setting(monkeypatch):
    """譯文看目標語言、原文看辨識語言，兩者的簡繁轉換各自獨立。"""
    monkeypatch.setattr(
        pipeline_module, "to_taiwan_traditional", lambda text: f"繁[{text}]"
    )
    sink = RecordingSink()
    pipe = Pipeline(
        CountingEngine(), sink, VADConfig(),
        translator=UpperTranslator(), bilingual=True,
        convert_tw=False, convert_original=True,
    )
    pipe.start()

    assert run_until(lambda: sink.texts)
    pipe.stop()
    pipe.wait(timeout=3.0)

    assert sink.originals[0].startswith("繁[")   # 原文有轉
    assert not sink.texts[0].startswith("繁[")   # 譯文沒轉


def test_queue_drops_oldest_when_recognition_falls_behind():
    """辨識跟不上時丟最舊的一句，避免字幕跟現場越差越遠。"""
    sink = RecordingSink()
    pipe = Pipeline(CountingEngine(delay=10.0), sink, VADConfig())
    pipe.start()

    assert run_until(lambda: any("跟不上" in e for e in sink.errors), timeout=8.0)
    assert pipe._queue.qsize() <= MAX_PENDING

    pipe.stop()
    pipe.wait(timeout=3.0)
