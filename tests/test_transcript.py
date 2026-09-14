"""逐字稿輸出測試。"""
import pytest

from livestt.transcript import Entry, TranscriptWriter, _clock, _srt_time, detect_format


class TestFormatDetection:
    @pytest.mark.parametrize(
        "name,expected",
        [("a.srt", "srt"), ("a.SRT", "srt"), ("a.txt", "text"),
         ("a.log", "text"), ("a.md", "text"), ("a", "text"), ("a.weird", "text")],
    )
    def test_by_extension(self, tmp_path, name, expected):
        assert detect_format(tmp_path / name) == expected


class TestTimeFormatting:
    @pytest.mark.parametrize(
        "seconds,expected",
        [(0, "00:00:00"), (3.9, "00:00:03"), (61, "00:01:01"), (3661, "01:01:01")],
    )
    def test_clock(self, seconds, expected):
        assert _clock(seconds) == expected

    @pytest.mark.parametrize(
        "seconds,expected",
        [(0, "00:00:00,000"), (3.12, "00:00:03,120"),
         (61.5, "00:01:01,500"), (3661.999, "01:01:01,999")],
    )
    def test_srt_time(self, seconds, expected):
        assert _srt_time(seconds) == expected

    def test_negative_times_are_clamped(self):
        """時間往回推算可能得到負數，不該寫出壞掉的時間軸。"""
        assert _srt_time(-1.0) == "00:00:00,000"
        assert _clock(-1.0) == "00:00:00"


class TestTextOutput:
    def test_writes_header_and_entries(self, tmp_path):
        path = tmp_path / "talk.txt"
        with TranscriptWriter(path, header="引擎：qwen") as log:
            log.write(Entry(1, 3.0, 7.0, "第一句"))
            log.write(Entry(2, 9.0, 12.0, "第二句"))

        content = path.read_text(encoding="utf-8")
        assert "# LiveSTT 逐字稿" in content
        assert "引擎：qwen" in content
        assert "[00:00:03] 第一句" in content
        assert "[00:00:09] 第二句" in content

    def test_bilingual_writes_both(self, tmp_path):
        path = tmp_path / "talk.txt"
        with TranscriptWriter(path) as log:
            log.write(Entry(1, 3.0, 7.0, "Hello", original="你好"))

        lines = path.read_text(encoding="utf-8").splitlines()
        assert "[00:00:03] 你好" in lines
        assert any(line.strip() == "→ Hello" for line in lines)


class TestSrtOutput:
    def test_cue_structure(self, tmp_path):
        path = tmp_path / "talk.srt"
        with TranscriptWriter(path) as log:
            log.write(Entry(1, 3.12, 7.45, "第一句"))

        assert path.read_text(encoding="utf-8") == (
            "1\n00:00:03,120 --> 00:00:07,450\n第一句\n\n"
        )

    def test_no_comment_header(self, tmp_path):
        """SRT 不允許註解，加了會讓播放器解析失敗。"""
        path = tmp_path / "talk.srt"
        with TranscriptWriter(path, header="引擎：qwen") as log:
            log.write(Entry(1, 0.0, 1.0, "x"))

        assert path.read_text(encoding="utf-8").startswith("1\n")

    def test_bilingual_shares_one_cue(self, tmp_path):
        path = tmp_path / "talk.srt"
        with TranscriptWriter(path) as log:
            log.write(Entry(1, 0.0, 2.0, "Hello", original="你好"))

        assert "你好\nHello" in path.read_text(encoding="utf-8")


class TestDurability:
    def test_each_entry_is_flushed(self, tmp_path):
        """程式中途當掉時，已辨識的部分要保得住。"""
        path = tmp_path / "talk.txt"
        log = TranscriptWriter(path)
        log.open()
        log.write(Entry(1, 0.0, 2.0, "還沒關檔就要看得到"))

        assert "還沒關檔就要看得到" in path.read_text(encoding="utf-8")
        log.close()

    def test_creates_parent_directories(self, tmp_path):
        path = tmp_path / "a" / "b" / "talk.txt"
        with TranscriptWriter(path) as log:
            log.write(Entry(1, 0.0, 1.0, "x"))

        assert path.exists()

    def test_write_before_open_is_ignored(self):
        TranscriptWriter.__new__(TranscriptWriter)  # 確保不會因未初始化而爆炸
        log = TranscriptWriter(__import__("pathlib").Path("/tmp/never-created.txt"))
        log.write(Entry(1, 0.0, 1.0, "x"))  # 沒 open() 就寫，應安靜忽略
