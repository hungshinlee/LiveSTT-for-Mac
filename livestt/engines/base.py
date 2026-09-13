"""STT 引擎的共同介面。

所有引擎都吃同一種輸入：16 kHz、單聲道、float32、值域 [-1, 1] 的 numpy 陣列。
音訊格式的正規化由 pipeline 統一處理，引擎不必各自重複轉換。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

SAMPLE_RATE = 16000


class EngineError(RuntimeError):
    """引擎無法使用時拋出（缺少相依套件、缺少權限、不支援的參數等）。"""


class STTEngine(ABC):
    """語音辨識引擎。

    生命週期：``prepare()`` → 多次 ``transcribe()`` → ``close()``。
    ``prepare()`` 負責載入模型與預熱，在背景執行緒中呼叫，可能耗時數秒。
    """

    #: CLI 上的引擎代號
    name: str = ""

    #: 是否支援 task="translate"（翻譯成英文）
    supports_translate: bool = False

    def prepare(self) -> None:
        """載入模型並預熱。預設不做事。"""

    @abstractmethod
    def transcribe(self, audio: np.ndarray) -> str:
        """辨識一段語音，回傳文字；無法辨識時回傳空字串。"""

    def close(self) -> None:
        """釋放資源。預設不做事。"""

    def describe(self) -> str:
        """回傳顯示在啟動訊息中的引擎描述。"""
        return self.name
