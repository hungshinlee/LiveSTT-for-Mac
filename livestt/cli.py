"""LiveSTT 命令列入口。"""
from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from pathlib import Path

from . import postprocess, translate
from .audio import DEFAULT_SOURCE, SOURCES, AudioError, create_source
from .translate import parse_glossary
from .engines import DEFAULT_ENGINE, ENGINES, EngineError, create_engine
from .pipeline import Pipeline
from .terms import parse_terms
from .transcript import TranscriptWriter
from .vad import VADConfig

EPILOG = """\
範例：
  livestt                                  預設：Whisper + 終端機輸出
  livestt --engine apple                   用 macOS 內建辨識（零下載、最快）
  livestt --engine qwen                    用 Qwen3-ASR（國語／臺灣台語最準）
  livestt --task translate                 翻譯成英文（僅 Whisper 支援）
  livestt --ui overlay                     浮動字幕視窗，適合全螢幕簡報
  livestt --ui overlay --screen 1          字幕顯示在第二個螢幕
  livestt -e qwen -l nan                   臺灣台語
  livestt --hotwords 客語,聲學模型,轉譯      提高特定詞彙的辨識率
  livestt -e apple --translate-to ja        中文語音 → 日文字幕
  livestt -e apple --translate-to zh-TW -l en   英文語音 → 繁中字幕
  livestt -e apple --translate-to en --bilingual  雙語字幕，原文與譯文並陳
  livestt -u overlay --log talk.srt         浮動字幕，同時存成 SRT 字幕檔
  livestt --source system -u overlay        聽電腦在播的影片，配上浮動字幕

翻譯的兩條路：
  --task translate    Whisper 內建，單次推論較省資源，但只能翻成英文
  --translate-to X    外接 LLM，三個引擎都能用，可翻成任何語言

音訊來源：
  mic       麥克風（預設）
  system    電腦正在播放的聲音 —— 影片、線上會議、瀏覽器分頁。
            聲音照常從喇叭出來，不需要安裝虛擬音效卡，
            但需要「螢幕與系統音訊錄製」權限，設定後要完全重開終端機

支援的語言：
  英語        三個引擎都可以，apple 延遲最低
  國語        三個引擎都可以，qwen 最準
  臺灣台語     只有 qwen（-l nan）
  臺灣客語     只有 whisper 搭配微調模型（見 README 的「轉換自訂模型」）

引擎比較：
  whisper   可翻譯成英文；臺灣客語的唯一選擇。品質高，延遲較高
  apple     零下載、延遲最低。需在系統設定開啟「聽寫」
  qwen      國語與臺灣台語最準，原生熱詞支援

查詢：
  livestt --list            列出可用模型
  livestt --list-locales    列出 Apple 引擎支援的語言
  livestt --list-devices    列出錄音裝置與音訊來源
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
        help="語言代碼：zh／zh-TW 國語、en 英語、nan 臺灣台語、hak 臺灣客語。不給則自動偵測",
    )
    core.add_argument(
        "--terms",
        metavar="檔案",
        help="課程／領域詞彙表，一個檔案同時作為辨識熱詞與翻譯術語表。"
             "沒有 = 的行只做辨識偏置，有 = 的行兩邊都生效",
    )
    core.add_argument(
        "--context",
        metavar="描述",
        help="一句話描述這場的主題，同時提供給辨識與翻譯，減少歧義。"
             "例如「這是一堂深度學習課程，會談到 Transformer 與注意力機制」",
    )
    core.add_argument(
        "--hotwords",
        help="逗號分隔的熱詞，提高特定詞彙辨識率；也可給一個每行一詞的檔案路徑",
    )
    core.add_argument(
        "--translate-to",
        metavar="語言",
        help="把辨識結果翻譯成指定語言（如 en、ja、zh-TW，或直接寫語言名稱）。"
             "三個引擎都適用，且不限於英文",
    )
    core.add_argument(
        "--translate-model",
        help=f"翻譯用的 LLM（預設 {translate.DEFAULT_MODEL}）",
    )
    core.add_argument(
        "--translate-window",
        type=int,
        default=translate.DEFAULT_WINDOW,
        metavar="N",
        help=f"翻譯時帶上前 N 句作為脈絡，0 為每句獨立翻譯"
             f"（預設 {translate.DEFAULT_WINDOW}）",
    )
    core.add_argument(
        "--bilingual",
        action="store_true",
        help="雙語顯示：原文與譯文一起顯示。需搭配 --translate-to",
    )
    core.add_argument(
        "--glossary",
        help="術語表，格式 原文=譯文 以逗號分隔；也可給每行一組的檔案路徑",
    )
    core.add_argument(
        "--traditional",
        choices=["auto", "on", "off"],
        default="auto",
        help="輸出轉成臺灣繁體。auto 會依引擎與模型自動判斷（預設 auto）",
    )
    core.add_argument(
        "--opencc",
        choices=list(postprocess.CONFIGS),
        default=postprocess.DEFAULT_CONFIG,
        help=f"簡繁轉換配置（預設 {postprocess.DEFAULT_CONFIG}）。"
             "s2twp 會額外轉換大陸用語，但可能誤轉「保存」等常用詞",
    )
    core.add_argument(
        "--log",
        metavar="檔案",
        help="把逐字稿寫入檔案。副檔名為 .srt 時輸出 SRT 字幕，其餘輸出帶時間的純文字。"
             "浮動字幕視窗模式下特別有用，否則講完就沒有紀錄",
    )
    core.add_argument(
        "--source",
        choices=list(SOURCES),
        default=DEFAULT_SOURCE,
        help="音訊來源：mic 麥克風，system 電腦正在播放的聲音"
             f"（預設 {DEFAULT_SOURCE}）。system 需要「螢幕與系統音訊錄製」權限",
    )
    core.add_argument(
        "--device", type=int,
        help="錄音裝置編號，見 --list-devices（只對 --source mic 有意義）",
    )

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
    info.add_argument("--list-devices", action="store_true",
                      help="列出錄音裝置與可用的音訊來源")

    return parser


# ---- 查詢指令 -------------------------------------------------------------


def show_models() -> None:
    from .engines import whisper_mlx, qwen_mlx

    print("引擎：")
    for spec in ENGINES.values():
        builtin = "內建翻譯" if spec.supports_translate else "僅辨識  "
        print(f"  {spec.name:<8} {builtin}  {spec.summary}")

    print("\nWhisper 本地模型（models/，由 tools/convert.py 產生）：")
    local = whisper_mlx.local_models()
    print("\n".join(f"  • {name}" for name in local) if local else "  （無）")

    print("\nWhisper HuggingFace 模型（首次使用自動下載）：")
    for repo, size, can_translate in whisper_mlx.KNOWN_MODELS:
        print(f"  • {repo:<40} {size:>8}  {'翻譯 ✓' if can_translate else '翻譯 ✗'}")

    print("\nQwen3-ASR 模型（首次使用自動下載）：")
    for repo, size in qwen_mlx.KNOWN_MODELS:
        print(f"  • {repo:<40} {size:>8}")

    print("\n翻譯模型（--translate-to 時使用，首次自動下載）：")
    for repo, size, note in translate.KNOWN_MODELS:
        print(f"  • {repo:<44} {size:>8}  {note}")

    print("\nApple 引擎使用 macOS 內建模型，無須下載，也沒有模型可選。")
    print("「僅辨識」的引擎搭配 --translate-to 一樣可以翻譯，且不限於英文。")


def show_locales() -> None:
    from .engines.apple_speech import supported_locales

    locales = supported_locales()
    print(f"Apple 引擎支援 {len(locales)} 種語言：\n")
    for index in range(0, len(locales), 6):
        print("  " + "  ".join(f"{loc:<10}" for loc in locales[index : index + 6]))
    print("\n用法：livestt --engine apple --language zh-TW")


def show_devices() -> None:
    from .audio import input_devices

    print("音訊來源（--source）：")
    for name, summary in SOURCES.items():
        print(f"  {name:<8} {summary}")

    print("\n錄音裝置（--device，只對 --source mic 有意義）：")
    for index, name, channels in input_devices():
        print(f"  [{index}] {name}（{channels} 聲道）")

    print("\n用法：livestt --device 1")
    print("      livestt --source system    # 轉錄電腦正在播放的聲音")


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
CHINESE_CODES = {"zh", "cmn", "nan", "hak"}


def wants_traditional(
    engine: str,
    model: str | None,
    language: str | None,
    task: str,
    translate_to: str | None = None,
) -> bool:
    """auto 模式下判斷是否要把最終輸出轉成臺灣繁體。

    判斷依據是「畫面上實際會顯示什麼語言」，所以有翻譯時看的是目標語言，
    而不是辨識出來的語言。
    """
    if translate_to:
        # 目標若是繁體中文，仍過一次 OpenCC 當保險（LLM 偶爾會吐簡體字）
        return translate.targets_traditional_chinese(translate_to)

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
        # zh-TW 本來就是繁體，只有簡體中文需要轉
        return (language or "").lower().replace("_", "-").startswith("zh-cn")

    return False


def print_banner(args, engine, convert_tw: bool, translator=None, terms=None,
                 source=None) -> None:
    print("=" * 56)
    print("LiveSTT — 離線即時語音轉文字（Apple Silicon GPU）")
    print("=" * 56)
    print(f"引擎：{engine.name} — {engine.describe()}")
    if source is not None:
        print(f"來源：{source.describe()}")
    print(f"任務：{'翻譯成英文' if args.task == 'translate' else '轉錄'}")
    print(f"語言：{args.language or '自動偵測'}")
    if translator is not None:
        print(f"翻譯：{translator.describe()}")
        if args.bilingual:
            print("顯示：雙語（原文 + 譯文）")
    if convert_tw:
        print(f"簡繁轉換：✓ 臺灣正體（OpenCC {args.opencc}）")
    print("-" * 56)
    print(
        f"VAD：門檻 {args.speech_threshold}｜靜音 {args.silence_duration}s｜"
        f"最短 {args.min_speech_duration}s｜緩衝 {args.speech_pad_duration}s"
    )
    if terms:
        print(f"詞彙：熱詞 {len(terms.hotwords)} 個｜術語 {len(terms.glossary)} 組")
    if args.context:
        print(f"主題：{args.context}")
    if args.log:
        kind = "SRT 字幕" if str(args.log).lower().endswith(".srt") else "純文字"
        print(f"逐字稿：{args.log}（{kind}）")
    if args.ui == "overlay":
        print(f"字幕：第 {args.screen} 個螢幕｜{args.lines} 行｜{args.font_size}px｜{args.color}")
        print("      可用滑鼠拖動視窗位置")
    print("=" * 56)
    if args.source == "system":
        print("開始播放影片或會議，按 Ctrl+C 結束\n")
    else:
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

        if args.bilingual and not args.translate_to:
            raise ValueError(
                "--bilingual 需要搭配 --translate-to。\n"
                "   Whisper 內建的 --task translate 只會輸出英文譯文，"
                "取不到原文，因此無法雙語顯示。"
            )

        if args.translate_to and args.task == "translate":
            raise ValueError(
                "--task translate 與 --translate-to 不能同時使用。\n"
                "   --task translate 是 Whisper 內建的翻譯（只能翻成英文），\n"
                "   --translate-to 是外接 LLM 翻譯（可翻成任何語言），兩者擇一。"
            )

        # --terms 提供共用詞彙，--hotwords／--glossary 可再補充
        terms = parse_terms(args.terms).merge(
            parse_terms(
                "\n".join(
                    [*parse_hotwords(args.hotwords),
                     *(f"{k} = {v}" for k, v in parse_glossary(args.glossary).items())]
                )
            )
        )

        # 先建立音訊來源並做權限檢查：權限問題留到模型載完才爆的話，
        # 使用者已經白等了十幾秒
        source = create_source(args.source, args.device)
        source.preflight()

        engine = create_engine(
            args.engine,
            model=args.model,
            language=args.language,
            task=args.task,
            hotwords=terms.hotwords,
            context=args.context,
        )

        transcript = None
        if args.log:
            header = f"引擎：{args.engine}"
            if args.translate_to:
                header += f"｜翻譯：{args.translate_to}"
            transcript = TranscriptWriter(Path(args.log), header=header)

        translator = None
        if args.translate_to:
            translator = translate.QwenLMTranslator(
                target=args.translate_to,
                model=args.translate_model,
                glossary=terms.glossary,
                context=args.context,
                window=args.translate_window,
            )

        if args.traditional == "auto":
            convert_tw = wants_traditional(
                args.engine, args.model, args.language, args.task, args.translate_to
            )
            # 原文是辨識結果，判斷時不看翻譯目標
            convert_original = wants_traditional(
                args.engine, args.model, args.language, args.task
            )
        else:
            convert_tw = convert_original = args.traditional == "on"

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
                    bilingual=args.bilingual,
                )
            )
        else:
            from .ui.terminal import TerminalSink

            sink = TerminalSink()

        print_banner(args, engine, convert_tw, translator, terms, source)

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
            source=source,
            translator=translator,
            bilingual=args.bilingual,
            convert_original=convert_original,
            opencc_config=args.opencc,
            transcript=transcript,
        )

    except BrokenPipeError:
        # 輸出被導向 head 之類的指令並提早關閉，不是錯誤
        return 0
    except (AudioError, EngineError, ValueError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1

    if transcript is not None:
        try:
            transcript.open()
        except OSError as exc:
            print(f"❌ 無法寫入逐字稿 {args.log}：{exc}", file=sys.stderr)
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
        if translator is not None:
            translator.close()
        if transcript is not None:
            transcript.close()
            print(f"逐字稿已儲存：{transcript.path}")
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
