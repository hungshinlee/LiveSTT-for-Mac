"""逐字稿輸出。

浮動字幕視窗的內容講完就消失了，簡報結束後沒有任何紀錄。這個模組把每一句
辨識結果寫進檔案，並保留時間資訊，因此也能直接輸出成 SRT 字幕檔。

每寫一句就 flush，程式若意外中斷，已辨識的部分不會遺失。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

#: 副檔名 → 格式
FORMATS = {
    ".txt": "text",
    ".log": "text",
    ".md": "text",
    ".srt": "srt",
}


@dataclass(frozen=True)
class Entry:
    """一句辨識結果及其時間位置（秒，相對於工作階段開始）。"""

    index: int
    start: float
    end: float
    text: str
    original: str | None = None


def _clock(seconds: float) -> str:
    """秒 → HH:MM:SS"""
    total = max(0, int(seconds))
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def _srt_time(seconds: float) -> str:
    """秒 → SRT 的 HH:MM:SS,mmm"""
    seconds = max(0.0, seconds)
    milliseconds = int(round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def detect_format(path: Path) -> str:
    """由副檔名決定格式，未知副檔名一律當純文字。"""
    return FORMATS.get(path.suffix.lower(), "text")


class TranscriptWriter:
    """把辨識結果寫進檔案。

    用 context manager 確保檔案一定關閉：

        with TranscriptWriter(Path("talk.srt")) as log:
            log.write(entry)
    """

    def __init__(self, path: Path, header: str | None = None) -> None:
        self.path = path
        self.format = detect_format(path)
        self.header = header
        self._file = None

    def __enter__(self) -> "TranscriptWriter":
        self.open()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("w", encoding="utf-8")
        # SRT 不能有註解，所以標頭只寫在純文字格式
        if self.format == "text":
            started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._file.write(f"# LiveSTT 逐字稿\n# 開始時間：{started}\n")
            if self.header:
                self._file.write(f"# {self.header}\n")
            self._file.write("\n")
            self._file.flush()

    def write(self, entry: Entry) -> None:
        if self._file is None:
            return
        if self.format == "srt":
            self._write_srt(entry)
        else:
            self._write_text(entry)
        # 每句都 flush：簡報中途當掉時，已講的部分要保得住
        self._file.flush()

    def _write_text(self, entry: Entry) -> None:
        stamp = f"[{_clock(entry.start)}] "
        if entry.original:
            self._file.write(f"{stamp}{entry.original}\n")
            self._file.write(f"{' ' * len(stamp)}→ {entry.text}\n")
        else:
            self._file.write(f"{stamp}{entry.text}\n")

    def _write_srt(self, entry: Entry) -> None:
        body = f"{entry.original}\n{entry.text}" if entry.original else entry.text
        self._file.write(
            f"{entry.index}\n"
            f"{_srt_time(entry.start)} --> {_srt_time(entry.end)}\n"
            f"{body}\n\n"
        )

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
