"""錄音 → VAD 斷句 → 辨識 → 輸出 的串接。

採生產者／消費者架構，錄音與辨識分屬不同執行緒：辨識較慢時音訊仍持續收，
只會在佇列中堆積，不會漏字。
"""
from __future__ import annotations

import queue
import threading

from .audio import Microphone, pcm_to_float32
from .engines.base import STTEngine
from .postprocess import to_taiwan_traditional
from .translate import Translator
from .ui.base import Sink
from .vad import SileroVAD, VADConfig

#: 佇列上限。堆積到這個程度代表機器跟不上，再收也只是讓延遲無限增加
MAX_PENDING = 32


class Pipeline:
    def __init__(
        self,
        engine: STTEngine,
        sink: Sink,
        vad_config: VADConfig,
        convert_tw: bool = False,
        device: int | None = None,
        translator: Translator | None = None,
        bilingual: bool = False,
        convert_original: bool = False,
    ) -> None:
        self.engine = engine
        self.sink = sink
        self.vad_config = vad_config
        self.convert_tw = convert_tw
        self.device = device
        self.translator = translator
        # 雙語：同時顯示辨識原文與譯文
        self.bilingual = bilingual and translator is not None
        # 原文的簡繁轉換獨立判斷：譯文看目標語言，原文看辨識語言
        self.convert_original = convert_original

        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=MAX_PENDING)
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        """啟動背景執行緒後立刻返回。"""
        self._threads = [
            threading.Thread(target=self._transcribe_loop, name="transcribe", daemon=True),
            threading.Thread(target=self._capture_loop, name="capture", daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        self._stop.set()

    def wait(self, timeout: float | None = None) -> None:
        for thread in self._threads:
            thread.join(timeout=timeout)

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    # ---- 執行緒 ----------------------------------------------------------

    def _transcribe_loop(self) -> None:
        self.sink.on_status("⏳ 正在載入模型…")
        try:
            self.engine.prepare()
            if self.translator is not None:
                self.sink.on_status("⏳ 正在載入翻譯模型…")
                self.translator.prepare()
        except Exception as exc:
            self.sink.on_error(str(exc))
            self._stop.set()
            return

        self._ready.set()
        self.sink.on_status("🎤 等待說話…")

        while not self._stop.is_set():
            try:
                audio_bytes = self._queue.get(timeout=0.3)
            except queue.Empty:
                continue

            try:
                pending = self._queue.qsize()
                self.sink.on_status(
                    f"⏳ 辨識中…（尚有 {pending} 句待處理）" if pending else "⏳ 辨識中…"
                )

                text = self.engine.transcribe(pcm_to_float32(audio_bytes))
                original = None

                if text and self.translator is not None:
                    self.sink.on_status("⏳ 翻譯中…")
                    if self.bilingual:
                        original = (
                            to_taiwan_traditional(text)
                            if self.convert_original
                            else text
                        )
                    text = self.translator.translate(text)

                # 簡繁轉換放在最後，作用對象是實際要顯示的文字
                if self.convert_tw:
                    text = to_taiwan_traditional(text)

                if text:
                    self.sink.on_text(text, original)
                else:
                    self.sink.on_status("🎤 等待說話…")
            except Exception as exc:
                self.sink.on_error(str(exc))
            finally:
                self._queue.task_done()

    def _capture_loop(self) -> None:
        # 等模型就緒再開麥克風，避免預熱期間累積一堆過時音訊
        while not self._ready.is_set():
            if self._stop.wait(0.1):
                return

        vad = SileroVAD(self.vad_config)
        try:
            with Microphone(self.device) as mic:
                for chunk in mic.chunks():
                    if self._stop.is_set():
                        return
                    for segment in vad.process(chunk):
                        self._enqueue(segment)
        except Exception as exc:
            if not self._stop.is_set():
                self.sink.on_error(f"錄音失敗：{exc}")
                self._stop.set()

    def _enqueue(self, segment: bytes) -> None:
        try:
            self._queue.put_nowait(segment)
        except queue.Full:
            # 辨識已經嚴重落後。丟掉最舊的一句換上新的，
            # 寧可少一句，也不要讓字幕跟現場越差越遠
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                pass
            self._queue.put_nowait(segment)
            self.sink.on_error("⚠️ 辨識速度跟不上，已略過最舊的一句")
