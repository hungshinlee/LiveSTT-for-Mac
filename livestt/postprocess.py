"""辨識結果的後處理。"""
from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def _converter():
    # OpenCC 初始化要讀字典檔，只做一次
    from opencc import OpenCC

    # s2twp：簡體 → 臺灣正體，並套用臺灣慣用詞（「鼠標」→「滑鼠」）
    return OpenCC("s2twp")


def to_taiwan_traditional(text: str) -> str:
    """把簡體中文轉成臺灣繁體中文。"""
    if not text:
        return text
    return _converter().convert(text)
