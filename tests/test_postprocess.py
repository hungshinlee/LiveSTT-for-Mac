"""簡繁轉換測試。

重點在於**預設不能竄改講者原話**：s2twp 的用語在地化是給書面翻譯用的，
套在逐字稿上會改變語意。
"""
import pytest

from livestt.postprocess import CONFIGS, DEFAULT_CONFIG, to_taiwan_traditional


class TestDefaultDoesNotRewriteWording:
    def test_default_is_s2tw_not_s2twp(self):
        assert DEFAULT_CONFIG == "s2tw"

    @pytest.mark.parametrize(
        "simplified,expected",
        [
            # s2twp 會把「保存」誤轉成「儲存」，這在本專案的領域裡語意完全不同
            ("客语保存工作", "客語保存工作"),
            ("我们保存了这个文件", "我們保存了這個文件"),
            ("保存文化资产", "保存文化資產"),
        ],
    )
    def test_preserves_wording(self, simplified, expected):
        assert to_taiwan_traditional(simplified) == expected

    def test_still_converts_characters(self):
        """字形轉換要照做，只是不做用語替換。"""
        assert to_taiwan_traditional("台湾的语音辨识") == "臺灣的語音辨識"

    def test_phonetic_wording_survives_round_trip(self):
        """講者說「軟體」時 ASR 輸出簡體字形，字形轉換就足以還原。"""
        assert to_taiwan_traditional("这个软体") == "這個軟體"


class TestExplicitConfigs:
    def test_s2twp_still_available_for_those_who_want_it(self):
        assert to_taiwan_traditional("这个软件", "s2twp") == "這個軟體"

    def test_s2twp_rewrites_wording_as_documented(self):
        """記錄 s2twp 的已知副作用，避免有人誤以為它是安全的預設。"""
        assert to_taiwan_traditional("客语保存工作", "s2twp") == "客語儲存工作"

    def test_s2t_does_not_apply_taiwan_variant_characters(self):
        """s2t 用通用繁體字形，s2tw 才套用臺灣的異體字偏好（裏/裡、麪/麵）。"""
        assert to_taiwan_traditional("里面", "s2t") == "裏面"
        assert to_taiwan_traditional("里面", "s2tw") == "裡面"

    def test_all_documented_configs_work(self):
        for config in CONFIGS:
            assert to_taiwan_traditional("语音", config)


class TestTaiwanNamingExceptions:
    """OpenCC 會把「台」一律轉成「臺」，但語言名稱的官方寫法是「臺灣台語」。"""

    @pytest.mark.parametrize(
        "simplified,expected",
        [
            ("台语", "台語"),
            ("台湾台语", "臺灣台語"),
            ("我在学台语", "我在學台語"),
            ("国台语双声道", "國台語雙聲道"),
        ],
    )
    def test_taiwanese_keeps_its_official_spelling(self, simplified, expected):
        assert to_taiwan_traditional(simplified) == expected

    def test_already_traditional_is_also_normalised(self):
        assert to_taiwan_traditional("臺語") == "台語"

    @pytest.mark.parametrize("simplified,expected", [("台湾", "臺灣"), ("台北", "臺北")])
    def test_other_uses_of_tai_are_untouched(self, simplified, expected):
        """例外只針對語言名稱，地名仍照 OpenCC 的正規化。"""
        assert to_taiwan_traditional(simplified) == expected

    def test_exceptions_apply_to_s2twp_too(self):
        assert to_taiwan_traditional("台语", "s2twp") == "台語"

    def test_exceptions_skip_generic_traditional(self):
        """s2t 是通用繁體，不涉及臺灣命名慣例，不套用例外。"""
        from livestt.postprocess import TAIWAN_CONFIGS

        assert "s2t" not in TAIWAN_CONFIGS


class TestEdgeCases:
    def test_empty_string(self):
        assert to_taiwan_traditional("") == ""

    def test_non_chinese_is_untouched(self):
        assert to_taiwan_traditional("Hello, MLX!") == "Hello, MLX!"

    def test_already_traditional_is_stable(self):
        assert to_taiwan_traditional("臺灣的語音辨識") == "臺灣的語音辨識"
