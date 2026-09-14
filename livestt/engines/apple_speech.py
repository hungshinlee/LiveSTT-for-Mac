"""Apple Speech 引擎（SFSpeechRecognizer，透過 PyObjC）。

完全不需要下載模型，辨識由 macOS 內建的語音引擎負責，延遲最低。
強制使用裝置端辨識（requiresOnDeviceRecognition），確保音訊不會離開這台機器。

實作上有兩個 macOS 特有的細節：

1. 首次使用需要使用者授權，授權對話框由系統跳出。
2. 辨識結果透過 callback 回傳，而 callback 需要有 run loop 在跑才會被送達。
   我們的辨識工作跑在背景執行緒上（沒有 run loop），所以等待結果時必須
   手動抽送目前執行緒的 run loop，見 ``_pump``。
"""
from __future__ import annotations

import threading
import time

import numpy as np

from .base import SAMPLE_RATE, EngineError, STTEngine

#: 單段語音的辨識逾時（秒）
RECOGNITION_TIMEOUT = 30.0

#: 等待使用者在授權對話框上點選的逾時（秒）
AUTHORIZATION_TIMEOUT = 60.0

#: --language 沒給時的候選 locale，依序嘗試
FALLBACK_LOCALES = ["zh-TW", "en-US"]


def _pump(event: threading.Event, timeout: float) -> bool:
    """等待 event，同時抽送目前執行緒的 run loop。

    callback 可能被送到本執行緒的 run loop，也可能被送到背景 dispatch queue。
    兩種情況都要能收到，所以這裡交錯進行 run loop 抽送與 event 等待。
    """
    from Foundation import NSDate, NSDefaultRunLoopMode, NSRunLoop

    loop = NSRunLoop.currentRunLoop()
    deadline = time.monotonic() + timeout
    while not event.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        loop.runMode_beforeDate_(
            NSDefaultRunLoopMode,
            NSDate.dateWithTimeIntervalSinceNow_(min(0.05, remaining)),
        )
        # runMode_beforeDate_ 在沒有 input source 時會立刻返回，
        # 這裡補一個短等待避免空轉燒 CPU
        event.wait(0.005)
    return True


def _to_pcm_buffer(audio: np.ndarray):
    """把 float32 numpy 陣列包成 AVAudioPCMBuffer。"""
    from AVFoundation import AVAudioFormat, AVAudioPCMBuffer

    audio = np.ascontiguousarray(audio, dtype=np.float32)
    frames = len(audio)

    fmt = AVAudioFormat.alloc().initWithCommonFormat_sampleRate_channels_interleaved_(
        1,  # AVAudioPCMFormatFloat32
        float(SAMPLE_RATE),
        1,
        False,
    )
    buffer = AVAudioPCMBuffer.alloc().initWithPCMFormat_frameCapacity_(fmt, frames)
    if buffer is None:
        raise EngineError("無法建立 AVAudioPCMBuffer")
    buffer.setFrameLength_(frames)

    # floatChannelData() 回傳指向各聲道的指標陣列，PyObjC 把它表示成 varlist；
    # as_buffer() 取得可寫入的記憶體視圖，參數是元素個數而非位元組數
    channel = buffer.floatChannelData()[0]
    view = np.frombuffer(channel.as_buffer(frames), dtype=np.float32)
    view[:] = audio
    return buffer


def supported_locales() -> list[str]:
    """列出這台機器上可用的辨識語言。"""
    try:
        from Speech import SFSpeechRecognizer
    except ImportError as exc:
        raise EngineError(
            "缺少 pyobjc-framework-Speech，請執行："
            "uv pip install pyobjc-framework-Speech pyobjc-framework-AVFoundation"
        ) from exc

    return sorted(
        str(locale.localeIdentifier()).replace("_", "-")
        for locale in SFSpeechRecognizer.supportedLocales()
    )


def _pick_locale(language: str | None) -> str:
    """挑一個 macOS 支援、且最接近使用者要求的 locale。"""
    available = supported_locales()
    lookup = {loc.lower(): loc for loc in available}

    if language:
        wanted = language.replace("_", "-")
        # 完全比對，例如 zh-TW
        if wanted.lower() in lookup:
            return lookup[wanted.lower()]
        # 只給主語言碼時，取同語言的第一個，例如 zh -> zh-TW
        primary = wanted.split("-")[0].lower()
        matches = [loc for loc in available if loc.lower().split("-")[0] == primary]
        if matches:
            # 偏好清單裡的優先，否則取第一個
            for preferred in FALLBACK_LOCALES:
                if preferred in matches:
                    return preferred
            return matches[0]
        raise EngineError(
            f"macOS 語音辨識不支援語言 '{language}'。"
            f"可用語言請執行：livestt --list-locales"
        )

    # 沒指定語言：先看系統語言，再退回偏好清單
    from Foundation import NSLocale

    current = str(NSLocale.currentLocale().localeIdentifier()).replace("_", "-")
    for candidate in [current, *FALLBACK_LOCALES]:
        if candidate.lower() in lookup:
            return lookup[candidate.lower()]
    return available[0]


class AppleSpeechEngine(STTEngine):
    name = "apple"
    supports_translate = False

    def __init__(
        self,
        language: str | None = None,
        hotwords: list[str] | None = None,
        punctuation: bool = True,
        context: str | None = None,
    ) -> None:
        # SFSpeechRecognizer 只吃 contextualStrings（詞彙清單），
        # 沒有可放自由文字的欄位，所以 context 對它無效
        del context
        self.language = language
        self.hotwords = hotwords or []
        self.punctuation = punctuation
        # 在這裡就決定 locale，這樣啟動訊息（describe）才顯示得出來，
        # 語言不支援也能在載入模型前就報錯
        self.locale = _pick_locale(language)
        self._recognizer = None

    def describe(self) -> str:
        extra = f"，熱詞 {len(self.hotwords)} 個" if self.hotwords else ""
        return f"macOS 內建語音辨識（{self.locale}，裝置端{extra}）"

    def prepare(self) -> None:
        try:
            from Foundation import NSLocale
            from Speech import SFSpeechRecognizer
        except ImportError as exc:
            raise EngineError(
                "缺少 pyobjc-framework-Speech，請執行："
                "uv pip install pyobjc-framework-Speech pyobjc-framework-AVFoundation"
            ) from exc

        self._authorize()

        ns_locale = NSLocale.alloc().initWithLocaleIdentifier_(self.locale)
        recognizer = SFSpeechRecognizer.alloc().initWithLocale_(ns_locale)
        if recognizer is None:
            raise EngineError(f"無法建立 locale 為 {self.locale} 的語音辨識器")
        if not recognizer.isAvailable():
            raise EngineError(
                f"語音辨識器目前無法使用（locale={self.locale}）。"
                "請確認系統設定 → 鍵盤 → 聽寫 已開啟。"
            )
        if not recognizer.supportsOnDeviceRecognition():
            raise EngineError(
                f"{self.locale} 尚未下載裝置端辨識模型。請到"
                "系統設定 → 鍵盤 → 聽寫，把該語言加入聽寫語言後再試一次。"
            )

        recognizer.setDefaultTaskHint_(1)  # SFSpeechRecognitionTaskHintDictation

        # 預設 callback 會送到 app 的主佇列。辨識跑在背景執行緒、主執行緒又沒有
        # run loop 在跑時，callback 永遠不會被送達而導致逾時。
        # 指定一條我們自己的背景佇列，callback 就與主執行緒無關了。
        from Foundation import NSOperationQueue

        queue = NSOperationQueue.alloc().init()
        queue.setMaxConcurrentOperationCount_(1)
        recognizer.setQueue_(queue)

        self._recognizer = recognizer

        # 用一小段靜音跑一次，把「聽寫未開啟」這類系統層設定問題在啟動時就攤開，
        # 不要等到使用者講完第一句話才失敗
        self.transcribe(np.zeros(SAMPLE_RATE // 2, dtype=np.float32))

    @staticmethod
    def _authorize() -> None:
        from Speech import SFSpeechRecognizer

        status = SFSpeechRecognizer.authorizationStatus()
        if status == 3:  # Authorized
            return
        if status in (1, 2):  # Denied / Restricted
            raise EngineError(
                "語音辨識權限遭拒。請到系統設定 → 隱私權與安全性 → 語音辨識，"
                "允許終端機使用。"
            )

        # NotDetermined：跳出系統授權對話框，等待使用者回應
        print("⏳ 正在請求語音辨識權限，請在系統對話框中允許…")
        result: dict[str, int] = {}
        done = threading.Event()

        def handler(new_status: int) -> None:
            result["status"] = new_status
            done.set()

        SFSpeechRecognizer.requestAuthorization_(handler)
        if not _pump(done, AUTHORIZATION_TIMEOUT):
            raise EngineError("等待語音辨識授權逾時")
        if result.get("status") != 3:
            raise EngineError("使用者未授權語音辨識")

    def transcribe(self, audio: np.ndarray) -> str:
        if self._recognizer is None:
            raise EngineError("引擎尚未 prepare()")

        from Speech import SFSpeechAudioBufferRecognitionRequest

        request = SFSpeechAudioBufferRecognitionRequest.alloc().init()
        request.setShouldReportPartialResults_(False)
        request.setRequiresOnDeviceRecognition_(True)
        request.setAddsPunctuation_(self.punctuation)
        if self.hotwords:
            # 把辨識結果往指定詞彙偏置，對人名與專有名詞特別有效
            request.setContextualStrings_(self.hotwords)

        request.appendAudioPCMBuffer_(_to_pcm_buffer(audio))
        request.endAudio()

        outcome: dict[str, object] = {}
        done = threading.Event()

        def handler(result, error) -> None:
            if error is not None:
                outcome["error"] = str(error.localizedDescription())
                done.set()
                return
            if result is not None:
                outcome["text"] = str(result.bestTranscription().formattedString())
                if result.isFinal():
                    done.set()

        task = self._recognizer.recognitionTaskWithRequest_resultHandler_(
            request, handler
        )
        # callback 走上面指定的背景佇列，所以這裡單純等就好
        if not done.wait(RECOGNITION_TIMEOUT):
            task.cancel()
            raise EngineError("語音辨識逾時")

        if "error" in outcome:
            message = str(outcome["error"])
            # 整段都是雜訊時系統會回報「找不到語音」，這不是錯誤，當成空結果
            if "No speech detected" in message or "1110" in message:
                return ""
            if "Dictation" in message or "Siri" in message:
                raise EngineError(
                    "macOS 的「聽寫」功能未開啟，Apple 引擎無法運作。\n"
                    "   請到 系統設定 → 鍵盤 → 聽寫，把它打開，"
                    f"並確認語言清單中含有 {self.locale}。\n"
                    f"   （系統訊息：{message}）"
                )
            raise EngineError(f"語音辨識失敗：{message}")

        return str(outcome.get("text", "")).strip()
