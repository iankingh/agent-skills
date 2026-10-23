#!/usr/bin/env python3
"""Read-only OpenCC check for newly written notes. Exit: 0 clean, 1 review, 2 error."""

import argparse
import difflib
import json
from pathlib import Path
import re
import sys

from markdown_regions import mask_markdown


COMMON_AMBIGUOUS = set("峰秘游台里群吃占托干床")
TW_TERMS = {
    "面向對象": "物件導向", "面向对象": "物件導向",
    "事務": "交易（依語境）", "事务": "交易（依語境）",
    "異常": "例外（程式語境）", "异常": "例外（程式語境）",
    "數據源": "資料來源", "数据源": "資料來源",
    "接口": "介面", "視頻": "影片", "视频": "影片",
}


def check_text(text, converter):
    masked = mask_markdown(text, prose_only=True)
    findings = []
    for number, line in enumerate(masked.splitlines(), 1):
        converted = converter.convert(line)
        diff = difflib.SequenceMatcher(a=line, b=converted, autojunk=False)
        for tag, a, b, c, d in diff.get_opcodes():
            if tag == "equal":
                continue
            before, after = line[a:b], converted[c:d]
            review = bool(before) and all(ch in COMMON_AMBIGUOUS for ch in before)
            findings.append({
                "line": number, "column": a + 1,
                "kind": "常見誤報候選，需看上下文" if review else "疑似簡體／字形差異",
                "text": before, "suggestion": after,
            })
        for word, replacement in TW_TERMS.items():
            for match in re.finditer(re.escape(word), line):
                findings.append({
                    "line": number, "column": match.start() + 1,
                    "kind": "台灣用語（依語境）", "text": word, "suggestion": replacement,
                })
        for match in re.finditer(r"立[ \t]*flag\b", line, re.I):
            findings.append({
                "line": number, "column": match.start() + 1,
                "kind": "台灣用語（依語境）", "text": match[0], "suggestion": "許下目標",
            })
    return sorted(findings, key=lambda row: (row["line"], row["column"], row["kind"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true", help="輸出 JSON 報告")
    args = parser.parse_args(argv)
    try:
        from opencc import OpenCC
    except ImportError:
        print("檢查未完成：缺少 OpenCC。請在使用的 Python 環境安裝 opencc-python-reimplemented；本程式不修改原文。", file=sys.stderr)
        return 2
    try:
        # s2t checks characters; Taiwan terminology is reported separately above.
        # Do not s2twp-convert names, quoted text or imported notes automatically.
        converter = OpenCC("s2t")
        results = [{"file": str(path), "findings": check_text(path.read_text(encoding="utf-8"), converter)}
                   for path in args.files]
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"檢查未完成：{exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for result in results:
            if not result["findings"]:
                print(f"{result['file']}: 未發現疑似字形或用語問題（不代表語意已驗證）")
            for row in result["findings"]:
                print(f"{result['file']}:{row['line']}:{row['column']}: {row['kind']}："
                      f"{row['text']} → {row['suggestion']}")
    return int(any(result["findings"] for result in results))


if __name__ == "__main__":
    sys.exit(main())
