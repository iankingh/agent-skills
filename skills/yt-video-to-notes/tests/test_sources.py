import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import sources


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def audio(self, seconds=2):
        path = self.root / "audio.wav"
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(16000)
            handle.writeframes(b"\0\0" * int(16000 * seconds))
        return path

    def test_wav_uses_actual_samples_but_never_certifies_content(self):
        path = self.audio()
        before = path.read_bytes()
        result = sources.audit_audio(path, 2, 0)
        self.assertEqual(result["measurement"], "wav_samples")
        self.assertEqual(result["duration_seconds"], 2)
        self.assertTrue(result["duration_matches"])
        self.assertFalse(result["content_verified"])
        self.assertFalse(sources.audit_audio(path, 120, 5)["duration_matches"])
        self.assertEqual(path.read_bytes(), before)

    def test_truncated_and_empty_wav_are_not_successful_capture(self):
        path = self.audio()
        path.write_bytes(path.read_bytes()[:-800])
        with self.assertRaisesRegex(ValueError, "截斷"):
            sources.audio_info(path)
        with self.assertRaisesRegex(ValueError, "空"):
            sources.audio_info(self.audio(0))

    def test_invalid_durations_and_tolerances_fail(self):
        path = self.audio()
        for expected, tolerance in [(0, 5), (-1, 5), (float("nan"), 5),
                                    (2, -1), (2, float("inf"))]:
            with self.subTest(expected=expected, tolerance=tolerance), self.assertRaises(ValueError):
                sources.audit_audio(path, expected, tolerance)

    def test_non_wav_ffprobe_stream_and_format_fallback(self):
        path = self.root / "audio.webm"
        path.write_bytes(b"test compressed input")
        for stream in [{"duration": "3.5", "sample_rate": "48000", "channels": 2},
                       {"duration": "N/A", "sample_rate": "48000", "channels": 2}]:
            output = {"streams": [stream], "format": {"duration": "3.5"}}
            with patch.object(sources.subprocess, "run", return_value=subprocess.CompletedProcess(
                    [], 0, json.dumps(output))) as probe:
                result = sources.audit_audio(path, 3.5, 0)
            self.assertEqual(result["duration_seconds"], 3.5)
            self.assertEqual(probe.call_args.args[0][-1], str(path.resolve()))
            self.assertFalse(result["content_verified"])

    def test_missing_probe_and_no_audio_do_not_pass(self):
        path = self.root / "audio.webm"
        path.write_bytes(b"test")
        with patch.object(sources.subprocess, "run", side_effect=FileNotFoundError("ffprobe")), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(sources.main(["audio", str(path), "--expected-seconds", "2"]), 2)
        with patch.object(sources.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 0, '{"streams": []}')), self.assertRaisesRegex(ValueError, "音軌"):
            sources.audio_info(path)

    def test_audio_cli_marks_mismatch_in_json(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = sources.main(["audio", str(self.audio()), "--expected-seconds", "120"])
        self.assertEqual(result, 1)
        report = json.loads(output.getvalue())
        self.assertEqual(report["duration_seconds"], 2)
        self.assertFalse(report["duration_matches"])

    def test_srt_window_preserves_source_times_and_crossing_cues(self):
        path = self.root / "transcript.srt"
        path.write_text("1\n00:00:00,000 --> 00:00:02,500\n<b>開場</b>\n\n"
                        "2\n00:00:02,500 --> 00:00:05,000\n重點 &amp; 方法\n\n"
                        "3\n00:00:08,000 --> 00:00:09,000\n結尾\n")
        before = path.read_bytes()
        result = sources.transcript_window(path, 2, 5)
        self.assertEqual([row["start"] for row in result], [0, 2.5])
        self.assertEqual(result[0]["text"], "開場")
        self.assertEqual(result[1]["text"], "重點 & 方法")
        self.assertEqual(sources.transcript_window(path, 5, 8), [])
        self.assertEqual(path.read_bytes(), before)

    def test_subtitle_markup_preserves_technical_text(self):
        text = "當 a < b 且 c > d 時，回傳 List<T> & 顯示 <b>"
        for suffix, cue, markup in [
            ("srt", "1\n00:00:00,000 --> 00:00:02,000", '<font color="red"><b>{}</b></font>'),
            ("vtt", "WEBVTT\n\n00:00.000 --> 00:02.000", '<v 講者><00:00.500><c.color><b>{}</b></c></v>'),
        ]:
            with self.subTest(suffix=suffix):
                path = self.root / f"transcript.{suffix}"
                body = markup.format("當 a < b 且 c > d 時，回傳 List<T> &amp; 顯示 &lt;b&gt;")
                path.write_text(f"{cue}\n{body}")
                self.assertEqual(sources.transcript_window(path, 0, 2)[0]["text"], text)

    def test_vtt_cue_ids_settings_and_note_blocks(self):
        path = self.root / "transcript.vtt"
        path.write_text("WEBVTT\n\nNOTE not a cue\n00:00.000 --> 00:01.000\n忽略\n\n"
                        "cue-1\n01:00.000 --> 01:02.500 align:start\n<c.color>實際內容</c>\n")
        result = sources.transcript_window(path, 60, 70)
        self.assertEqual(result, [{"start": 60.0, "end": 62.5, "text": "實際內容"}])

    def test_broken_subtitle_block_cannot_silently_drop_source_content(self):
        path = self.root / "transcript.srt"
        path.write_text("1\n00:00:00,000 --> 00:00:01,000\n已取得\n\n"
                        "2\n沒有時間軸的來源區塊\n")
        with self.assertRaisesRegex(ValueError, "不能靜默略過"):
            sources.transcript_window(path, 0, 10)

    def test_json_segments_support_duration_and_reject_invented_times(self):
        path = self.root / "transcript.json"
        path.write_text(json.dumps({"segments": [
            {"start": 8, "duration": 2, "text": "第二段"},
            {"start": 0, "end": 5, "text": "第一段"}]}))
        self.assertEqual([row["text"] for row in sources.transcript_window(path, 0, 10)],
                         ["第一段", "第二段"])
        for rows in [[], [{"text": "沒有時間"}],
                     [{"start": -1, "end": 5, "text": "錯誤"}],
                     [{"start": 3, "end": 2, "text": "倒退"}],
                     [{"start": 0, "end": float("inf"), "text": "無窮"}]]:
            path.write_text(json.dumps(rows))
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(sources.main(["slice", str(path), "--start", "0", "--end", "10"]), 2)

    def test_slice_cli_empty_window_is_not_fabricated_content(self):
        path = self.root / "transcript.json"
        path.write_text('[{"start":0,"end":1,"text":"內容"}]')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(sources.main(["slice", str(path), "--start", "2", "--end", "4"]), 0)
        self.assertEqual(json.loads(output.getvalue()), [])
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(sources.main(["slice", str(path), "--start", "4", "--end", "2"]), 2)


if __name__ == "__main__":
    unittest.main()
