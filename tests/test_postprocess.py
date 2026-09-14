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


class TestProperNounExceptions:
    """「臺」一律照教育部標準，只有專有名詞例外。"""

    @pytest.mark.parametrize(
        "simplified,expected",
        [
            # 語言名稱：官方寫法刻意混用兩字
            ("台语", "台語"),
            ("台湾台语", "臺灣台語"),
            ("我在学台语", "我在學台語"),
            # 人名
            ("郭台铭", "郭台銘"),
            ("郭台铭创办鸿海", "郭台銘創辦鴻海"),
            # 公司登記名稱
            ("台积电", "台積電"),
            ("台达电", "台達電"),
            ("台塑", "台塑"),
            ("台电", "台電"),
            ("台泥", "台泥"),
            ("台糖", "台糖"),
            ("台盐", "台鹽"),
        ],
    )
    def test_proper_nouns_keep_tai(self, simplified, expected):
        assert to_taiwan_traditional(simplified) == expected

    @pytest.mark.parametrize(
        "simplified,expected",
        [
            # 地名照教育部標準
            ("台北", "臺北"), ("台中", "臺中"), ("台南", "臺南"),
            ("台东", "臺東"), ("台湾", "臺灣"),
            # 機構官方就用「臺」
            ("台大", "臺大"), ("台铁", "臺鐵"),
            # 一般名詞照教育部標準，不管日常怎麼寫
            ("舞台", "舞臺"), ("电视台", "電視臺"), ("电台", "電臺"),
            ("平台", "平臺"), ("月台", "月臺"), ("讲台", "講臺"),
            ("阳台", "陽臺"), ("台阶", "臺階"),
        ],
    )
    def test_everything_else_uses_tai_traditional(self, simplified, expected):
        assert to_taiwan_traditional(simplified) == expected

    @pytest.mark.parametrize(
        "simplified,expected",
        [
            # 「臺」是前一個詞的詞尾，後面剛好接上會撞名的字
            ("电视台电话", "電視臺電話"),
            ("气象台电脑", "氣象臺電腦"),
            ("电视台糖果", "電視臺糖果"),
            ("电视台塑胶", "電視臺塑膠"),
            ("天文台电视", "天文臺電視"),
            ("电视台语音", "電視臺語音"),
            ("电台电波", "電臺電波"),
            ("观测台电源", "觀測臺電源"),
        ],
    )
    def test_does_not_misfire_on_word_boundaries(self, simplified, expected):
        """單純的字串取代會把這些句子改壞，所以例外規則帶了否定回顧。"""
        assert to_taiwan_traditional(simplified) == expected

    def test_already_traditional_is_also_normalised(self):
        assert to_taiwan_traditional("臺語") == "台語"
        assert to_taiwan_traditional("郭臺銘") == "郭台銘"

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
