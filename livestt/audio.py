"""音訊來源：麥克風與系統音訊。

所有來源對 pipeline 吐出同一種格式：16 kHz、單聲道、16-bit PCM bytes，
每次 ``CHUNK_SAMPLES`` 個樣本。取樣率轉換與聲道混音都在這一層做完，
pipeline 與引擎因此看不到「48 kHz 立體聲」這種事。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

import numpy as np

#: Silero VAD 要求固定大小的 frame，512 是 16 kHz 下的標準值
CHUNK_SAMPLES = 512
SAMPLE_RATE = 16000
CHANNELS = 1

#: CLI 的 --source 選項，值是一句話說明
SOURCES = {
    "mic": "麥克風",
    "system": "電腦正在播放的聲音（影片、線上會議、瀏覽器分頁）",
}

DEFAULT_SOURCE = "mic"


class AudioError(RuntimeError):
    """音訊來源無法使用時拋出（缺少相依套件、缺少權限、裝置不存在等）。"""


def pcm_to_float32(data: bytes) -> np.ndarray:
    """16-bit PCM bytes → float32 numpy 陣列，值域 [-1, 1]。"""
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


def float32_to_pcm(audio: np.ndarray) -> bytes:
    """float32 numpy 陣列 → 16-bit PCM bytes。超出值域的樣本會被截平。"""
    return (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()


def downmix(audio: np.ndarray, channels: int) -> np.ndarray:
    """多聲道（交錯排列）混成單聲道。"""
    if channels <= 1:
        return np.ascontiguousarray(audio, dtype=np.float32)
    usable = len(audio) - len(audio) % channels
    return audio[:usable].reshape(-1, channels).mean(axis=1).astype(np.float32)


def _lowpass_kernel(cutoff: float, taps: int) -> np.ndarray:
    """窗化 sinc 低通濾波器。``cutoff`` 是相對於來源取樣率的正規化頻率。"""
    offsets = np.arange(taps) - (taps - 1) / 2
    kernel = 2 * cutoff * np.sinc(2 * cutoff * offsets) * np.hamming(taps)
    return (kernel / kernel.sum()).astype(np.float32)


class Resampler:
    """把任意取樣率的單聲道音訊轉成 16 kHz。

    串流用，所以濾波器狀態與取樣相位都跨 chunk 保留 ——
    每個 chunk 各自獨立處理的話，接縫處會有規律的喀嗒聲。
    """

    #: 低通的截止頻率（Hz）。留一點餘裕給濾波器的過渡帶，不要壓在 8 kHz
    CUTOFF_HZ = 7200

    def __init__(self, src_rate: int, taps: int = 63) -> None:
        if src_rate <= 0:
            raise AudioError(f"無效的取樣率：{src_rate}")
        self.src_rate = src_rate
        self._step = src_rate / SAMPLE_RATE

        # 降取樣前一定要低通。影片與音樂在 8 kHz 以上有大量成分，
        # 直接抽樣會把它們整片折回語音頻段，聽感像金屬音，辨識率也跟著掉
        if src_rate > SAMPLE_RATE:
            self._kernel = _lowpass_kernel(self.CUTOFF_HZ / src_rate, taps)
            self._fir_state = np.zeros(taps - 1, dtype=np.float32)
        else:
            self._kernel = None
            self._fir_state = None

        # 線性內插需要跨 chunk 的前一個樣本與小數相位
        self._tail = np.zeros(1, dtype=np.float32)
        self._phase = 0.0

    def process(self, mono: np.ndarray) -> np.ndarray:
        """轉換一塊音訊。輸入太短時可能回傳空陣列，剩下的留到下次。"""
        mono = np.asarray(mono, dtype=np.float32)
        if self.src_rate == SAMPLE_RATE:
            return mono
        if len(mono) == 0:
            return np.zeros(0, dtype=np.float32)

        if self._kernel is not None:
            buffer = np.concatenate([self._fir_state, mono])
            if len(buffer) < len(self._kernel):
                self._fir_state = buffer
                return np.zeros(0, dtype=np.float32)
            # 'valid' 卷積吃掉 taps-1 個樣本，那些樣本是下一塊的前文
            mono = np.convolve(buffer, self._kernel, mode="valid").astype(np.float32)
            self._fir_state = buffer[len(buffer) - len(self._kernel) + 1 :]

        buffer = np.concatenate([self._tail, mono])
        last = len(buffer) - 1
        count = int((last - self._phase) // self._step) + 1 if self._phase <= last else 0
        if count <= 0:
            self._tail = buffer
            return np.zeros(0, dtype=np.float32)

        positions = self._phase + self._step * np.arange(count)
        output = np.interp(positions, np.arange(len(buffer)), buffer)

        # 下一個取樣點可能落在這塊之外（step > 1 時很常見），
        # 保留它左邊那個樣本當前文，相位改成相對於保留處
        next_position = positions[-1] + self._step
        keep = min(int(next_position), last)
        self._tail = buffer[keep:]
        self._phase = next_position - keep
        return output.astype(np.float32)


class AudioSource(ABC):
    """音訊來源。

    生命週期是 context manager：``with source: for chunk in source.chunks()``。
    ``chunks()`` 產生的一律是 16 kHz 單聲道 16-bit PCM，每塊 CHUNK_SAMPLES 個樣本。
    """

    #: CLI 上的來源代號
    name: str = ""

    def preflight(self) -> None:
        """在載入模型前確認這個來源能用。預設不做事。

        權限問題留到開始錄音才爆，使用者已經等了十幾秒的模型載入；
        有代價的檢查（例如系統音訊的權限）在這裡提前做掉。
        """

    def describe(self) -> str:
        """回傳顯示在啟動訊息中的說明。"""
        return SOURCES.get(self.name, self.name)

    def __enter__(self) -> "AudioSource":
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    @abstractmethod
    def chunks(self) -> Iterator[bytes]:
        """持續產生固定大小的音訊 frame，直到來源關閉。"""


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


class Microphone(AudioSource):
    """麥克風錄音串流，用 context manager 確保資源一定釋放。"""

    name = "mic"

    def __init__(self, device: int | None = None) -> None:
        self.device = device
        self._audio = None
        self._stream = None

    def describe(self) -> str:
        return f"麥克風（裝置 {self.device}）" if self.device is not None else "麥克風"

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


def create_source(source: str = DEFAULT_SOURCE, device: int | None = None) -> AudioSource:
    """依 --source 建立音訊來源。"""
    if source not in SOURCES:
        raise AudioError(f"未知的音訊來源 '{source}'，可用的是：{'、'.join(SOURCES)}")

    if source == "system":
        if device is not None:
            raise AudioError(
                "--device 只對 --source mic 有意義。\n"
                "   系統音訊不經過錄音裝置，它直接從 macOS 的音訊輸出擷取。"
            )
        # 相依套件延遲 import：只用麥克風的人不該因為缺 ScreenCaptureKit 而無法啟動
        from .systemaudio import SystemAudio

        return SystemAudio()

    return Microphone(device)
