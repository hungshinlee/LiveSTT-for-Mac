"""LiveSTT 命令列入口。"""
from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from pathlib import Path

from .engines import DEFAULT_ENGINE, ENGINES, EngineError, create_engine
from .pipeline import Pipeline
from .vad import VADConfig

EPILOG = """\
範例：
  livestt                                  預設：Whisper + 終端機輸出
  livestt --engine apple                   用 macOS 內建辨識（零下載、最快）
  livestt --engine qwen                    用 Qwen3-ASR（中文／台語最準）
  livestt --task translate                 翻譯成英文（僅 Whisper 支援）
  livestt --ui overlay                     浮動字幕視窗，適合全螢幕簡報
  livestt --ui overlay --screen 1          字幕顯示在第二個螢幕
  livestt --hotwords 客語,聲學模型,轉譯      提高特定詞彙的辨識率

引擎比較：
  whisper   可翻譯成英文、可用微調模型（客語）。品質高，延遲較高
  apple     零下載、延遲最低、支援 zh-TW。需在系統設定開啟「聽寫」
  qwen      中文與方言（台語、粵語）最準，原生熱詞支援

查詢：
  livestt --list            列出可用模型
  livestt --list-locales    列出 Apple 引擎支援的語言
  livestt --list-devices    列出錄音裝置
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="livestt",
        description="Apple Silicon Mac 上的離線即時語音轉文字",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EPILOG,
    )

    core = parser.add_argument_group("核心")
    core.add_argument(
        "--engine", "-e",
        choices=list(ENGINES),
        default=DEFAULT_ENGINE,
        help=f"辨識引擎（預設 {DEFAULT_ENGINE}）",
    )
    core.add_argument(
        "--ui", "-u",
        choices=["terminal", "overlay"],
        default="terminal",
        help="輸出方式：terminal 終端機，overlay 浮動字幕視窗（預設 terminal）",
    )
    core.add_argument(
        "--model", "-m",
        help="模型名稱（HF repo 或本地模型）。Apple 引擎沒有模型可選",
    )
    core.add_argument(
        "--task", "-t",
        choices=["transcribe", "translate"],
        default="transcribe",
        help="transcribe 轉錄，translate 翻譯成英文（僅 Whisper 支援）",
    )
    core.add_argument(
        "--language", "-l",
        help="語言代碼，如 zh、zh-TW、en、ja、yue。不給則自動偵測",
    )
    core.add_argument(
        "--hotwords",
        help="逗號分隔的熱詞，提高特定詞彙辨識率；也可給一個每行一詞的檔案路徑",
    )
    core.add_argument(
        "--traditional",
        choices=["auto", "on", "off"],
        default="auto",
        help="輸出轉成臺灣繁體。auto 會依引擎與模型自動判斷（預設 auto）",
    )
    core.add_argument("--device", type=int, help="錄音裝置編號，見 --list-devices")

    vad = parser.add_argument_group("語音偵測 (VAD)")
    vad.add_argument(
        "--speech-threshold", type=float, default=0.5,
        help="語音判定門檻 0.0–1.0，越高越嚴格（預設 0.5，環境吵雜可調 0.6）",
    )
    vad.add_argument(
        "--silence-duration", type=float, default=0.6,
        help="靜音多久算講完一句，秒（預設 0.6，說話快可調 0.4）",
    )
    vad.add_argument(
        "--min-speech-duration", type=float, default=0.2,
        help="最短語音長度，秒，更短的視為雜訊（預設 0.2）",
    )
    vad.add_argument(
        "--speech-pad-duration", type=float, default=0.1,
        help="句首保留的緩衝，秒（預設 0.1，開頭被截斷可調 0.2）",
    )

    overlay = parser.add_argument_group("字幕視窗（--ui overlay）")
    overlay.add_argument("--screen", "-s", type=int, default=0,
                         help="顯示在第幾個螢幕，0 為主螢幕（預設 0）")
    overlay.add_argument("--font-size", type=int, default=36, help="字體大小（預設 36）")
    overlay.add_argument("--font-name", help="字體名稱，如 HanaMinA（預設系統字體）")
    overlay.add_argument("--lines", type=int, default=3, help="顯示行數（預設 3）")
    overlay.add_argument("--color", default="white",
                         help="文字顏色：white/yellow/green/cyan/orange/pink 或 #RRGGBB")
    overlay.add_argument("--opacity", type=float, default=0.85,
                         help="背景透明度 0.0–1.0（預設 0.85）")
    overlay.add_argument("--width-ratio", type=float, default=0.8,
                         help="視窗寬度佔螢幕比例（預設 0.8）")
    overlay.add_argument("--bottom-margin", type=int, default=50,
                         help="距離螢幕底部的距離，像素（預設 50）")

    info = parser.add_argument_group("查詢")
    info.add_argument("--list", action="store_true", help="列出可用模型與引擎")
    info.add_argument("--list-locales", action="store_true",
                      help="列出 Apple 引擎支援的語言")
    info.add_argument("--list-devices", action="store_true", help="列出錄音裝置")

    return parser


# ---- 查詢指令 -------------------------------------------------------------


def show_models() -> None:
    from .engines import whisper_mlx, qwen_mlx

    print("引擎：")
    for spec in ENGINES.values():
        translate = "可翻譯" if spec.supports_translate else "僅辨識"
        print(f"  {spec.name:<8} {translate}  {spec.summary}")

    print("\nWhisper 本地模型（models/，由 tools/convert.py 產生）：")
    local = whisper_mlx.local_models()
    print("\n".join(f"  • {name}" for name in local) if local else "  （無）")

    print("\nWhisper HuggingFace 模型（首次使用自動下載）：")
    for repo, size, translate in whisper_mlx.KNOWN_MODELS:
        print(f"  • {repo:<40} {size:>8}  {'翻譯 ✓' if translate else '翻譯 ✗'}")

    print("\nQwen3-ASR 模型（首次使用自動下載）：")
    for repo, size in qwen_mlx.KNOWN_MODELS:
        print(f"  • {repo:<40} {size:>8}")

    print("\nApple 引擎使用 macOS 內建模型，無須下載，也沒有模型可選。")


def show_locales() -> None:
    from .engines.apple_speech import supported_locales

    locales = supported_locales()
    print(f"Apple 引擎支援 {len(locales)} 種語言：\n")
    for index in range(0, len(locales), 6):
        print("  " + "  ".join(f"{loc:<10}" for loc in locales[index : index + 6]))
    print("\n用法：livestt --engine apple --language zh-TW")


def show_devices() -> None:
    from .audio import input_devices

    print("錄音裝置：")
    for index, name, channels in input_devices():
        print(f"  [{index}] {name}（{channels} 聲道）")
    print("\n用法：livestt --device 1")


# ---- 設定組裝 -------------------------------------------------------------


def parse_hotwords(value: str | None) -> list[str]:
    """解析 --hotwords：可以是逗號分隔字串，也可以是每行一詞的檔案。"""
    if not value:
        return []

    path = Path(value)
    if path.is_file():
        words = path.read_text(encoding="utf-8").splitlines()
    else:
        words = value.replace("，", ",").split(",")

    return [word.strip() for word in words if word.strip()]


#: 會產生中文輸出的語言代碼
CHINESE_CODES = {"zh", "cmn", "yue", "nan", "hak", "wuu"}


def wants_traditional(engine: str, model: str | None, language: str | None, task: str) -> bool:
    """auto 模式下判斷是否要把輸出轉成臺灣繁體。"""
    if task == "translate":
        return False  # 輸出是英文

    # 明確指定了非中文語言就不必轉；沒指定則可能自動偵測到中文，仍要轉
    if language and language.split("-")[0].lower() not in CHINESE_CODES:
        return False

    if engine == "whisper":
        from .engines.whisper_mlx import is_local, resolve_model

        # 本地微調模型（例如客語）保留原始輸出，不做任何字形轉換
        return not is_local(resolve_model(model))

    if engine == "qwen":
        return True  # Qwen3-ASR 中文輸出為簡體

    if engine == "apple":
        # zh-TW / zh-HK 本來就是繁體，只有簡體中文需要轉
        return (language or "").lower().replace("_", "-").startswith("zh-cn")

    return False


def print_banner(args, engine, convert_tw: bool) -> None:
    print("=" * 56)
    print("LiveSTT — 離線即時語音轉文字（Apple Silicon GPU）")
    print("=" * 56)
    print(f"引擎：{engine.name} — {engine.describe()}")
    print(f"任務：{'翻譯成英文' if args.task == 'translate' else '轉錄'}")
    print(f"語言：{args.language or '自動偵測'}")
    if convert_tw:
        print("簡繁轉換：✓ 臺灣正體（OpenCC s2twp）")
    print("-" * 56)
    print(
        f"VAD：門檻 {args.speech_threshold}｜靜音 {args.silence_duration}s｜"
        f"最短 {args.min_speech_duration}s｜緩衝 {args.speech_pad_duration}s"
    )
    if args.ui == "overlay":
        print(f"字幕：第 {args.screen} 個螢幕｜{args.lines} 行｜{args.font_size}px｜{args.color}")
        print("      可用滑鼠拖動視窗位置")
    print("=" * 56)
    print("開始說話，按 Ctrl+C 結束\n")


# ---- 主流程 ---------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # 輸出被導向檔案時 stdout 預設是區塊緩衝，而 overlay 模式最後是由
    # NSApp.terminate_() 在 Objective-C 層結束行程，Python 的緩衝區不會被 flush，
    # 結果是整份輸出憑空消失。改成行緩衝，並在收尾時明確 flush。
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, OSError):
        pass

    try:
        if args.list:
            show_models()
            return 0
        if args.list_locales:
            show_locales()
            return 0
        if args.list_devices:
            show_devices()
            return 0

        hotwords = parse_hotwords(args.hotwords)
        engine = create_engine(
            args.engine,
            model=args.model,
            language=args.language,
            task=args.task,
            hotwords=hotwords,
        )

        convert_tw = (
            wants_traditional(args.engine, args.model, args.language, args.task)
            if args.traditional == "auto"
            else args.traditional == "on"
        )

        if args.ui == "overlay":
            from .ui.overlay import OverlaySink, OverlayStyle

            sink = OverlaySink(
                OverlayStyle(
                    screen=args.screen,
                    width_ratio=args.width_ratio,
                    bottom_margin=args.bottom_margin,
                    opacity=args.opacity,
                    font_size=args.font_size,
                    font_name=args.font_name,
                    max_lines=args.lines,
                    text_color=args.color,
                )
            )
        else:
            from .ui.terminal import TerminalSink

            sink = TerminalSink()

        print_banner(args, engine, convert_tw)

        pipeline = Pipeline(
            engine=engine,
            sink=sink,
            vad_config=VADConfig(
                speech_threshold=args.speech_threshold,
                min_silence_duration=args.silence_duration,
                min_speech_duration=args.min_speech_duration,
                speech_pad_duration=args.speech_pad_duration,
            ),
            convert_tw=convert_tw,
            device=args.device,
        )

    except (EngineError, ValueError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1

    done = threading.Event()

    def cleanup() -> None:
        """收尾。可能被主流程與事件迴圈各呼叫一次，所以設計成冪等。"""
        if done.is_set():
            return
        done.set()
        print("\n正在關閉…")
        pipeline.stop()
        pipeline.wait(timeout=2.0)
        engine.close()
        print("已停止")
        sys.stdout.flush()

    if args.ui == "overlay":
        # overlay 的事件迴圈不會返回（見 OverlaySink.run 的說明），
        # 所以 Ctrl+C 只能先讓 pipeline 停下來，再由事件迴圈的 poll 觸發收尾
        signal.signal(signal.SIGINT, lambda *_: pipeline.stop())
        signal.signal(signal.SIGTERM, lambda *_: pipeline.stop())

        sink.build()  # 視窗必須在主執行緒建立
        pipeline.start()
        sink.run(should_stop=lambda: pipeline.stopped, on_stop=cleanup)
        sink.close()
    else:
        pipeline.start()
        try:
            while not pipeline.stopped:
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            cleanup()
            sink.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
