"""音訊來源的格式轉換測試：重取樣、混音、來源選擇。

測的是我們自己寫的轉換邏輯，不碰 ScreenCaptureKit 與 pyaudio，
所以不需要麥克風、不需要螢幕錄製權限。
"""
import numpy as np
import pytest

from livestt.audio import (
    SAMPLE_RATE,
    AudioError,
    Microphone,
    Resampler,
    create_source,
    downmix,
    float32_to_pcm,
    pcm_to_float32,
)
from livestt.systemaudio import to_mono


def tone(freq: float, seconds: float, rate: int) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def peak_frequency(audio: np.ndarray, rate: int) -> float:
    spectrum = np.abs(np.fft.rfft(audio))
    return float(np.fft.rfftfreq(len(audio), 1 / rate)[np.argmax(spectrum)])


# ---- 重取樣 ---------------------------------------------------------------


def test_passthrough_when_already_at_target_rate():
    audio = tone(440, 0.1, SAMPLE_RATE)
    assert np.array_equal(Resampler(SAMPLE_RATE).process(audio), audio)


@pytest.mark.parametrize("src_rate", [48000, 44100, 32000])
def test_output_length_follows_the_rate_ratio(src_rate):
    output = Resampler(src_rate).process(tone(440, 1.0, src_rate))
    # 濾波器的暖機會吃掉幾個樣本，容許 1% 誤差
    assert abs(len(output) - SAMPLE_RATE) < SAMPLE_RATE * 0.01


def test_tone_survives_downsampling():
    """降頻後音高與音量都不該變。"""
    source = tone(440, 1.0, 48000)
    output = Resampler(48000).process(source)

    assert abs(peak_frequency(output, SAMPLE_RATE) - 440) < 5
    assert output.std() == pytest.approx(source.std(), rel=0.1)


def test_high_frequencies_are_filtered_not_folded_back():
    """15 kHz 不低通就會折成 1 kHz 的假訊號，聽起來像有人在講話。"""
    output = Resampler(48000).process(tone(15000, 1.0, 48000))
    assert output.std() < 0.02  # 幾乎只剩殘量


def test_chunked_processing_matches_whole_signal():
    """狀態要跨 chunk 保留，否則每個接縫都會有一聲喀嗒。"""
    source = tone(440, 0.5, 48000)
    whole = Resampler(48000).process(source)

    streaming = Resampler(48000)
    pieces = [streaming.process(source[i : i + 1024]) for i in range(0, len(source), 1024)]
    chunked = np.concatenate(pieces)

    assert len(chunked) == len(whole)
    assert np.allclose(chunked, whole, atol=1e-6)


def test_odd_chunk_sizes_do_not_lose_samples():
    """SCStream 給的塊大小不固定，長度要隨輸入累積而不是被截掉。"""
    source = tone(440, 1.0, 48000)
    streaming = Resampler(48000)
    total = 0
    start = 0
    for size in [7, 101, 1024, 3, 4096] * 40:
        if start >= len(source):
            break
        total += len(streaming.process(source[start : start + size]))
        start += size
    consumed = min(start, len(source))
    assert abs(total - consumed * SAMPLE_RATE / 48000) < 5


# ---- 混音與格式 -----------------------------------------------------------


def test_downmix_averages_interleaved_channels():
    interleaved = np.array([1.0, 0.0, 1.0, 0.0], dtype=np.float32)  # 左1 右0
    assert np.array_equal(downmix(interleaved, 2), np.array([0.5, 0.5], dtype=np.float32))


def test_non_interleaved_is_plane_major_not_alternating():
    """非交錯的排列是「整個左聲道接著整個右聲道」。

    照交錯去讀的話兩個聲道會互相污染，這個測試就是用來守住這件事。
    """
    left = np.array([1.0, 1.0, 1.0], dtype=np.float32)
    right = np.array([0.0, 0.0, 0.0], dtype=np.float32)
    raw = np.concatenate([left, right])

    assert np.array_equal(to_mono(raw, 2, non_interleaved=True), np.full(3, 0.5, np.float32))
    # 同一筆資料當成交錯來讀會得到完全不同的結果
    assert not np.array_equal(to_mono(raw, 2, non_interleaved=False), np.full(3, 0.5, np.float32))


def test_mono_input_passes_through():
    raw = np.array([0.25, -0.25], dtype=np.float32)
    assert np.array_equal(to_mono(raw, 1, non_interleaved=True), raw)


def test_pcm_roundtrip_and_clipping():
    audio = np.array([0.0, 0.5, -0.5, 2.0, -2.0], dtype=np.float32)
    restored = pcm_to_float32(float32_to_pcm(audio))
    assert restored == pytest.approx([0.0, 0.5, -0.5, 1.0, -1.0], abs=1e-4)


# ---- 來源選擇 -------------------------------------------------------------


def test_create_source_defaults_to_microphone():
    source = create_source()
    assert isinstance(source, Microphone)
    assert source.device is None


def test_create_source_passes_device_to_microphone():
    assert create_source("mic", device=2).device == 2


def test_unknown_source_is_rejected():
    with pytest.raises(AudioError, match="未知的音訊來源"):
        create_source("speaker")


def test_device_with_system_source_is_rejected():
    """系統音訊不經過錄音裝置，靜默忽略只會讓人以為選錯裝置。"""
    with pytest.raises(AudioError, match="--device"):
        create_source("system", device=1)
