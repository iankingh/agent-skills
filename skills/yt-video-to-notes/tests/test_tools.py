import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import build
import chk
from markdown_regions import mask_markdown

VIDEO = "e0UOuQ_lCUY"
SECOND = "e3DDXSMWr5w"


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.episodes = {"1": build.video_url(VIDEO), "2": build.video_url(SECOND)}

    def test_normalize_single_video_without_expanding_playlist(self):
        for source in [
            VIDEO, f"https://youtu.be/{VIDEO}?list=ignored&t=30",
            f"https://www.youtube.com/watch?v={VIDEO}&list=ignored&index=12",
            f"https://m.youtube.com/shorts/{VIDEO}",
            f"https://youtube.com/live/{VIDEO}",
        ]:
            self.assertEqual(build.video_url(source), f"https://www.youtube.com/watch?v={VIDEO}")
        with self.assertRaises(ValueError):
            build.video_url("https://youtube.com/playlist?list=abc")
        with self.assertRaises(ValueError):
            build.video_url(f"https://youtube.com.example.org/watch?v={VIDEO}")

    def test_timestamp_and_episode_attribution(self):
        result = build.render("{{1:05}} {{2@63:04}} {{ep:1}}", VIDEO, self.episodes)
        self.assertEqual(result,
            f"[1:05](https://www.youtube.com/watch?v={VIDEO}&t=65s) "
            f"[第 2 集 63:04](https://www.youtube.com/watch?v={SECOND}&t=3784s) "
            f"[第 1 集](https://www.youtube.com/watch?v={VIDEO})")

    def test_internal_link_resolution_and_missing_note(self):
        (self.root / "notes").mkdir()
        (self.root / "notes/問題？.md").write_text("內容")
        result = build.render("@@ref", mentions={"ref": "問題？"}, vault=self.root)
        self.assertEqual(result, "[[notes/問題？]]")
        with self.assertRaises(ValueError):
            build.render("@@ref", mentions={"ref": "不存在"}, vault=self.root)
        (self.root / "問題？.md").write_text("另一篇")
        with self.assertRaises(ValueError):
            build.render("@@ref", mentions={"ref": "問題？"}, vault=self.root)

    def test_code_frontmatter_and_callout_fences_preserved(self):
        text = '---\nexample: "{{unknown}}"\n---\n`{{bad}}`\n```js\n{{code}}\n```\n> ```\n> @@code\n> ```\n{{0:03}}'
        self.assertEqual(build.render(text, VIDEO), text.replace(
            "{{0:03}}", f"[0:03](https://www.youtube.com/watch?v={VIDEO}&t=3s)"))

    def test_invalid_or_unmapped_markers_fail(self):
        for text in ["{{1:60}}", "{{-1:02}}", "{{3@1:02}}", "{{ep:3}}",
                     "{{unfinished", "@@missing", "@@"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                build.render(text, VIDEO, self.episodes)
        with self.assertRaises(ValueError):
            build.render("{{1:02}}")

    def test_failure_does_not_create_or_overwrite_output(self):
        draft, output = self.root / "draft.md", self.root / "out.md"
        draft.write_text("{{bad}}")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(build.main(["render", str(draft), "--output", str(output),
                                         "--video", VIDEO]), 2)
        self.assertFalse(output.exists())
        output.write_text("保留")
        draft.write_text("{{0:00}}")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(build.main(["render", str(draft), "--output", str(output),
                                         "--video", VIDEO]), 2)
            self.assertEqual(build.main(["render", str(draft), "--output", str(draft),
                                         "--video", VIDEO, "--overwrite"]), 2)
        self.assertEqual(output.read_text(), "保留")
        self.assertEqual(draft.read_text(), "{{0:00}}")

    def test_render_cli(self):
        draft, output = self.root / "draft.md", self.root / "out.md"
        draft.write_text("# 標題\n{{0:09}}")
        with contextlib.redirect_stdout(io.StringIO()):
            status = build.main(["render", str(draft), "--output", str(output), "--video", VIDEO])
        self.assertEqual(status, 0)
        self.assertIn("&t=9s)", output.read_text())

    def test_resume_missing_and_complete_chapters(self):
        a, b, log = self.root / "a.md", self.root / "b.md", self.root / "created.txt"
        a.write_text("# 第一章\n已驗收")
        b.write_text("# 第二章\n已驗收")
        self.assertTrue(build.record(a, [1], log, self.episodes))
        before = log.read_bytes()
        self.assertFalse(build.record(a, [1], log, self.episodes))
        self.assertEqual(before, log.read_bytes())
        self.assertTrue(any("[2]" in x for x in build.audit([1, 2], log, self.episodes)))
        self.assertTrue(build.record(b, [2], log, self.episodes))
        self.assertEqual(build.audit([1, 2], log, self.episodes), [])
        a.write_text("已修改，待重新驗收")
        self.assertTrue(build.audit([1, 2], log, self.episodes))
        with self.assertRaises(ValueError):
            build.record(a, [1], log, self.episodes)

    def test_duplicate_episode_and_stale_source(self):
        a, b, log = self.root / "a.md", self.root / "b.md", self.root / "created.txt"
        a.write_text("完整章節")
        b.write_text("另一篇")
        build.record(a, [1, 2], log, self.episodes)
        with self.assertRaises(ValueError):
            build.record(b, [2], log, self.episodes)
        self.assertTrue(build.audit([1, 2], log, {"1": build.video_url(SECOND), "2": build.video_url(SECOND)}))
        a.unlink()
        self.assertTrue(build.audit([1, 2], log, self.episodes))

    def test_ranges_scope_and_invalid_log(self):
        self.assertEqual(build.episode_range("2-4"), [2, 3, 4])
        for value in ["0", "3-1", "1,3", "01", "-1"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                build.episode_range(value)
        log = self.root / "created.txt"
        log.write_text(json.dumps({"path": "relative.md"}) + "\n")
        with self.assertRaises(ValueError):
            build.read_log(log)
        log.unlink()
        self.assertTrue(any("缺少來源" in p for p in build.audit([1, 2, 3], log, self.episodes)))

    def test_record_rejects_unresolved_and_does_not_overwrite_note(self):
        note = self.root / "note.md"
        note.write_text("{{ep:1}}")
        with self.assertRaises(ValueError):
            build.record(note, [1], self.root / "created.txt", self.episodes)
        note.write_text("完整章節")
        with self.assertRaises(ValueError):
            build.record(note, [1], note, self.episodes)
        self.assertEqual(note.read_text(), "完整章節")


class CheckerTests(unittest.TestCase):
    def test_mask_retains_positions_and_prose_link_labels(self):
        text = '---\ntitle: 简体\n---\n[简体](https://example.org/简体(a))\n`简体`\n```py\n简体\n```\n<b>简体</b>\n'
        masked = mask_markdown(text, prose_only=True)
        self.assertEqual(len(masked), len(text))
        self.assertEqual(masked.count("\n"), text.count("\n"))
        self.assertEqual(masked.count("简体"), 2)

    def test_missing_dependency_reports_incomplete(self):
        result = subprocess.run([sys.executable, "-S", str(SCRIPTS / "chk.py"), "unused.md"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("檢查未完成", result.stderr)

    def test_real_opencc_findings_and_taiwan_terms(self):
        from opencc import OpenCC
        text = "这是视频，接口。\n干杯，台灣。\n    - 软件\n```py\n软件\n```\nhttps://example.org/软件\n`软件`\n"
        rows = chk.check_text(text, OpenCC("s2t"))
        self.assertTrue(any(r["line"] == 1 and "字形" in r["kind"] for r in rows))
        self.assertTrue(any(r["text"] == "接口" and r["suggestion"] == "介面" for r in rows))
        self.assertTrue(any(r["line"] == 2 and "誤報" in r["kind"] for r in rows))
        self.assertTrue(any(r["line"] == 3 for r in rows))
        self.assertFalse(any(r["line"] > 3 for r in rows))

    def test_checker_cli_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.md"
            path.write_bytes("这是软件\r\n".encode())
            before = path.read_bytes()
            result = subprocess.run([sys.executable, str(SCRIPTS / "chk.py"), str(path), "--json"],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertTrue(json.loads(result.stdout)[0]["findings"])
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
