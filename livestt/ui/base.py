"""輸出介面。

pipeline 只透過這個介面回報結果，因此終端機輸出與浮動字幕視窗可以互換。
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class Sink(ABC):
    """辨識結果的顯示端。"""

    @abstractmethod
    def on_text(self, text: str, original: str | None = None) -> None:
        """收到一句結果。

        Args:
            text: 要顯示的主要文字（有翻譯時是譯文）。
            original: 雙語模式下的原文；不顯示原文時為 None。
        """

    def on_status(self, message: str) -> None:
        """狀態訊息（等待中、辨識中、佇列堆積等），可被後續訊息覆蓋。"""

    def on_error(self, message: str) -> None:
        """錯誤訊息。"""

    def close(self) -> None:
        """收尾。"""
