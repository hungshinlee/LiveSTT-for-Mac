"""課程／領域詞彙表。

辨識與翻譯需要的詞彙其實高度重疊：一堂 AI 課會反覆出現 BERT、Transformer、
梯度下降，這些詞既要讓 ASR 聽得準，也要讓翻譯用固定的譯法。分成兩個格式
不同的檔案維護很累贅，所以這裡用一個檔案同時餵給兩邊。

格式：

    # 以 # 開頭是註解，空行忽略
    BERT                    ← 只做辨識偏置
    Transformer
    各位同學 = everyone      ← 左邊做辨識偏置，整組做翻譯對照
    梯度下降 = gradient descent
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Terms:
    """辨識熱詞與翻譯術語表。"""

    hotwords: list[str] = field(default_factory=list)
    glossary: dict[str, str] = field(default_factory=dict)

    def merge(self, other: "Terms") -> "Terms":
        """合併兩份詞彙，後者優先。"""
        seen = list(self.hotwords)
        for word in other.hotwords:
            if word not in seen:
                seen.append(word)
        return Terms(hotwords=seen, glossary={**self.glossary, **other.glossary})

    def __bool__(self) -> bool:
        return bool(self.hotwords or self.glossary)


def parse_terms(value: str | None) -> Terms:
    """解析詞彙表。

    ``value`` 可以是檔案路徑，也可以直接是內容（以逗號或換行分隔），
    方便臨時在命令列上補幾個詞。
    """
    if not value:
        return Terms()

    path = Path(value)
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()
    else:
        # 命令列直接給：逗號與換行都當分隔
        lines = value.replace("，", ",").replace(",", "\n").splitlines()

    hotwords: list[str] = []
    glossary: dict[str, str] = {}

    for line in lines:
        entry = line.split("#", 1)[0].strip()
        if not entry:
            continue

        if "=" in entry:
            source, target = entry.split("=", 1)
            source, target = source.strip(), target.strip()
            if not source or not target:
                continue
            glossary[source] = target
            # 左邊同時作為辨識熱詞：聽錯了譯法再準也沒用
            if source not in hotwords:
                hotwords.append(source)
        elif entry not in hotwords:
            hotwords.append(entry)

    return Terms(hotwords=hotwords, glossary=glossary)
