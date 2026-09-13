"""字幕視窗的樣式計算。不建立視窗，只驗證純粹的數值與解析邏輯。"""
import pytest

from livestt.ui.overlay import COLORS, OverlayStyle, _color


class TestBilingualLayout:
    def test_single_language_is_one_line_per_entry(self):
        assert OverlayStyle().lines_per_entry == 1

    def test_bilingual_is_two_lines_per_entry(self):
        assert OverlayStyle(bilingual=True).lines_per_entry == 2

    def test_original_font_is_smaller_than_translation(self):
        """原文要比譯文小，讓譯文成為視覺重點。"""
        style = OverlayStyle(bilingual=True, font_size=40)
        assert style.original_font_size < style.font_size

    def test_original_font_has_a_floor(self):
        """字級再小也要看得見。"""
        assert OverlayStyle(font_size=10).original_font_size >= 12.0


class TestColors:
    @pytest.mark.parametrize("name", sorted(COLORS))
    def test_named_colors_resolve(self, name):
        red, green, blue = _color(name)
        assert all(0.0 <= c <= 1.0 for c in (red, green, blue))

    def test_hex_colors(self):
        assert _color("#FF8800") == pytest.approx((1.0, 0.5333, 0.0), abs=1e-3)

    def test_black_and_white_hex(self):
        assert _color("#000000") == (0.0, 0.0, 0.0)
        assert _color("#FFFFFF") == (1.0, 1.0, 1.0)

    def test_unknown_color_lists_valid_options(self):
        with pytest.raises(ValueError, match="yellow"):
            _color("magenta")
