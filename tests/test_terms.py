"""課程詞彙表測試。"""
import pytest

from livestt.terms import Terms, parse_terms


class TestParsing:
    def test_plain_words_become_hotwords_only(self):
        terms = parse_terms("BERT\nTransformer")

        assert terms.hotwords == ["BERT", "Transformer"]
        assert terms.glossary == {}

    def test_pairs_feed_both_sides(self):
        """有譯法的詞也要做辨識偏置：聽錯了譯法再準也沒用。"""
        terms = parse_terms("梯度下降 = gradient descent")

        assert terms.hotwords == ["梯度下降"]
        assert terms.glossary == {"梯度下降": "gradient descent"}

    def test_mixed_file(self, tmp_path):
        path = tmp_path / "course.txt"
        path.write_text(
            "# AI 課程\nBERT\nTransformer\n\n各位同學 = everyone\n梯度下降 = gradient descent\n",
            encoding="utf-8",
        )
        terms = parse_terms(str(path))

        assert terms.hotwords == ["BERT", "Transformer", "各位同學", "梯度下降"]
        assert terms.glossary == {"各位同學": "everyone", "梯度下降": "gradient descent"}

    def test_comments_and_blank_lines_ignored(self):
        terms = parse_terms("# 標題\n\nBERT  # 行內註解\n\n# 另一個註解\n")

        assert terms.hotwords == ["BERT"]

    def test_inline_comment_stripped_from_pair(self):
        terms = parse_terms("梯度下降 = gradient descent  # 常用")

        assert terms.glossary == {"梯度下降": "gradient descent"}

    def test_accepts_inline_comma_list(self):
        """方便在命令列臨時補幾個詞。"""
        terms = parse_terms("BERT,Transformer,各位同學=everyone")

        assert terms.hotwords == ["BERT", "Transformer", "各位同學"]
        assert terms.glossary == {"各位同學": "everyone"}

    def test_fullwidth_comma(self):
        assert parse_terms("BERT，Transformer").hotwords == ["BERT", "Transformer"]

    def test_duplicates_collapse(self):
        assert parse_terms("BERT\nBERT\nBERT").hotwords == ["BERT"]

    def test_incomplete_pairs_are_skipped(self):
        terms = parse_terms("= 沒有左邊\n沒有右邊 =\nBERT")

        assert terms.hotwords == ["BERT"]
        assert terms.glossary == {}

    def test_target_may_contain_equals(self):
        assert parse_terms("a = b = c").glossary == {"a": "b = c"}

    def test_empty(self):
        assert not parse_terms(None)
        assert not parse_terms("")


class TestMerge:
    def test_later_wins_on_conflict(self):
        base = parse_terms("詞 = old")
        extra = parse_terms("詞 = new")

        assert base.merge(extra).glossary == {"詞": "new"}

    def test_hotwords_are_unioned_without_duplicates(self):
        merged = parse_terms("A\nB").merge(parse_terms("B\nC"))

        assert merged.hotwords == ["A", "B", "C"]

    def test_merge_does_not_mutate_inputs(self):
        base = parse_terms("A")
        base.merge(parse_terms("B"))

        assert base.hotwords == ["A"]

    def test_truthiness(self):
        assert not Terms()
        assert Terms(hotwords=["A"])
        assert Terms(glossary={"a": "b"})
