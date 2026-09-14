"""翻譯層。

辨識與翻譯是兩件事，所以翻譯獨立成一層：任何 STT 引擎的輸出都可以再經過
翻譯送到畫面上。這讓三個引擎都獲得翻譯能力，而且不限於英文 ——
Whisper 內建的 translate 只能翻成英文，這條路則可以翻成任何語言，
包含「翻成中文」這個 Whisper 做不到的方向。
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod

#: 預設選 8bit 而非 4bit。實測 4bit 會漏掉細節 —— 「營收年增 8.7%」的
#: 「年增」、「地點改在第三會議室」的「改」都不見了。多 0.13 秒/句換不漏資訊。
DEFAULT_MODEL = "mlx-community/Qwen3-4B-Instruct-2507-8bit"

#: --list 時顯示的常用翻譯模型：(repo, 大小, 說明)
KNOWN_MODELS = [
    ("mlx-community/Qwen3-4B-Instruct-2507-8bit", "~4.3 GB", "預設，品質最佳"),
    ("mlx-community/Qwen3-4B-Instruct-2507-4bit", "~2.3 GB", "快 0.13 秒，但會漏細節"),
    ("mlx-community/Qwen3-1.7B-4bit", "~1.0 GB", "最輕量，術語較易出錯"),
]

#: 語言代碼 → 給模型看的自然語言名稱
LANGUAGE_NAMES = {
    "en": "English",
    "zh": "Traditional Chinese (Taiwan)",
    "zh-tw": "Traditional Chinese (Taiwan)",
    "zh-hk": "Traditional Chinese (Hong Kong)",
    "zh-cn": "Simplified Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "ru": "Russian",
    "th": "Thai",
    "vi": "Vietnamese",
    "id": "Indonesian",
    "ar": "Arabic",
    "hi": "Hindi",
    "nl": "Dutch",
    "tr": "Turkish",
}

#: 目標語言屬於繁體中文時，最後再過一次 OpenCC 當保險
TRADITIONAL_TARGETS = {"zh", "zh-tw", "zh-hk"}


def resolve_language(value: str) -> str:
    """把 --translate-to 的值轉成給模型看的語言名稱。

    代碼（``ja``）會查表；查不到就原樣送出，讓使用者可以直接寫
    ``"Traditional Chinese"`` 或 ``"Taiwanese Hokkien"`` 這種自由描述。
    """
    return LANGUAGE_NAMES.get(value.strip().lower(), value.strip())


def targets_traditional_chinese(value: str) -> bool:
    """判斷目標語言是不是繁體中文。"""
    normalized = value.strip().lower()
    if normalized in TRADITIONAL_TARGETS:
        return True
    return "traditional" in normalized and "chinese" in normalized


def parse_glossary(value: str | None) -> dict[str, str]:
    """解析 --glossary。

    接受 ``原文=譯文`` 以逗號分隔，或每行一組的檔案。
    """
    if not value:
        return {}

    from pathlib import Path

    path = Path(value)
    if path.is_file():
        entries = path.read_text(encoding="utf-8").splitlines()
    else:
        entries = value.replace("，", ",").split(",")

    glossary = {}
    for entry in entries:
        entry = entry.strip()
        if not entry or "=" not in entry:
            continue
        source, target = entry.split("=", 1)
        if source.strip() and target.strip():
            glossary[source.strip()] = target.strip()
    return glossary


class Translator(ABC):
    """翻譯器。生命週期與 STTEngine 相同：prepare → translate → close。"""

    name: str = ""

    def prepare(self) -> None:
        """載入模型。在背景執行緒中呼叫，可能耗時。"""

    @abstractmethod
    def translate(self, text: str) -> str:
        """翻譯一句話。"""

    def close(self) -> None:
        """釋放資源。"""

    def describe(self) -> str:
        return self.name


#: LLM 偶爾會加上引號或「Translation:」之類的前綴，送到字幕前要清掉
_PREFIXES = re.compile(
    r"^\s*(translation|translated text|譯文|翻譯)\s*[:：]\s*", re.IGNORECASE
)
_FENCE = re.compile(r"^```[a-zA-Z]*\n?|\n?```$")


def _clean(text: str) -> str:
    text = _FENCE.sub("", text.strip()).strip()
    text = _PREFIXES.sub("", text).strip()
    # 去掉整句被包起來的成對引號
    for left, right in (('"', '"'), ("「", "」"), ("“", "”"), ("'", "'")):
        if len(text) > 1 and text.startswith(left) and text.endswith(right):
            text = text[1:-1].strip()
    # 只取第一段：模型有時會多附一段解釋
    return text.split("\n\n")[0].strip()


class QwenLMTranslator(Translator):
    """用 Qwen3 指令模型翻譯（透過 mlx-lm）。"""

    name = "qwen-lm"

    def __init__(
        self,
        target: str,
        model: str | None = None,
        glossary: dict[str, str] | None = None,
    ) -> None:
        self.target_raw = target
        self.target = resolve_language(target)
        self.model = model or DEFAULT_MODEL
        self.glossary = glossary or {}
        self._model = None
        self._tokenizer = None
        self._sampler = None

    def describe(self) -> str:
        extra = f"，術語 {len(self.glossary)} 組" if self.glossary else ""
        return f"{self.model} → {self.target}{extra}"

    def _system_prompt(self) -> str:
        prompt = (
            f"You are a translation engine. Translate the user's text into {self.target}. "
            "Output ONLY the translation: no explanation, no quotes, no original text. "
            "The input comes from live speech recognition and may be incomplete "
            "or contain errors; translate what is there and do not invent content."
        )
        if self.glossary:
            terms = "; ".join(f"{k} = {v}" for k, v in self.glossary.items())
            prompt += f"\nAlways use these fixed term translations: {terms}"
        return prompt

    def prepare(self) -> None:
        try:
            from mlx_lm import load
            from mlx_lm.sample_utils import make_sampler
        except ImportError as exc:  # pragma: no cover - 取決於安裝環境
            raise RuntimeError(
                "缺少 mlx-lm，請執行：uv pip install mlx-lm"
            ) from exc

        self._model, self._tokenizer = load(self.model)
        # temp=0：翻譯要可重現，不要每次講同一句得到不同結果
        self._sampler = make_sampler(temp=0.0)

        self.translate("測試")  # 預熱，順便驗證 chat template 可用

    def _build_prompt(self, text: str) -> str:
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": text},
        ]
        try:
            # 非 thinking 模式：思考過程會讓延遲從零點幾秒暴增到數秒
            return self._tokenizer.apply_chat_template(
                messages,
                add_generation_prompt=True,
                tokenize=False,
                enable_thinking=False,
            )
        except TypeError:
            # 2507 之後的 Instruct 模型沒有 thinking，也就沒有這個參數
            return self._tokenizer.apply_chat_template(
                messages, add_generation_prompt=True, tokenize=False
            )

    def translate(self, text: str) -> str:
        if self._model is None:
            raise RuntimeError("翻譯器尚未 prepare()")
        if not text.strip():
            return ""

        from mlx_lm import generate

        # 上限隨輸入長度縮放。固定值會讓長句被硬生生截斷，
        # 給太大又會讓模型有空間開始胡言亂語
        source_tokens = len(self._tokenizer.encode(text))
        max_tokens = min(512, max(48, source_tokens * 3 + 24))

        output = generate(
            self._model,
            self._tokenizer,
            prompt=self._build_prompt(text),
            max_tokens=max_tokens,
            sampler=self._sampler,
            verbose=False,
        )
        return _clean(output)
