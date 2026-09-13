"""麥克風擷取。"""
from __future__ import annotations

from collections.abc import Iterator

import numpy as np

#: Silero VAD 要求固定大小的 frame，512 是 16 kHz 下的標準值
CHUNK_SAMPLES = 512
SAMPLE_RATE = 16000
CHANNELS = 1


def pcm_to_float32(data: bytes) -> np.ndarray:
    """16-bit PCM bytes → float32 numpy 陣列，值域 [-1, 1]。"""
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


def input_devices() -> list[tuple[int, str, int]]:
    """列出可用的錄音裝置：(index, 名稱, 最大輸入聲道數)。"""
    import pyaudio

    audio = pyaudio.PyAudio()
    try:
        devices = []
        for index in range(audio.get_device_count()):
            info = audio.get_device_info_by_index(index)
            channels = int(info.get("maxInputChannels", 0))
            if channels > 0:
                devices.append((index, str(info.get("name", "?")), channels))
        return devices
    finally:
        audio.terminate()


class Microphone:
    """麥克風錄音串流，用 context manager 確保資源一定釋放。"""

    def __init__(self, device: int | None = None) -> None:
        self.device = device
        self._audio = None
        self._stream = None

    def __enter__(self) -> "Microphone":
        import pyaudio

        self._audio = pyaudio.PyAudio()
        try:
            self._stream = self._audio.open(
                format=pyaudio.paInt16,
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                input=True,
                input_device_index=self.device,
                frames_per_buffer=CHUNK_SAMPLES,
            )
        except Exception:
            self._audio.terminate()
            self._audio = None
            raise
        return self

    def __exit__(self, *exc_info) -> None:
        if self._stream is not None:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        if self._audio is not None:
            self._audio.terminate()
            self._audio = None

    def chunks(self) -> Iterator[bytes]:
        """持續產生固定大小的音訊 frame，直到串流關閉。"""
        while self._stream is not None:
            try:
                yield self._stream.read(CHUNK_SAMPLES, exception_on_overflow=False)
            except Exception:
                # 串流被關閉或裝置被拔除
                return
