"""辨識結果的後處理。"""
from __future__ import annotations

import re
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

#: 「臺」作為詞尾時，前面常出現的字。
#:
#: 用來避免誤判：「電視臺電話」裡的「臺電」並不是台電公司，
#: 「電視臺語音」裡的「臺語」也不是語言名稱。少了這道防線，
#: 單純的字串取代會把這些句子改壞。
_TAIL_CHARS = "視象文測舞平後前講陽月燈望砲櫃吧天電斷看"

#: OpenCC 轉換之後要還原的專有名詞，格式為 (正規表示式, 取代結果)。
#:
#: 「臺」一律照教育部標準（臺北、臺中、舞臺、電視臺），只有專有名詞例外：
#:
#: - 語言名稱：官方寫法是「臺灣台語」，教育部 2024 年定名時刻意混用兩字
#: - 人名與公司登記名稱：本來就寫「台」，改成「臺」等於寫錯名字
#:
#: 這張表**只收有官方或登記依據的詞**，不要拿來做一般性的用詞替換 ——
#: 那正是我們不使用 s2twp 的理由。
EXCEPTIONS = [
    # 語言名稱
    (rf"(?<![{_TAIL_CHARS}])臺語", "台語"),
    # 人名
    (r"郭臺銘", "郭台銘"),
    # 公司登記名稱（三字以上不需防呆，不會與其他詞相接）
    (r"臺積電", "台積電"),
    (r"臺達電", "台達電"),
    (r"臺灣積體電路", "台灣積體電路"),
    # 公司登記名稱（兩字，需要防呆）
    (rf"(?<![{_TAIL_CHARS}])臺塑", "台塑"),
    (rf"(?<![{_TAIL_CHARS}])臺電(?!視)", "台電"),
    (rf"(?<![{_TAIL_CHARS}])臺泥", "台泥"),
    (rf"(?<![{_TAIL_CHARS}])臺糖", "台糖"),
    (rf"(?<![{_TAIL_CHARS}])臺鹽", "台鹽"),
    (rf"(?<![{_TAIL_CHARS}])臺玻", "台玻"),
    (r"臺灣玻璃工業", "台灣玻璃工業"),
]

_COMPILED = [(re.compile(pattern), replacement) for pattern, replacement in EXCEPTIONS]


def _apply_exceptions(text: str) -> str:
    for pattern, replacement in _COMPILED:
        text = pattern.sub(replacement, text)
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
