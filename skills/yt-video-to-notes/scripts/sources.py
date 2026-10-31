#!/usr/bin/env python3
"""Read-only audio duration checks and time-windowed transcript reading.

Exit: 0 duration matches / transcript read; 1 duration mismatch; 2 input/tool error.
Duration checks never certify that audio contains the intended video or speaker.
"""

import argparse
import html
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import wave


def number(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} 必須是有限數字")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} 必須是有限數字")
    return result


def audio_info(path):
    if not path.is_file():
        raise ValueError("音訊檔不存在")
    with path.open("rb") as handle:
        header = handle.read(12)
    if header[:4] == b"RIFF" and header[8:12] == b"WAVE":
        with wave.open(str(path), "rb") as audio:
            rate, channels = audio.getframerate(), audio.getnchannels()
            frame_size = channels * audio.getsampwidth()
            if rate <= 0 or frame_size <= 0:
                raise ValueError("無效的 WAV 取樣資訊")
            expected_frames, actual_bytes = audio.getnframes(), 0
            while chunk := audio.readframes(65536):
                actual_bytes += len(chunk)
            if actual_bytes % frame_size or actual_bytes // frame_size != expected_frames:
                raise ValueError("WAV 音訊截斷：實際樣本數與檔頭不符")
            duration = actual_bytes / frame_size / rate
            result = {"measurement": "wav_samples", "duration_seconds": duration,
                      "sample_rate": rate, "channels": channels}
    else:
        command = ["ffprobe", "-v", "error", "-select_streams", "a:0",
                   "-show_entries", "stream=duration,sample_rate,channels:format=duration",
                   "-of", "json", str(path.resolve())]
        probe = subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
        data = json.loads(probe.stdout)
        streams = data.get("streams", [])
        if not streams:
            raise ValueError("ffprobe 未找到音軌")
        stream = streams[0]
        duration = stream.get("duration")
        if duration in (None, "N/A"):
            duration = data.get("format", {}).get("duration")
        result = {"measurement": "ffprobe", "duration_seconds": number(duration, "音訊長度"),
                  "sample_rate": stream.get("sample_rate"), "channels": stream.get("channels")}
    if result["duration_seconds"] <= 0:
        raise ValueError("音訊為空或沒有有效長度")
    return result


def audit_audio(path, expected, tolerance=5):
    expected, tolerance = number(expected, "影片長度"), number(tolerance, "容許秒數")
    if expected <= 0 or tolerance < 0:
        raise ValueError("影片長度須大於零，容許秒數不得為負")
    result = audio_info(path)
    result.update({"expected_seconds": expected, "tolerance_seconds": tolerance,
                   "difference_seconds": result["duration_seconds"] - expected,
                   "duration_matches": abs(result["duration_seconds"] - expected) <= tolerance,
                   "content_verified": False})
    return result


def cue_time(value):
    parts = value.replace(",", ".").split(":")
    if len(parts) not in (2, 3):
        raise ValueError("字幕時間須為 mm:ss.mmm 或 hh:mm:ss.mmm")
    nums = [number(part, "字幕時間") for part in parts]
    if nums[0] < 0 or any(n < 0 or n >= 60 for n in nums[1:]):
        raise ValueError("字幕時間超出有效範圍")
    return sum(n * 60 ** power for power, n in enumerate(reversed(nums)))


def load_segments(path):
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        rows = data.get("segments") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise ValueError("逐字稿 JSON 須為區段陣列，或包含 segments 陣列")
    elif path.suffix.lower() in {".srt", ".vtt"}:
        rows = []
        for block in re.split(r"\r?\n[ \t]*\r?\n", text.strip()):
            lines = block.splitlines()
            if lines and re.match(r"^(NOTE|STYLE|REGION)(?:\s|$)", lines[0]):
                continue
            parsed = False
            for index, line in enumerate(lines):
                if "-->" not in line:
                    continue
                match = re.fullmatch(r"\s*([\d:.,]+)\s+-->\s+([\d:.,]+)(?:\s+.*)?", line)
                if not match:
                    raise ValueError("字幕時間軸格式錯誤")
                body = " ".join(lines[index + 1:])
                body = html.unescape(re.sub(r"<[^>]*>", "", body)).strip()
                rows.append({"start": cue_time(match[1]), "end": cue_time(match[2]), "text": body})
                parsed = True
                break
            if not parsed and (not lines or not lines[0].startswith("WEBVTT")):
                raise ValueError("字幕區塊缺少有效時間軸，不能靜默略過")
    else:
        raise ValueError("僅支援 JSON、SRT 或 VTT 逐字稿")
    result = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("text"), str):
            raise ValueError("逐字稿區段須包含 text 字串")
        start = number(row.get("start"), "區段開始時間")
        end = (number(row["end"], "區段結束時間") if "end" in row
               else start + number(row.get("duration"), "區段長度"))
        if start < 0 or end <= start:
            raise ValueError("逐字稿區段時間無效")
        if row["text"].strip():
            result.append({"start": start, "end": end, "text": row["text"].strip()})
    if not result:
        raise ValueError("沒有可讀取的含時間區段；不從純文字推測時間")
    return sorted(result, key=lambda row: (row["start"], row["end"]))


def transcript_window(path, start, end):
    start, end = number(start, "開始秒數"), number(end, "結束秒數")
    if start < 0 or end <= start:
        raise ValueError("閱讀區間須為遞增的非負秒數")
    return [row for row in load_segments(path) if row["start"] < end and row["end"] > start]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    audio = sub.add_parser("audio", help="只核對長度，內容仍需人工抽查")
    audio.add_argument("file", type=Path)
    audio.add_argument("--expected-seconds", type=float, required=True)
    audio.add_argument("--tolerance-seconds", type=float, default=5)
    read = sub.add_parser("slice", help="只讀取與指定秒數區間重疊的字幕／逐字稿")
    read.add_argument("file", type=Path)
    read.add_argument("--start", type=float, required=True)
    read.add_argument("--end", type=float, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "audio":
            result = audit_audio(args.file, args.expected_seconds, args.tolerance_seconds)
            status = int(not result["duration_matches"])
        else:
            result = transcript_window(args.file, args.start, args.end)
            status = 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return status
    except (ValueError, TypeError, KeyError, OSError, EOFError, wave.Error,
            subprocess.SubprocessError) as exc:
        print(f"來源檢查未完成：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
