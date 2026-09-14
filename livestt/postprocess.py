"""辨識結果的後處理。"""
from __future__ import annotations

from functools import lru_cache

#: 預設的 OpenCC 配置。
#:
#: 刻意選 s2tw 而非 s2twp。s2twp 除了字形轉換，還會做「用語在地化」
#: （软件→軟體、内存→記憶體），那是給書面翻譯用的，套在逐字稿上是錯的：
#:
#: - 語音辨識本來就是照發音轉寫，講者說「軟體」時 ASR already 輸出 软体，
#:   字形轉換就足以得到「軟體」。用語映射只在講者真的說了「軟件」時才觸發，
#:   而那時把它改掉等於竄改講者原話。
#: - 它還會誤轉常用詞：「保存」→「儲存」、「文件」→「檔案」。
#:   「客語保存工作」會變成「客語儲存工作」，意思完全不同。
DEFAULT_CONFIG = "s2tw"

#: --opencc 可選的配置
CONFIGS = {
    "s2tw": "簡體 → 臺灣正體（僅字形，預設）",
    "s2twp": "簡體 → 臺灣正體，並轉換大陸用語（软件→軟體）。會誤轉「保存」等詞",
    "s2t": "簡體 → 繁體（不套用臺灣字形偏好）",
}


#: 只套用於臺灣導向的配置（s2t 是通用繁體，不涉及臺灣命名慣例）
TAIWAN_CONFIGS = {"s2tw", "s2twp"}

#: OpenCC 轉換之後要還原的詞。
#:
#: OpenCC 會把「台」一律正規化成「臺」，但語言名稱的官方寫法是「臺灣台語」
#: —— 教育部 2024 年定名時刻意混用兩字。照 OpenCC 的結果會得到「臺灣臺語」，
#: 那不是正式寫法。
#:
#: 這裡只列真正有官方依據的例外，不要拿來做一般性的用詞替換 ——
#: 那正是我們不使用 s2twp 的理由。
EXCEPTIONS = {
    "臺語": "台語",
}


def _apply_exceptions(text: str) -> str:
    for wrong, right in EXCEPTIONS.items():
        text = text.replace(wrong, right)
    return text


@lru_cache(maxsize=4)
def _converter(config: str):
    # OpenCC 初始化要讀字典檔，同一組配置只建一次
    from opencc import OpenCC

    return OpenCC(config)


def to_taiwan_traditional(text: str, config: str = DEFAULT_CONFIG) -> str:
    """把簡體中文轉成臺灣繁體中文。"""
    if not text:
        return text
    converted = _converter(config).convert(text)
    if config in TAIWAN_CONFIGS:
        converted = _apply_exceptions(converted)
    return converted
