"""翻譯層測試。不載入 LLM，測的是提示組裝、輸出清理與語言判斷。"""
import pytest

from livestt.cli import build_parser, wants_traditional
from livestt.translate import (
    QwenLMTranslator,
    _clean,
    parse_glossary,
    resolve_language,
    targets_traditional_chinese,
)


class TestGlossary:
    def test_parses_pairs(self):
        assert parse_glossary("客語=Hakka,聲學模型=acoustic model") == {
            "客語": "Hakka",
            "聲學模型": "acoustic model",
        }

    def test_accepts_fullwidth_comma(self):
        assert parse_glossary("客語=Hakka，台語=Taiwanese") == {
            "客語": "Hakka",
            "台語": "Taiwanese",
        }

    def test_ignores_entries_without_separator(self):
        assert parse_glossary("客語=Hakka,壞掉的項目") == {"客語": "Hakka"}

    def test_keeps_equals_sign_inside_target(self):
        assert parse_glossary("a=b=c") == {"a": "b=c"}

    def test_empty(self):
        assert parse_glossary(None) == {}

    def test_reads_from_file(self, tmp_path):
        path = tmp_path / "glossary.txt"
        path.write_text("客語=Hakka\n\n聲學模型=acoustic model\n", encoding="utf-8")

        assert parse_glossary(str(path)) == {
            "客語": "Hakka",
            "聲學模型": "acoustic model",
        }


class TestLanguageResolution:
    @pytest.mark.parametrize(
        "code,expected",
        [("ja", "Japanese"), ("en", "English"), ("zh-TW", "Traditional Chinese (Taiwan)"),
         ("zh-CN", "Simplified Chinese")],
    )
    def test_known_codes(self, code, expected):
        assert resolve_language(code) == expected

    def test_free_form_passes_through(self):
        """讓使用者能直接描述目標語言，不受代碼表限制。"""
        assert resolve_language("Taiwanese Hokkien") == "Taiwanese Hokkien"

    @pytest.mark.parametrize(
        "value,expected",
        [("zh-TW", True), ("Traditional Chinese", True),
         ("zh-CN", False), ("ja", False), ("en", False)],
    )
    def test_traditional_target_detection(self, value, expected):
        assert targets_traditional_chinese(value) is expected


class TestOutputCleaning:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ('"Hello world"', "Hello world"),
            ("Translation: Hello world", "Hello world"),
            ("翻譯：你好", "你好"),
            ("「你好」", "你好"),
            ("```\nHello\n```", "Hello"),
            ("你好\n\n(註：這是模型多講的)", "你好"),
            ("  Hello world  ", "Hello world"),
        ],
    )
    def test_strips_llm_artifacts(self, raw, expected):
        assert _clean(raw) == expected

    def test_preserves_internal_quotes(self):
        assert _clean('He said "hi" to me') == 'He said "hi" to me'


class TestSystemPrompt:
    def test_includes_target_language(self):
        prompt = QwenLMTranslator(target="ja")._system_prompt()
        assert "Japanese" in prompt

    def test_includes_glossary_terms(self):
        prompt = QwenLMTranslator(target="en", glossary={"客語": "Hakka"})._system_prompt()
        assert "客語 = Hakka" in prompt

    def test_warns_model_about_partial_speech(self):
        """ASR 輸出可能破碎，提示要求模型不要自行補完。"""
        assert "do not invent" in QwenLMTranslator(target="en")._system_prompt()

    def test_describe_mentions_target_and_glossary(self):
        described = QwenLMTranslator(target="ja", glossary={"a": "b"}).describe()
        assert "Japanese" in described and "1" in described


class TestTraditionalWithTranslation:
    def test_target_decides_conversion_not_source(self):
        """有翻譯時，看的是畫面上會顯示的語言。"""
        assert wants_traditional("apple", None, "en", "transcribe", translate_to="zh-TW")
        assert not wants_traditional("qwen", None, "zh", "transcribe", translate_to="en")

    def test_simplified_target_is_not_converted(self):
        assert not wants_traditional("apple", None, "en", "transcribe", translate_to="zh-CN")


class TestParserConflict:
    def test_both_translation_paths_can_be_parsed(self):
        """解析階段不擋，衝突在 main() 才報錯（帶完整說明）。"""
        args = build_parser().parse_args(["--task", "translate", "--translate-to", "ja"])
        assert args.task == "translate" and args.translate_to == "ja"


class TestDefaults:
    def test_default_model_is_the_8bit_instruct(self):
        """4bit 會漏掉「年增」「改在」這類細節，預設刻意選 8bit。"""
        from livestt.translate import DEFAULT_MODEL

        assert DEFAULT_MODEL == "mlx-community/Qwen3-4B-Instruct-2507-8bit"

    def test_default_is_listed_first(self):
        from livestt.translate import DEFAULT_MODEL, KNOWN_MODELS

        assert KNOWN_MODELS[0][0] == DEFAULT_MODEL

    def test_translator_uses_the_default_when_unspecified(self):
        from livestt.translate import DEFAULT_MODEL, QwenLMTranslator

        assert QwenLMTranslator(target="en").model == DEFAULT_MODEL
