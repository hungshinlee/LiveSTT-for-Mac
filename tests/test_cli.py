"""CLI 參數解析與引擎選擇邏輯測試。"""
import pytest

from livestt.cli import build_parser, parse_hotwords, wants_traditional
from livestt.engines import ENGINES, EngineError, create_engine
from livestt.engines.qwen_mlx import to_language_name


class TestHotwords:
    def test_comma_separated(self):
        assert parse_hotwords("客語,聲學模型,轉譯") == ["客語", "聲學模型", "轉譯"]

    def test_accepts_fullwidth_comma_and_trims(self):
        assert parse_hotwords(" 客語，  聲學模型 ") == ["客語", "聲學模型"]

    def test_empty(self):
        assert parse_hotwords(None) == []
        assert parse_hotwords("") == []

    def test_reads_from_file(self, tmp_path):
        path = tmp_path / "words.txt"
        path.write_text("客語\n聲學模型\n\n轉譯\n", encoding="utf-8")

        assert parse_hotwords(str(path)) == ["客語", "聲學模型", "轉譯"]


class TestTraditionalAuto:
    def test_hf_whisper_is_converted(self):
        assert wants_traditional("whisper", "mlx-community/whisper-large-v3-mlx", None, "transcribe")

    def test_qwen_is_converted(self):
        assert wants_traditional("qwen", None, None, "transcribe")

    def test_translate_is_never_converted(self):
        """翻譯輸出是英文，轉簡繁沒有意義。"""
        assert not wants_traditional("whisper", None, None, "translate")

    def test_apple_zh_tw_is_not_converted(self):
        """zh-TW 本來就是繁體。"""
        assert not wants_traditional("apple", None, "zh-TW", "transcribe")

    def test_apple_zh_cn_is_converted(self):
        assert wants_traditional("apple", None, "zh-CN", "transcribe")


class TestEngineRegistry:
    def test_translate_rejected_by_asr_only_engines(self):
        for name in ("apple", "qwen"):
            with pytest.raises(EngineError, match="不支援翻譯"):
                create_engine(name, task="translate")

    def test_unknown_engine_lists_valid_ones(self):
        with pytest.raises(EngineError, match="whisper"):
            create_engine("nope")

    def test_only_whisper_translates(self):
        translating = {n for n, s in ENGINES.items() if s.supports_translate}
        assert translating == {"whisper"}

    def test_apple_ignores_model_argument(self):
        """Apple 沒有模型可選，給了 --model 也不該爆炸。"""
        engine = create_engine("apple", model="whatever", language="en-US")
        assert engine.name == "apple"


class TestQwenLanguage:
    @pytest.mark.parametrize(
        "code,expected",
        [("zh", "Chinese"), ("zh-TW", "Chinese"), ("yue", "Cantonese"),
         ("en", "English"), ("nan", "Chinese"), ("ja", "Japanese")],
    )
    def test_maps_iso_codes(self, code, expected):
        assert to_language_name(code) == expected

    def test_none_means_auto_detect(self):
        assert to_language_name(None) is None

    def test_unsupported_language_is_rejected(self):
        with pytest.raises(EngineError, match="不支援語言"):
            to_language_name("xx")


class TestParser:
    def test_defaults(self):
        args = build_parser().parse_args([])
        assert (args.engine, args.ui, args.task) == ("whisper", "terminal", "transcribe")

    def test_short_flags(self):
        args = build_parser().parse_args(["-e", "qwen", "-u", "overlay", "-s", "1"])
        assert (args.engine, args.ui, args.screen) == ("qwen", "overlay", 1)

    def test_invalid_engine_rejected(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--engine", "nope"])


class TestTraditionalLanguageGuard:
    """明確指定非中文語言時不該宣告要做簡繁轉換。"""

    def test_explicit_english_is_not_converted(self):
        assert not wants_traditional("whisper", None, "en", "transcribe")

    def test_explicit_japanese_is_not_converted(self):
        assert not wants_traditional("qwen", None, "ja", "transcribe")

    def test_chinese_variants_still_converted(self):
        for code in ("zh", "zh-CN", "yue", "nan"):
            assert wants_traditional("qwen", None, code, "transcribe"), code

    def test_auto_detect_still_converted(self):
        """沒指定語言時可能偵測到中文，仍要轉。"""
        assert wants_traditional("qwen", None, None, "transcribe")


class TestQueryCommands:
    """--list 等查詢指令要能跑完不拋例外（曾因區域變數遮蔽模組而壞掉）。"""

    def test_list_models_runs(self, capsys):
        from livestt.cli import show_models

        show_models()
        out = capsys.readouterr().out
        assert "引擎：" in out
        assert "翻譯模型" in out

    def test_list_via_main(self):
        from livestt.cli import main

        assert main(["--list"]) == 0

    def test_list_devices_via_main(self):
        from livestt.cli import main

        assert main(["--list-devices"]) == 0
