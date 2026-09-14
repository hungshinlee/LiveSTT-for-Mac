"""Qwen3-ASR 引擎（透過 mlx-audio 在 Apple Silicon 上執行）。

開源 ASR 中文準確度最強的一檔。本專案用得到的是國語、英語，
以及它支援的閩南語（臺灣台語屬於閩南語）。純辨識模型，不能翻譯。

它不支援客語 —— 客語請改用 Whisper 搭配微調模型。
"""
from __future__ import annotations

import threading

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

#: Qwen3-ASR 不支援的語言，各自有更好的去處
UNSUPPORTED = {
    "hak": (
        "Qwen3-ASR 不支援客語。\n"
        "   客語請改用 Whisper 搭配微調模型：\n"
        "   uv run python tools/convert.py formospeech/whisper-large-v2-taiwanese-hakka-v1\n"
        "   uv run livestt -m whisper-large-v2-taiwanese-hakka-v1-mlx"
    ),
}

#: 模型認的是英文語言名稱，不是 ISO 代碼
LANGUAGE_NAMES = {
    "zh": "Chinese",
    "cmn": "Chinese",
    # 臺灣台語屬於閩南語，Qwen3-ASR 把它歸在 Chinese 底下的方言，由模型自行判別
    "nan": "Chinese",
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

    if primary in UNSUPPORTED:
        raise EngineError(UNSUPPORTED[primary])

    name = LANGUAGE_NAMES.get(primary)
    if name is None:
        raise EngineError(
            f"Qwen3-ASR 不支援語言 '{code}'。"
            f"支援的代碼：{', '.join(sorted(LANGUAGE_NAMES))}"
        )
    return name


def _use_thread_lock_for_progress() -> None:
    """讓 tqdm 改用執行緒鎖，而不是 multiprocessing 號誌。

    mlx-audio 內部用 tqdm 顯示進度，而 tqdm 預設會建立一個 multiprocessing 鎖
    —— 即使進度條被停用，鎖仍在 ``tqdm.__new__`` 階段就建好。

    我們是單行程，這個鎖本來就沒必要；更麻煩的是浮動字幕視窗模式結束時，
    ``NSApp.terminate_()`` 會直接在 Objective-C 層砍掉行程，鎖來不及釋放，
    於是 Python 的 resource_tracker 會印出「leaked semaphore objects」警告，
    讓使用者以為程式出了問題。換成執行緒鎖就不會建立號誌。
    """
    try:
        import tqdm

        tqdm.tqdm.set_lock(threading.RLock())
    except Exception:
        # tqdm 只是顯示進度用的，換不成也不影響辨識
        pass


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

        _use_thread_lock_for_progress()
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
