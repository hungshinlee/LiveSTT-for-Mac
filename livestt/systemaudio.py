"""系統音訊擷取（ScreenCaptureKit）。

把電腦本身正在播放的聲音 —— 影片、線上會議、瀏覽器分頁 —— 直接送進辨識，
而不是用麥克風去收喇叭的聲音。聲音照常從喇叭播出，也不必安裝任何虛擬音效卡。

幾個 macOS 特有的細節：

**需要「螢幕與系統音訊錄製」權限，而且改完要重開終端機。**
macOS 只在行程啟動時讀一次 TCC 設定，所以在系統設定裡勾選之後，
必須把終端機**完全結束**再打開，光是開新視窗或新分頁沒有用。

**ScreenCaptureKit 沒有「只擷取聲音」的模式。**
SCStream 一定要綁一個顯示器與畫面尺寸，聲音是附帶的。我們把畫面縮到 2×2、
更新率壓到一秒一張，等於只付出可忽略的畫面擷取成本。

**callback 的 dispatch queue 要自己指定。**
與 `SFSpeechRecognizer` 同一類問題：不給佇列時的行為不保證，
而我們的錄音執行緒沒有 run loop 在跑。指定一條自己的序列佇列最省事。

**`ofType:` 是 NSInteger，不是物件。**
PyObjC 要靠 `SCStreamOutput` protocol 才知道這件事；沒有宣告 protocol 的話
它會把那個整數當成物件指標解讀。

**ASBD 有時是具名結構、有時是純 tuple。**
取決於 `CoreAudio` 模組有沒有被 import 過，而那又取決於使用者選了哪個引擎。
`format_of()` 一律用位置取值，不要改回屬性存取。

**音訊是 48 kHz、float32、非交錯的立體聲。**
pipeline 要的是 16 kHz 單聲道 16-bit PCM，所以降頻與混音在這裡做完。
非交錯的 CMBlockBuffer 是「整個左聲道接著整個右聲道」，不是左右交錯。
"""
from __future__ import annotations

import queue
import threading
from collections.abc import Iterator

import numpy as np

from .audio import (
    CHUNK_SAMPLES,
    AudioError,
    AudioSource,
    Resampler,
    downmix,
    float32_to_pcm,
)

#: 等 ScreenCaptureKit 的 completion handler 回應的逾時（秒）
CALLBACK_TIMEOUT = 10.0

#: 待處理音訊塊的上限。每塊約 20 ms，128 塊約 2.5 秒
MAX_BLOCKS = 128

#: AudioStreamBasicDescription 的格式旗標（CoreAudioBaseTypes.h）
_FLAG_IS_FLOAT = 1 << 0
_FLAG_IS_NON_INTERLEAVED = 1 << 5

#: ASBD 的欄位位置，順序同 CoreAudioBaseTypes.h 的宣告。
#: 不用屬性名的理由見 format_of()。
_ASBD_SAMPLE_RATE = 0
_ASBD_FORMAT_FLAGS = 2
_ASBD_CHANNELS_PER_FRAME = 6
_ASBD_BITS_PER_CHANNEL = 7

PERMISSION_HELP = (
    "沒有「螢幕與系統音訊錄製」權限，無法擷取系統音訊。\n"
    "   請到 系統設定 → 隱私權與安全性 → 螢幕與系統音訊錄製，勾選你的終端機，\n"
    "   然後「完全結束」終端機再重新開啟 —— macOS 只在行程啟動時讀一次這個設定，\n"
    "   開新視窗或新分頁不會生效。"
)

MISSING_PACKAGE_HELP = (
    "缺少系統音訊擷取的相依套件，請執行：\n"
    "   uv pip install -e '.[system]'\n"
    "   （或 uv pip install pyobjc-framework-ScreenCaptureKit pyobjc-framework-libdispatch）"
)


def _import_frameworks():
    """延遲 import，只用麥克風的人不該因為缺這些套件而無法啟動。"""
    try:
        import CoreMedia
        import libdispatch
        import ScreenCaptureKit
    except ImportError as exc:
        raise AudioError(MISSING_PACKAGE_HELP) from exc
    return ScreenCaptureKit, CoreMedia, libdispatch


def shareable_content():
    """取得可擷取的顯示器清單。順便作為權限檢查 —— 沒權限時這一步就會失敗。"""
    ScreenCaptureKit, _, _ = _import_frameworks()

    result: dict[str, object] = {}
    done = threading.Event()

    def handler(content, error) -> None:
        result["content"] = content
        result["error"] = error
        done.set()

    ScreenCaptureKit.SCShareableContent.getShareableContentWithCompletionHandler_(handler)
    # handler 走 ScreenCaptureKit 自己的背景佇列，不需要抽送 run loop
    if not done.wait(CALLBACK_TIMEOUT):
        raise AudioError("等待 ScreenCaptureKit 回應逾時")

    error = result.get("error")
    if error is not None:
        raise AudioError(f"{PERMISSION_HELP}\n   （系統訊息：{error.localizedDescription()}）")

    content = result.get("content")
    if content is None or not content.displays():
        raise AudioError("ScreenCaptureKit 找不到可擷取的顯示器")
    return content


def format_of(asbd) -> tuple[int, int, int, bool]:
    """從 ASBD 讀出 (取樣率, 聲道數, 位元深度, 是否非交錯)。

    **一律用位置取值，不要改成 `asbd.mChannelsPerFrame`。**
    PyObjC 只有在 `CoreAudio` 模組被 import 過之後，才會把 ASBD 包成具名結構；
    沒有的話同一個函式回傳的是純 tuple，屬性存取會直接爆掉。而 `CoreAudio`
    有沒有被 import 到，取決於使用者選了哪個引擎（`apple` 會，`whisper` 不會），
    所以這是個會「換個引擎就壞掉」的陷阱。位置取值對兩種形式都成立。
    """
    try:
        rate = int(asbd[_ASBD_SAMPLE_RATE])
        flags = int(asbd[_ASBD_FORMAT_FLAGS])
        channels = max(1, int(asbd[_ASBD_CHANNELS_PER_FRAME]))
        bits = int(asbd[_ASBD_BITS_PER_CHANNEL])
    except (TypeError, IndexError, ValueError) as exc:
        raise AudioError(f"讀不到音訊格式描述（asbd={asbd!r}）") from exc
    return rate, channels, bits, bool(flags & _FLAG_IS_NON_INTERLEAVED)


def to_mono(raw: np.ndarray, channels: int, non_interleaved: bool) -> np.ndarray:
    """把 CMBlockBuffer 裡的樣本混成單聲道。

    非交錯的排列是「整個左聲道接著整個右聲道」，不是左右左右交錯 ——
    搞錯的話兩個聲道會互相污染，聽起來像被切半再疊起來。
    """
    if channels <= 1:
        return np.ascontiguousarray(raw, dtype=np.float32)
    frames = len(raw) // channels
    if frames == 0:
        return np.zeros(0, dtype=np.float32)
    if not non_interleaved:
        return downmix(raw, channels)
    return raw[: frames * channels].reshape(channels, frames).mean(axis=0).astype(np.float32)


def mono_samples(sample_buffer) -> tuple[np.ndarray, int]:
    """從 CMSampleBuffer 取出 (單聲道 float32, 取樣率)。"""
    import CoreMedia as CM

    description = CM.CMSampleBufferGetFormatDescription(sample_buffer)
    rate, channels, bits, non_interleaved = format_of(
        CM.CMAudioFormatDescriptionGetStreamBasicDescription(description)
    )

    block = CM.CMSampleBufferGetDataBuffer(sample_buffer)
    if block is None:
        raise AudioError("CMSampleBuffer 沒有資料")
    length = CM.CMBlockBufferGetDataLength(block)
    status, data = CM.CMBlockBufferCopyDataBytes(block, 0, length, None)
    if status != 0:
        raise AudioError(f"讀取 CMBlockBuffer 失敗（status={status}）")

    if bits == 32:
        raw = np.frombuffer(data, dtype=np.float32)
    elif bits == 16:
        raw = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    else:
        raise AudioError(f"不支援的系統音訊格式：{bits} bit、{channels} 聲道")

    return to_mono(raw, channels, non_interleaved), rate


_objc_classes = None


def _stream_classes():
    """定義 SCStream 需要的兩個 ObjC 類別。

    同名的 ObjC 類別不能註冊兩次，所以結果要快取；
    又因為相依套件是延遲 import 的，不能寫在模組頂層。
    """
    global _objc_classes
    if _objc_classes is not None:
        return _objc_classes

    import objc
    from Foundation import NSObject

    ScreenCaptureKit, _, _ = _import_frameworks()

    class LiveSTTStreamOutput(
        NSObject, protocols=[objc.protocolNamed("SCStreamOutput")]
    ):
        def stream_didOutputSampleBuffer_ofType_(self, stream, sample_buffer, kind):
            if kind != ScreenCaptureKit.SCStreamOutputTypeAudio:
                return
            source = getattr(self, "source", None)
            if source is not None:
                source._handle(sample_buffer)

    class LiveSTTStreamDelegate(
        NSObject, protocols=[objc.protocolNamed("SCStreamDelegate")]
    ):
        def stream_didStopWithError_(self, stream, error):
            source = getattr(self, "source", None)
            if source is not None:
                source._fail(f"系統音訊擷取中斷：{error.localizedDescription()}")

    _objc_classes = (LiveSTTStreamOutput, LiveSTTStreamDelegate)
    return _objc_classes


class SystemAudio(AudioSource):
    """把 macOS 正在播放的聲音當成錄音來源。"""

    name = "system"

    def __init__(self, exclude_self: bool = True) -> None:
        # 我們自己不放音，但 overlay 模式下未來若加了提示音就會被收進去
        self.exclude_self = exclude_self
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=MAX_BLOCKS)
        self._resampler: Resampler | None = None
        self._stream = None
        self._output = None
        self._delegate = None
        self._handler_queue = None
        self._closed = threading.Event()
        self._failure: str | None = None

    def describe(self) -> str:
        return "系統音訊（電腦正在播放的聲音）"

    def preflight(self) -> None:
        """在載入模型前先確認權限，不要等使用者等完模型才發現不能錄。"""
        shareable_content()

    # ---- 串流 -----------------------------------------------------------

    def __enter__(self) -> "SystemAudio":
        ScreenCaptureKit, CoreMedia, libdispatch = _import_frameworks()
        output_class, delegate_class = _stream_classes()

        display = shareable_content().displays()[0]
        content_filter = ScreenCaptureKit.SCContentFilter.alloc().initWithDisplay_excludingWindows_(
            display, []
        )

        config = ScreenCaptureKit.SCStreamConfiguration.alloc().init()
        config.setCapturesAudio_(True)
        config.setExcludesCurrentProcessAudio_(self.exclude_self)
        # 只要聲音：畫面縮到最小、一秒最多一張，畫面擷取的成本可以忽略
        config.setWidth_(2)
        config.setHeight_(2)
        config.setMinimumFrameInterval_(CoreMedia.CMTimeMake(1, 1))

        self._output = output_class.alloc().init()
        self._output.source = self
        self._delegate = delegate_class.alloc().init()
        self._delegate.source = self

        stream = ScreenCaptureKit.SCStream.alloc().initWithFilter_configuration_delegate_(
            content_filter, config, self._delegate
        )
        # 佇列要自己留一份參照：被 Python 回收掉的話 callback 就沒有地方送
        self._handler_queue = libdispatch.dispatch_queue_create(
            b"com.livestt.systemaudio", None
        )
        ok, error = stream.addStreamOutput_type_sampleHandlerQueue_error_(
            self._output, ScreenCaptureKit.SCStreamOutputTypeAudio, self._handler_queue, None
        )
        if not ok:
            raise AudioError(f"無法掛上系統音訊輸出：{error}")

        self._await_stream(stream.startCaptureWithCompletionHandler_, "啟動")
        self._stream = stream
        return self

    def __exit__(self, *exc_info) -> None:
        self._closed.set()
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                self._await_stream(stream.stopCaptureWithCompletionHandler_, "停止")
            except AudioError:
                # 收尾階段的失敗沒有補救空間，也不該蓋掉真正的錯誤
                pass
        self._output = self._delegate = self._handler_queue = None

    @staticmethod
    def _await_stream(method, what: str) -> None:
        """呼叫 SCStream 的非同步方法並等它完成。"""
        result: dict[str, object] = {}
        done = threading.Event()

        def handler(error) -> None:
            result["error"] = error
            done.set()

        method(handler)
        if not done.wait(CALLBACK_TIMEOUT):
            raise AudioError(f"{what}系統音訊擷取逾時")
        error = result.get("error")
        if error is not None:
            raise AudioError(f"{what}系統音訊擷取失敗：{error.localizedDescription()}")

    # ---- callback -------------------------------------------------------

    def _fail(self, message: str) -> None:
        self._failure = message

    def _handle(self, sample_buffer) -> None:
        """在 dispatch queue 上被呼叫：降頻後丟進佇列，不做任何會阻塞的事。"""
        if self._closed.is_set():
            return
        try:
            mono, rate = mono_samples(sample_buffer)
        except Exception as exc:  # callback 裡拋例外只會被 PyObjC 吞掉
            self._fail(f"系統音訊解碼失敗：{exc}")
            return

        if self._resampler is None or self._resampler.src_rate != rate:
            self._resampler = Resampler(rate)

        data = float32_to_pcm(self._resampler.process(mono))
        if not data:
            return
        try:
            self._queue.put_nowait(data)
        except queue.Full:
            # 辨識端停住了。丟最舊的那塊，理由與 pipeline 佇列滿載時相同
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(data)
            except queue.Full:
                pass

    # ---- 供 pipeline 取用 ------------------------------------------------

    def chunks(self) -> Iterator[bytes]:
        """持續產生固定大小的音訊 frame，直到串流關閉。"""
        target = CHUNK_SAMPLES * 2  # 16-bit
        pending = bytearray()

        while not self._closed.is_set():
            if self._failure is not None:
                raise AudioError(self._failure)
            try:
                pending += self._queue.get(timeout=0.3)
            except queue.Empty:
                continue
            while len(pending) >= target:
                yield bytes(pending[:target])
                del pending[:target]
