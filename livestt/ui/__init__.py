"""輸出端：終端機與浮動字幕視窗。"""
from .base import Sink
from .terminal import TerminalSink

__all__ = ["Sink", "TerminalSink"]
