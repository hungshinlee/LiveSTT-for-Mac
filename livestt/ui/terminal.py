"""終端機輸出。"""
from __future__ import annotations

import sys
import threading

from .base import Sink

#: 清除整行並把游標移回行首
CLEAR_LINE = "\033[2K\r"

#: 雙語模式下原文用灰色，讓譯文成為視覺重點
DIM = "\033[2m"
RESET = "\033[0m"


class TerminalSink(Sink):
    """把辨識結果印在終端機上。

    狀態訊息寫在同一行並不斷覆蓋，辨識結果則換行永久保留。
    """

    def __init__(self, stream=None) -> None:
        self._stream = stream or sys.stdout
        self._lock = threading.Lock()
        self._status_shown = False

    def _clear_status(self) -> None:
        if self._status_shown:
            self._stream.write(CLEAR_LINE)
            self._status_shown = False

    def on_text(self, text: str, original: str | None = None) -> None:
        with self._lock:
            self._clear_status()
            if original:
                self._stream.write(f"{DIM}🎙 {original}{RESET}\n")
                self._stream.write(f"📝 {text}\n")
            else:
                self._stream.write(f"📝 {text}\n")
            self._stream.flush()

    def on_status(self, message: str) -> None:
        with self._lock:
            self._stream.write(f"{CLEAR_LINE}{message}")
            self._stream.flush()
            self._status_shown = True

    def on_error(self, message: str) -> None:
        with self._lock:
            self._clear_status()
            self._stream.write(f"❌ {message}\n")
            self._stream.flush()

    def close(self) -> None:
        with self._lock:
            self._clear_status()
            self._stream.flush()
