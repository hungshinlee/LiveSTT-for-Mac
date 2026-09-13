"""Silero VAD 語音活動偵測。

比單純的音量門檻準確得多，能區分人聲與背景噪音（鍵盤聲、冷氣聲等），
負責把連續的音訊流切成一句一句。
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from pysilero_vad import SileroVoiceActivityDetector


@dataclass
class VADConfig:
    """VAD 參數。預設值與 CLI 預設值一致。"""

    #: 語音機率門檻（0.0–1.0），越高越嚴格
    speech_threshold: float = 0.5

    #: 語音結束後要有多長的靜音才算一句講完（秒）
    min_silence_duration: float = 0.6

    #: 最短語音長度（秒），比這短的片段視為雜訊丟棄
    min_speech_duration: float = 0.2

    #: 語音起點前保留的緩衝（秒），避免句首被切掉
    speech_pad_duration: float = 0.1

    sample_rate: int = 16000


class SileroVAD:
    """把音訊流切成完整語句。

        vad = SileroVAD(VADConfig())
        for chunk in microphone:
            for segment in vad.process(chunk):
                transcribe(segment)
    """

    def __init__(self, config: VADConfig | None = None) -> None:
        self.config = config or VADConfig()
        self._vad = SileroVoiceActivityDetector()

        # Silero 只吃固定大小的 frame
        self.chunk_samples = self._vad.chunk_samples()
        self.chunk_bytes = self._vad.chunk_bytes()

        chunks_per_second = self.config.sample_rate / self.chunk_samples
        self._silence_limit = max(
            1, round(self.config.min_silence_duration * chunks_per_second)
        )
        self._min_speech = max(
            1, round(self.config.min_speech_duration * chunks_per_second)
        )
        self._pad = max(1, round(self.config.speech_pad_duration * chunks_per_second))

        self.reset()

    def reset(self) -> None:
        """回到未偵測到語音的初始狀態。"""
        self._speaking = False
        self._silence_count = 0
        self._speech_count = 0
        self._buffer: list[bytes] = []
        # 語音開始前的音訊，用來補回句首
        self._pre_buffer: deque[bytes] = deque(maxlen=self._pad)

    def process(self, audio_bytes: bytes) -> list[bytes]:
        """餵入音訊，回傳這次呼叫中完成的語句（通常是 0 或 1 段）。

        傳入的資料長度不必剛好是一個 frame，過長會自動切開逐一處理，
        因此一次呼叫可能完成不只一段語音。
        """
        segments = []
        for offset in range(0, len(audio_bytes) - self.chunk_bytes + 1, self.chunk_bytes):
            segment = self._process_frame(
                audio_bytes[offset : offset + self.chunk_bytes]
            )
            if segment is not None:
                segments.append(segment)
        return segments

    def _process_frame(self, frame: bytes) -> bytes | None:
        is_speech = self._vad(frame) >= self.config.speech_threshold

        if is_speech:
            if not self._speaking:
                # 語音起點：把前導緩衝接上，避免第一個字被切掉
                self._speaking = True
                self._speech_count = 0
                self._buffer = list(self._pre_buffer)
            self._buffer.append(frame)
            self._speech_count += 1
            self._silence_count = 0
            return None

        self._pre_buffer.append(frame)
        if not self._speaking:
            return None

        # 說話中遇到靜音：先收著，靜音夠久才算講完
        self._buffer.append(frame)
        self._silence_count += 1
        if self._silence_count < self._silence_limit:
            return None

        long_enough = self._speech_count >= self._min_speech
        segment = b"".join(self._buffer) if long_enough else None
        self.reset()
        return segment

    def flush(self) -> bytes | None:
        """收尾：取出還沒講完但已經夠長的最後一段語音。"""
        segment = (
            b"".join(self._buffer)
            if self._speaking and self._speech_count >= self._min_speech
            else None
        )
        self.reset()
        return segment
