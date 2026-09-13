"""Qwen3-ASR 引擎（透過 mlx-audio 在 Apple Silicon 上執行）。

開源 ASR 中文準確度最強的一檔，支援 30 種語言與 22 種漢語方言
（含閩南語、粵語、吳語）。純辨識模型，不能翻譯。
"""
from __future__ import annotations

import numpy as np

from .base import EngineError, STTEngine

DEFAULT_MODEL = "mlx-community/Qwen3-ASR-1.7B-8bit"

#: --list 時顯示的常用模型：(repo, 大小)
KNOWN_MODELS = [
    ("mlx-community/Qwen3-ASR-1.7B-8bit", "~1.8 GB"),
    ("mlx-community/Qwen3-ASR-1.7B-4bit", "~1.0 GB"),
    ("mlx-community/Qwen3-ASR-1.7B-bf16", "~3.4 GB"),
    ("mlx-community/Qwen3-ASR-0.6B-8bit", "~700 MB"),
    ("mlx-community/Qwen3-ASR-0.6B-4bit", "~400 MB"),
]

#: 模型認的是英文語言名稱，不是 ISO 代碼
LANGUAGE_NAMES = {
    "zh": "Chinese",
    "cmn": "Chinese",
    "nan": "Chinese",  # 閩南語屬於 Chinese 底下的方言，由模型自行判別
    "hak": "Chinese",
    "wuu": "Chinese",
    "yue": "Cantonese",
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "pt": "Portuguese",
    "it": "Italian",
    "ru": "Russian",
    "ar": "Arabic",
    "th": "Thai",
    "vi": "Vietnamese",
    "id": "Indonesian",
    "ms": "Malay",
    "nl": "Dutch",
    "tr": "Turkish",
    "hi": "Hindi",
    "sv": "Swedish",
    "da": "Danish",
    "fi": "Finnish",
    "pl": "Polish",
    "cs": "Czech",
    "fil": "Filipino",
    "fa": "Persian",
    "el": "Greek",
    "hu": "Hungarian",
    "mk": "Macedonian",
    "ro": "Romanian",
}


def to_language_name(code: str | None) -> str | None:
    """把 ISO 語言碼轉成 Qwen3-ASR 認得的英文語言名稱。"""
    if not code:
        return None
    primary = code.split("-")[0].lower()
    name = LANGUAGE_NAMES.get(primary)
    if name is None:
        raise EngineError(
            f"Qwen3-ASR 不支援語言 '{code}'。"
            f"支援的代碼：{', '.join(sorted(LANGUAGE_NAMES))}"
        )
    return name


class QwenASRMLXEngine(STTEngine):
    name = "qwen"
    supports_translate = False

    def __init__(
        self,
        model: str | None = None,
        language: str | None = None,
        hotwords: list[str] | None = None,
    ) -> None:
        self.model = model or DEFAULT_MODEL
        self.language = to_language_name(language)
        self.hotwords = hotwords or None
        self._model = None

    def describe(self) -> str:
        extra = f"，熱詞 {len(self.hotwords)} 個" if self.hotwords else ""
        return f"{self.model} (HuggingFace){extra}"

    def prepare(self) -> None:
        try:
            from mlx_audio.stt.utils import load_model
        except ImportError as exc:  # pragma: no cover - 取決於安裝環境
            raise EngineError(
                "缺少 mlx-audio，請執行：uv pip install mlx-audio"
            ) from exc

        self._model = load_model(self.model)

    def transcribe(self, audio: np.ndarray) -> str:
        if self._model is None:
            raise EngineError("引擎尚未 prepare()")

        result = self._model.generate(
            audio,
            language=self.language,
            hotwords=self.hotwords,
            verbose=False,
        )
        return (result.text or "").strip()
