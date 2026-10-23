#!/usr/bin/env python3
"""Build new Markdown notes and track explicitly requested playlist chapters."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urlsplit

from markdown_regions import mask_markdown


def video_url(value):
    """Normalize a video, ignoring playlist context; never fetch or expand lists."""
    if not isinstance(value, str):
        raise ValueError("影片來源必須是影片 ID 或網址")
    ident = value
    if not re.fullmatch(r"[\w-]{11}", ident, flags=re.ASCII):
        url = urlsplit(value)
        host = (url.hostname or "").lower()
        if url.scheme not in {"https", "http"}:
            raise ValueError(f"無效的 YouTube 網址：{value}")
        if host in {"youtu.be", "www.youtu.be"}:
            ident = url.path.strip("/")
        elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
            if url.path == "/watch":
                ident = parse_qs(url.query).get("v", [""])[0]
            else:
                parts = url.path.strip("/").split("/")
                ident = parts[1] if len(parts) == 2 and parts[0] in {"shorts", "live", "embed"} else ""
        else:
            ident = ""
    if not re.fullmatch(r"[\w-]{11}", ident, flags=re.ASCII):
        raise ValueError(f"無法辨識單支 YouTube 影片：{value}")
    return f"https://www.youtube.com/watch?v={ident}"


def episode_range(value):
    if not re.fullmatch(r"[1-9]\d*(?:-[1-9]\d*)?", value):
        raise ValueError("集數須為正整數或連續範圍，例如 1 或 1-3")
    bounds = [int(x) for x in value.split("-")]
    start, end = bounds[0], bounds[-1]
    if end < start:
        raise ValueError("集數範圍必須遞增")
    return list(range(start, end + 1))


def mappings(path):
    data = json.loads(path.read_text(encoding="utf-8")) if path else {}
    if not isinstance(data, dict):
        raise ValueError("映射檔必須是 JSON 物件")
    episodes, mentions = data.get("episodes", {}), data.get("mentions", {})
    if not isinstance(episodes, dict) or not isinstance(mentions, dict):
        raise ValueError("episodes 與 mentions 必須是物件")
    for key in episodes:
        if not re.fullmatch(r"[1-9]\d*", key):
            raise ValueError(f"無效的集數鍵：{key}")
    return {key: video_url(value) for key, value in episodes.items()}, mentions


def seconds(value):
    if not re.fullmatch(r"\d+:[0-5]\d", value):
        raise ValueError(f"時間須為 m:ss，秒數限 00–59：{value}")
    minutes, secs = map(int, value.split(":"))
    return minutes * 60 + secs


def note_link(target, vault):
    if not vault or not vault.is_dir():
        raise ValueError("@@key 轉換需要存在的 --vault 目錄")
    if not isinstance(target, str) or not target or any(ch in target for ch in "[]|#^\n\r"):
        raise ValueError("筆記映射須為實際檔名或 vault 相對路徑，不含顯示別名或段落")
    root = vault.resolve()
    relative = Path(target if target.endswith(".md") else target + ".md")
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("筆記映射不可超出 vault")
    candidates = ([root / relative] if len(relative.parts) > 1
                  else [p for p in root.rglob("*.md") if p.name == relative.name])
    matches = [p for p in candidates if p.is_file() and p.resolve().is_relative_to(root)]
    if len(matches) != 1:
        raise ValueError(f"筆記不存在或無法唯一定位：{target}")
    return "[[" + matches[0].relative_to(root).as_posix()[:-3] + "]]"


def ensure_resolved(text):
    if re.search(r"\{\{|\}\}|@@", mask_markdown(text)):
        raise ValueError("仍有未解析標記；請檢查時間格式、影片與筆記映射")


def render(text, video=None, episodes=None, mentions=None, vault=None):
    episodes, mentions = episodes or {}, mentions or {}
    default = video_url(video) if video else None
    masked = mask_markdown(text)
    edits = []
    for match in re.finditer(r"\{\{([^{}\n]+)\}\}|(?<![\w@])@@([A-Za-z0-9_-]+)", masked):
        token, key = match.groups()
        if key is not None:
            if key not in mentions:
                raise ValueError(f"缺少筆記映射：{key}")
            value = note_link(mentions[key], vault)
        elif token.startswith("ep:"):
            ep = token[3:]
            if ep not in episodes:
                raise ValueError(f"缺少影片集數映射：{ep}")
            value = f"[第 {ep} 集]({video_url(episodes[ep])})"
        else:
            if "@" in token:
                ep, time = token.split("@", 1)
                if ep not in episodes:
                    raise ValueError(f"缺少影片集數映射：{ep}")
                url, label = video_url(episodes[ep]), f"第 {ep} 集 {time}"
            else:
                time, url, label = token, default, token
                if url is None:
                    raise ValueError("單支時間戳需要 --video")
            value = f"[{label}]({url}&t={seconds(time)}s)"
        edits.append((match.start(), match.end(), value))
    for start, end, value in reversed(edits):
        text = text[:start] + value + text[end:]
    ensure_resolved(text)
    return text


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_log(path):
    if not path.exists():
        return []
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    seen_paths, seen_episodes = set(), set()
    for row in records:
        if not isinstance(row, dict) or set(row) != {"path", "episodes", "sources", "sha256"}:
            raise ValueError("created.txt 紀錄格式錯誤")
        if not isinstance(row["path"], str) or not Path(row["path"]).is_absolute():
            raise ValueError("created.txt 必須記錄絕對路徑")
        eps = row["episodes"]
        if (not isinstance(eps, list) or not eps
                or any(type(n) is not int or n < 1 for n in eps)
                or eps != list(range(eps[0], eps[-1] + 1))):
            raise ValueError("created.txt 集數必須連續且無重複")
        if not isinstance(row["sources"], dict) or set(row["sources"]) != {str(n) for n in eps}:
            raise ValueError("created.txt 來源與集數不符")
        for source in row["sources"].values():
            video_url(source)
        if not isinstance(row["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
            raise ValueError("created.txt SHA-256 格式錯誤")
        if row["path"] in seen_paths or seen_episodes.intersection(eps):
            raise ValueError("created.txt 有重複檔案或重複涵蓋集數")
        seen_paths.add(row["path"])
        seen_episodes.update(eps)
    return records


def record(path, eps, log, episodes):
    path = path.resolve()
    if path.suffix != ".md" or not path.is_file():
        raise ValueError("只能記錄已建立的 Markdown 筆記")
    if log.resolve() == path:
        raise ValueError("紀錄檔不能覆蓋筆記")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError("不能記錄空白筆記")
    ensure_resolved(text)
    if any(str(n) not in episodes for n in eps):
        raise ValueError("所記錄集數缺少來源映射")
    rows = read_log(log)
    new = {"path": str(path), "episodes": eps,
           "sources": {str(n): episodes[str(n)] for n in eps}, "sha256": digest(path)}
    if new in rows:
        return False
    if any(row["path"] == str(path) for row in rows):
        raise ValueError("此檔案的紀錄已變更；重新驗收後移除該舊紀錄，再 record")
    if any(set(row["episodes"]).intersection(eps) for row in rows):
        raise ValueError("其他章節已涵蓋這些集數")
    log.parent.mkdir(parents=True, exist_ok=True)
    # Rebuild the small log so a missing trailing newline cannot corrupt JSONL.
    log.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows + [new]),
                   encoding="utf-8")
    return True


def audit(expected, log, episodes):
    rows = read_log(log)
    problems, covered = [], set()
    missing_sources = [n for n in expected if str(n) not in episodes]
    if missing_sources:
        problems.append(f"缺少來源映射：{missing_sources}")
    for row in rows:
        path = Path(row["path"])
        valid = True
        if not path.is_file() or digest(path) != row["sha256"]:
            problems.append(f"檔案不存在或內容已變動：{path}")
            valid = False
        if any(row["sources"][str(n)] != episodes.get(str(n)) for n in row["episodes"]):
            problems.append(f"來源映射已變動：{path}")
            valid = False
        if valid:
            covered.update(row["episodes"])
    missing, extra = sorted(set(expected) - covered), sorted(covered - set(expected))
    if missing:
        problems.append(f"尚缺已驗收章節：{missing}")
    if extra:
        problems.append(f"紀錄包含指定範圍外集數：{extra}")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    render_parser = sub.add_parser("render", help="轉換草稿標記，保留程式碼與 frontmatter")
    render_parser.add_argument("input", type=Path)
    render_parser.add_argument("--output", type=Path, required=True)
    render_parser.add_argument("--video")
    render_parser.add_argument("--map", type=Path)
    render_parser.add_argument("--vault", type=Path)
    render_parser.add_argument("--overwrite", action="store_true")
    record_parser = sub.add_parser("record", help="人工驗收後記錄完成章節")
    record_parser.add_argument("file", type=Path)
    record_parser.add_argument("--episodes", required=True)
    check_parser = sub.add_parser("check", help="查漏集、重複、來源變更與失效紀錄")
    check_parser.add_argument("--expected", required=True)
    for child in [record_parser, check_parser]:
        child.add_argument("--log", type=Path, required=True)
        child.add_argument("--map", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        episodes, mentions = mappings(args.map)
        if args.command == "render":
            if args.input.resolve() == args.output.resolve():
                raise ValueError("輸出不可覆寫輸入草稿")
            if args.output.exists() and not args.overwrite:
                raise ValueError("輸出已存在；確認可取代後才使用 --overwrite")
            output = render(args.input.read_text(encoding="utf-8"), args.video, episodes, mentions, args.vault)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("w" if args.overwrite else "x", encoding="utf-8") as handle:
                handle.write(output)
            print(args.output)
        elif args.command == "record":
            changed = record(args.file, episode_range(args.episodes), args.log, episodes)
            print("已記錄" if changed else "紀錄一致，無需重複新增")
        else:
            problems = audit(episode_range(args.expected), args.log, episodes)
            print("\n".join(problems) if problems else "指定集數連續、無漏集，來源與已完成檔案一致")
            return int(bool(problems))
    except (ValueError, OSError, UnicodeError) as exc:
        print(f"未完成：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
