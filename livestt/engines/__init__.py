"""引擎註冊表。

新增引擎只需要在這裡多一筆 ``EngineSpec``，CLI 的 --engine 選項、說明文字與
--list 輸出都會跟著更新。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .base import EngineError, STTEngine

DEFAULT_ENGINE = "whisper"


@dataclass(frozen=True)
class EngineSpec:
    name: str
    summary: str
    supports_translate: bool
    #: 引擎需要的額外套件，用於安裝提示
    extra: str
    factory: Callable[..., STTEngine]


def _whisper(**kwargs) -> STTEngine:
    from .whisper_mlx import WhisperMLXEngine

    return WhisperMLXEngine(**kwargs)


def _apple(**kwargs) -> STTEngine:
    from .apple_speech import AppleSpeechEngine

    # Apple 沒有模型可選，忽略 --model
    kwargs.pop("model", None)
    kwargs.pop("task", None)
    return AppleSpeechEngine(**kwargs)


def _qwen(**kwargs) -> STTEngine:
    from .qwen_mlx import QwenASRMLXEngine

    kwargs.pop("task", None)
    return QwenASRMLXEngine(**kwargs)


ENGINES: dict[str, EngineSpec] = {
    "whisper": EngineSpec(
        name="whisper",
        summary="MLX Whisper，唯一支援翻譯成英文，可用本地微調模型",
        supports_translate=True,
        extra="whisper",
        factory=_whisper,
    ),
    "apple": EngineSpec(
        name="apple",
        summary="macOS 內建語音辨識，零下載、延遲最低",
        supports_translate=False,
        extra="apple",
        factory=_apple,
    ),
    "qwen": EngineSpec(
        name="qwen",
        summary="Qwen3-ASR，中文與方言（台語、粵語）準確度最佳，支援熱詞",
        supports_translate=False,
        extra="qwen",
        factory=_qwen,
    ),
}


def create_engine(name: str, **kwargs) -> STTEngine:
    """依名稱建立引擎，並過濾掉該引擎不需要的參數。"""
    try:
        spec = ENGINES[name]
    except KeyError:
        raise EngineError(
            f"未知的引擎 '{name}'，可用：{', '.join(ENGINES)}"
        ) from None

    if kwargs.get("task") == "translate" and not spec.supports_translate:
        raise EngineError(
            f"引擎 '{name}' 不支援翻譯（它是純語音辨識模型）。\n"
            "   要翻譯成英文請改用：--engine whisper --task translate"
        )

    return spec.factory(**kwargs)


__all__ = [
    "DEFAULT_ENGINE",
    "ENGINES",
    "EngineError",
    "EngineSpec",
    "STTEngine",
    "create_engine",
]
