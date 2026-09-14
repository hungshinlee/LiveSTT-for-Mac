"""MLX Whisper 引擎。

唯一支援 translate（翻譯成英文）的引擎，也是本地轉換模型（例如臺灣客語）
的唯一執行路徑。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .base import SAMPLE_RATE, EngineError, STTEngine

DEFAULT_MODEL = "mlx-community/whisper-large-v3-mlx"

#: tools/convert.py 產出的本地模型放這裡
MODELS_DIR = Path(__file__).resolve().parent.parent.parent / "models"

#: --list 時顯示的常用模型：(repo, 大小, 是否支援翻譯)
KNOWN_MODELS = [
    ("mlx-community/whisper-large-v3-mlx", "~3 GB", True),
    ("mlx-community/whisper-large-v3-turbo", "~1.6 GB", False),
    ("mlx-community/whisper-medium-mlx", "~1.5 GB", True),
    ("mlx-community/whisper-small-mlx", "~488 MB", True),
    ("mlx-community/whisper-base-mlx", "~145 MB", True),
    ("mlx-community/whisper-tiny-mlx", "~75 MB", True),
]


def local_models() -> list[str]:
    """列出 models/ 底下已轉換完成的模型。"""
    if not MODELS_DIR.is_dir():
        return []
    return sorted(
        path.name
        for path in MODELS_DIR.iterdir()
        if path.is_dir()
        and (path / "config.json").exists()
        and (path / "weights.npz").exists()
    )


def resolve_model(name: str | None) -> str:
    """把使用者給的模型名稱解析成 mlx_whisper 能吃的路徑或 HF repo。

    未指定時優先使用本地模型，其次才是預設的 HF 模型。
    """
    if name is None:
        found = local_models()
        return str(MODELS_DIR / found[0]) if found else DEFAULT_MODEL

    # 帶斜線視為 HF repo 或絕對路徑
    if "/" in name:
        return name

    for candidate in (name, f"{name}-mlx"):
        path = MODELS_DIR / candidate
        if not path.is_dir():
            continue
        if not (path / "weights.npz").exists():
            # 目錄在但權重不在：轉換沒跑完。導向 HuggingFace 只會得到
            # 令人困惑的 404，不如直接說清楚
            raise EngineError(
                f"本地模型 '{candidate}' 不完整，缺少 weights.npz。\n"
                f"   請重新轉換：uv run python tools/convert.py <hf-repo> --force"
            )
        return str(path)

    # 當成 mlx-community 的簡寫，例如 whisper-medium-mlx
    return f"mlx-community/{name}"


def is_local(model: str) -> bool:
    """判斷解析後的模型是本地路徑還是 HF repo。"""
    return "/" not in model or model.startswith("/")


class WhisperMLXEngine(STTEngine):
    name = "whisper"
    supports_translate = True

    def __init__(
        self,
        model: str | None = None,
        language: str | None = None,
        task: str = "transcribe",
        hotwords: list[str] | None = None,
        context: str | None = None,
    ) -> None:
        self.model = resolve_model(model)
        self.task = task
        # Whisper 用 ISO 主要語言碼，zh-TW 之類的地區碼要去掉
        self.language = language.split("-")[0] if language else None
        # Whisper 沒有熱詞 API，只能用 initial_prompt 做提示條件化。
        # 效果不如真正的熱詞偏置，提示太長還可能誘發幻覺，所以只串成一句短的。
        self.context = (context or "").strip() or None
        parts = [p for p in (self.context, "、".join(hotwords) if hotwords else None) if p]
        self.initial_prompt = " ".join(parts) or None
        self.hotwords = hotwords or []
        self._transcribe = None

    def describe(self) -> str:
        label = Path(self.model).name if is_local(self.model) else self.model
        source = "本地" if is_local(self.model) else "HuggingFace"
        extra = f"，提示詞 {len(self.hotwords)} 個" if self.hotwords else ""
        return f"{label} ({source}){extra}"

    def prepare(self) -> None:
        try:
            import mlx_whisper
        except ImportError as exc:  # pragma: no cover - 取決於安裝環境
            raise EngineError(
                "缺少 mlx-whisper，請執行：uv pip install mlx-whisper"
            ) from exc

        self._transcribe = mlx_whisper.transcribe
        # 用一秒靜音跑一次，把模型載入記憶體，避免第一句話被拖慢
        self._run(np.zeros(SAMPLE_RATE, dtype=np.float32))

    def _run(self, audio: np.ndarray) -> str:
        kwargs = {"path_or_hf_repo": self.model, "task": self.task}
        if self.language:
            kwargs["language"] = self.language
        if self.initial_prompt:
            kwargs["initial_prompt"] = self.initial_prompt
        return self._transcribe(audio, **kwargs)["text"].strip()

    def transcribe(self, audio: np.ndarray) -> str:
        if self._transcribe is None:
            raise EngineError("引擎尚未 prepare()")
        return self._run(audio)
