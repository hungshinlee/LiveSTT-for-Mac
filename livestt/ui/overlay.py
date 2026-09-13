"""浮動字幕視窗（macOS 原生，PyObjC）。

用 NSScreenSaverWindowLevel 讓視窗浮在全螢幕簡報之上，適合 Keynote、
Google Slides 等場合。視窗可用滑鼠拖動。
"""
from __future__ import annotations

from dataclasses import dataclass

import AppKit
from AppKit import (
    NSApplication,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSMutableParagraphStyle,
    NSParagraphStyleAttributeName,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSColor,
    NSFont,
    NSMakeRect,
    NSScreen,
    NSScreenSaverWindowLevel,
    NSTextAlignmentCenter,
    NSTextField,
    NSWindow,
    NSWindowStyleMaskBorderless,
)
from Foundation import NSMutableAttributedString
from PyObjCTools import AppHelper

from .base import Sink

#: 文字顏色名稱 → RGB
COLORS = {
    "white": (1.0, 1.0, 1.0),
    "yellow": (1.0, 0.95, 0.3),
    "green": (0.4, 1.0, 0.5),
    "cyan": (0.4, 0.95, 1.0),
    "orange": (1.0, 0.7, 0.3),
    "pink": (1.0, 0.6, 0.8),
}

WAITING_TEXT = "🎤 等待說話…"


@dataclass
class OverlayStyle:
    """字幕視窗外觀。全部可由 CLI 覆寫。"""

    screen: int = 0
    width_ratio: float = 0.8
    bottom_margin: int = 50
    opacity: float = 0.85
    font_size: int = 36
    font_name: str | None = None
    max_lines: int = 3
    line_height: float = 1.3
    text_color: str = "white"
    background: tuple[float, float, float] = (0.1, 0.1, 0.1)
    #: 雙語模式：原文與譯文一起顯示，原文較小且較淡
    bilingual: bool = False

    @property
    def lines_per_entry(self) -> int:
        return 2 if self.bilingual else 1

    @property
    def original_font_size(self) -> float:
        """原文字級。比譯文小，讓譯文成為視覺重點。"""
        return max(12.0, self.font_size * 0.72)


def _color(name: str) -> tuple[float, float, float]:
    if name.startswith("#") and len(name) == 7:
        return tuple(int(name[i : i + 2], 16) / 255 for i in (1, 3, 5))
    if name not in COLORS:
        raise ValueError(
            f"未知的顏色 '{name}'，可用：{', '.join(COLORS)}，或 #RRGGBB"
        )
    return COLORS[name]


class OverlaySink(Sink):
    """把辨識結果顯示在浮動字幕視窗上。

    視窗必須在主執行緒建立與更新，因此所有 UI 操作都透過
    ``AppHelper.callAfter`` 丟回主執行緒。
    """

    def __init__(self, style: OverlayStyle | None = None) -> None:
        self.style = style or OverlayStyle()
        self._lines: list[tuple[str, str | None]] = []
        self._window = None
        self._label = None
        self._on_quit = None

    # ---- 建立視窗 --------------------------------------------------------

    def build(self) -> None:
        """建立視窗。必須在主執行緒呼叫。"""
        style = self.style

        app = NSApplication.sharedApplication()
        # Accessory：不在 Dock 顯示圖示，也不搶走簡報的焦點
        app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

        screens = NSScreen.screens()
        if style.screen < len(screens):
            screen = screens[style.screen]
        else:
            print(
                f"⚠️ 找不到第 {style.screen} 個螢幕（目前共 {len(screens)} 個），"
                "改用主螢幕"
            )
            screen = NSScreen.mainScreen()

        frame = screen.frame()
        width = frame.size.width * style.width_ratio
        entry_height = style.font_size * style.line_height
        if style.bilingual:
            entry_height += style.original_font_size * style.line_height
        height = int(entry_height * style.max_lines + 30)
        x = frame.origin.x + (frame.size.width - width) / 2
        y = frame.origin.y + style.bottom_margin

        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, width, height),
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        window.setLevel_(NSScreenSaverWindowLevel)
        window.setOpaque_(False)
        red, green, blue = style.background
        window.setBackgroundColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(
                red, green, blue, style.opacity
            )
        )
        window.setHasShadow_(True)
        window.setMovableByWindowBackground_(True)
        # 跟著使用者切換 Space，並且允許浮在全螢幕 App 上方
        window.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
        )

        label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(20, 10, width - 40, height - 20)
        )
        font = None
        if style.font_name:
            font = NSFont.fontWithName_size_(style.font_name, style.font_size)
            if font is None:
                print(f"⚠️ 找不到字體 '{style.font_name}'，改用系統字體")
        self._font = font or NSFont.boldSystemFontOfSize_(style.font_size)
        label.setFont_(self._font)

        red, green, blue = _color(style.text_color)
        self._text_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(
            red, green, blue, 1.0
        )
        # 原文用同色但更淡，避免喧賓奪主
        self._original_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(
            red, green, blue, 0.62
        )
        if style.font_name:
            self._original_font = NSFont.fontWithName_size_(
                style.font_name, style.original_font_size
            ) or NSFont.systemFontOfSize_(style.original_font_size)
        else:
            self._original_font = NSFont.systemFontOfSize_(style.original_font_size)
        label.setTextColor_(self._text_color)
        label.setBackgroundColor_(NSColor.clearColor())
        label.setBezeled_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setAlignment_(NSTextAlignmentCenter)
        label.setUsesSingleLineMode_(False)
        label.setMaximumNumberOfLines_(style.max_lines * style.lines_per_entry)
        label.setStringValue_(WAITING_TEXT)

        window.contentView().addSubview_(label)
        window.makeKeyAndOrderFront_(None)

        self._window = window
        self._label = label

    # ---- Sink ------------------------------------------------------------

    def _paragraph_style(self):
        paragraph = NSMutableParagraphStyle.alloc().init()
        paragraph.setAlignment_(NSTextAlignmentCenter)
        return paragraph

    def _build_attributed(self):
        """把歷史組成一段富文字，原文與譯文各有自己的字級與濃度。"""
        paragraph = self._paragraph_style()
        result = NSMutableAttributedString.alloc().init()

        for index, (text, original) in enumerate(self._lines):
            if index:
                result.appendAttributedString_(
                    NSMutableAttributedString.alloc().initWithString_("\n")
                )
            if original:
                result.appendAttributedString_(
                    NSMutableAttributedString.alloc().initWithString_attributes_(
                        original + "\n",
                        {
                            NSFontAttributeName: self._original_font,
                            NSForegroundColorAttributeName: self._original_color,
                            NSParagraphStyleAttributeName: paragraph,
                        },
                    )
                )
            result.appendAttributedString_(
                NSMutableAttributedString.alloc().initWithString_attributes_(
                    text,
                    {
                        NSFontAttributeName: self._font,
                        NSForegroundColorAttributeName: self._text_color,
                        NSParagraphStyleAttributeName: paragraph,
                    },
                )
            )
        return result

    def _render(self, text: str) -> None:
        """顯示單行狀態訊息。"""
        if self._label is None:
            return
        AppHelper.callAfter(lambda: self._label.setStringValue_(text))

    def _render_history(self) -> None:
        if self._label is None:
            return
        attributed = self._build_attributed()
        AppHelper.callAfter(
            lambda: self._label.setAttributedStringValue_(attributed)
        )

    def on_text(self, text: str, original: str | None = None) -> None:
        self._lines.append((text, original))
        # 只留最近幾句，最新的在最下面
        del self._lines[: -self.style.max_lines]
        self._render_history()

    def on_status(self, message: str) -> None:
        # 已經有字幕時不要被狀態訊息蓋掉，狀態只在還沒有內容時顯示
        if not self._lines:
            self._render(message)

    def on_error(self, message: str) -> None:
        print(f"❌ {message}")
        if not self._lines:
            self._render(f"❌ {message}")

    def close(self) -> None:
        def do_close() -> None:
            if self._window is not None:
                self._window.close()
                self._window = None
            AppHelper.stopEventLoop()

        AppHelper.callAfter(do_close)

    # ---- 事件迴圈 --------------------------------------------------------

    def run(self, should_stop, on_stop=None) -> None:
        """在主執行緒跑事件迴圈，直到 should_stop() 為真。

        注意：``AppHelper.runEventLoop()`` 不會返回。PyObjC 的 ``stopEventLoop()``
        在這個情境下走的是 ``NSApp.terminate_()``，直接在 Objective-C 層結束行程，
        連 Python 的 atexit 都不會執行。因此**收尾工作必須在停止迴圈之前做完**，
        不能寫在 ``run()`` 之後。``on_stop`` 就是給這件事用的。
        """
        import threading

        def poll() -> None:
            # 這個 callback 每 0.2 秒執行一次 Python 程式碼，
            # 順帶讓主執行緒有機會處理 SIGINT（Ctrl+C）
            if should_stop():
                if on_stop is not None:
                    on_stop()
                AppHelper.stopEventLoop()
            else:
                timer = threading.Timer(0.2, lambda: AppHelper.callAfter(poll))
                timer.daemon = True
                timer.start()

        AppHelper.callAfter(poll)
        # installInterrupt=False：改由 cli 自己的 SIGINT handler 觸發停止流程，
        # 這樣 Ctrl+C 也會經過 on_stop，而不是直接把行程砍掉
        AppHelper.runEventLoop(installInterrupt=False)
        if on_stop is not None:
            on_stop()  # 萬一哪天 PyObjC 改成會返回
