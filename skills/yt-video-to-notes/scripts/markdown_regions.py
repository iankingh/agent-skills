"""Offset-preserving masks for the note helpers; never rewrite input files."""

import re


def mask_markdown(text, prose_only=False):
    """Hide code and frontmatter; optionally hide link targets, tags and URLs.

    Newlines and string length are preserved for useful line/column diagnostics.
    This is a conservative scanner for normal Markdown, including callout fences.
    """
    chars = list(text)

    def hide(start, end):
        for pos in range(start, end):
            if chars[pos] not in "\r\n":
                chars[pos] = " "

    frontmatter = re.match(r"\A---[ \t]*\r?\n.*?\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|$)", text, re.S)
    if frontmatter:
        hide(*frontmatter.span())
    offset = 0
    fence = None
    for line in text.splitlines(keepends=True):
        logical = re.sub(r"^(?:[ \t]*>[ \t]?)+", "", line)
        match = re.match(r"^[ \t]*(?:[-+*] |\d+\. )?(`{3,}|~{3,})(.*)", logical)
        if fence:
            hide(offset, offset + len(line))
            if match and match[1][0] == fence[0] and len(match[1]) >= fence[1] and not match[2].strip():
                fence = None
        elif match:
            fence = (match[1][0], len(match[1]))
            hide(offset, offset + len(line))
        elif (line.startswith("\t") or line.startswith("    ")) and not re.match(
                r"^\s*(?:[-+*] |\d+[.)] )", line):
            # Indented blocks can be code. Err toward avoiding false positives.
            hide(offset, offset + len(line))
        offset += len(line)
    for match in re.finditer(r"<(pre|code)\b[^>]*>.*?</\1\s*>", "".join(chars), re.S | re.I):
        hide(*match.span())

    # Match inline code using the exact opening backtick run.
    masked = "".join(chars)
    pos = 0
    while pos < len(masked):
        if masked[pos] != "`":
            pos += 1
            continue
        end = pos
        while end < len(masked) and masked[end] == "`":
            end += 1
        marker = masked[pos:end]
        closing = re.search(r"(?<!`)" + re.escape(marker) + r"(?!`)", masked[end:])
        if closing:
            stop = end + closing.end()
            hide(pos, stop)
            pos = stop
        else:
            pos = end

    if prose_only:
        # Link destinations can contain nested parentheses and escaped characters.
        masked = "".join(chars)
        for match in re.finditer(r"\]\(", masked):
            start = pos = match.end()
            depth = 1
            while pos < len(masked) and depth:
                if masked[pos] == "\\":
                    pos += 2
                    continue
                if masked[pos] == "(":
                    depth += 1
                elif masked[pos] == ")":
                    depth -= 1
                pos += 1
            hide(start, pos - 1 if depth == 0 else pos)
        patterns = [
            r"https?://[^\s<>]+",
            r"<[^>\n]+>",
            r"(?m)^[ ]{0,3}\[[^\]\n]+\]:[^\n]*",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, "".join(chars)):
                hide(*match.span())
        for match in re.finditer(r"\[\[([^\]\n]+)\]\]", "".join(chars)):
            target_end = match.start(1) + len(match[1].split("|", 1)[0])
            hide(match.start(), target_end)
            hide(match.end() - 2, match.end())
    return "".join(chars)
