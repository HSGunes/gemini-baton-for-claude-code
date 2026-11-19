#!/usr/bin/env python3
"""Generate a pure-CSS animated dark terminal SVG from a text transcript."""

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
from xml.sax.saxutils import escape

WIDTH = 900
TITLE_BAR_H = 38
PAD_X = 24
PAD_TOP = 18
PAD_BOTTOM = 20
FONT_SIZE = 14
LINE_HEIGHT = 20
MAX_COLS = 96
PROMPT_END_X = 15
FONT_FAMILY = "DejaVu Sans Mono, Menlo, Consolas, monospace"

# Timing constants in exact integer milliseconds.
CMD_CHAR_MS = 32
CMD_MIN_MS = 800
CMD_MAX_MS = 2200
CMD_ENTER_MS = 450
PRE_CMD_MS = 600
OUT_LINE_MS = 160
BLANK_LINE_MS = 60
END_HOLD_MS = 4500
FADE_MS = 800
RESET_MS = 500
MAX_TOTAL_MS = 34000

PROGRESS_RE = re.compile(r"^([.FEspfxX]+)(\s+)(\[\s*\d+%\])$")
PYTEST_SUMMARY_RE = re.compile(r"\b(\d+\s+(?:failed|passed|errors?|warnings?))\b")
HEADER_EQ_RE = re.compile(r"^=+\s+(.+?)\s+=+$")
UNDERLINE_RE = re.compile(r"^_+\s+.+\s+_+$")
SECTION_RE = re.compile(r"^[A-Z][A-Za-z /]+:$")
TABLE_RULE_RE = re.compile(r"^-(?:-|\s)+-$")
TABLE_HEADER_RE = re.compile(r"^[A-Z][A-Z0-9 _-]+$")


@dataclass
class VisualRow:
    row_idx: int
    text: str
    is_cmd: bool
    is_cmd_start: bool
    is_cmd_end: bool
    t_start_ms: int = 0
    t_type_end_ms: int = 0
    t_cursor_off_ms: int = 0


def wrap_line(line: str, max_cols: int = MAX_COLS) -> list[str]:
    """Wrap lines longer than max_cols at word boundaries without losing text."""
    cleaned = line.rstrip()
    if len(cleaned) <= max_cols:
        return [cleaned]

    if cleaned.startswith("$ "):
        cont_indent = "  "
    elif cleaned.startswith("  - "):
        cont_indent = "    "
    else:
        leading = len(cleaned) - len(cleaned.lstrip(" "))
        cont_indent = " " * min(leading, 8)

    chunks: list[str] = []
    remaining = cleaned
    first = True
    while remaining:
        prefix = "" if first else cont_indent
        limit = max_cols - len(prefix)
        if len(remaining) <= limit:
            chunks.append(prefix + remaining)
            break
        min_cut = (len(remaining) - len(remaining.lstrip(" "))) if first else 0
        cut = remaining.rfind(" ", 0, limit + 1)
        if cut > min_cut:
            chunks.append(prefix + remaining[:cut])
            remaining = remaining[cut + 1 :]
        else:
            chunks.append(prefix + remaining[:limit])
            remaining = remaining[limit:]
        first = False
    return chunks


def build_rows(raw_lines: list[str]) -> list[VisualRow]:
    rows: list[VisualRow] = []
    for raw in raw_lines:
        stripped = raw.rstrip()
        is_cmd = stripped.startswith("$ ")
        chunks = wrap_line(stripped, MAX_COLS)
        last_idx = len(chunks) - 1
        for i, chunk in enumerate(chunks):
            rows.append(
                VisualRow(
                    row_idx=len(rows),
                    text=chunk,
                    is_cmd=is_cmd,
                    is_cmd_start=is_cmd and i == 0,
                    is_cmd_end=is_cmd and i == last_idx,
                )
            )
    return rows


def schedule_rows(rows: list[VisualRow]) -> tuple[int, int, int]:
    """Assign exact millisecond timestamps and return (fade_start, fade_end, total)."""
    t_ms = 0
    for row in rows:
        if not row.text:
            row.t_start_ms = t_ms
            t_ms += BLANK_LINE_MS
            continue

        if row.is_cmd:
            if row.is_cmd_start and row.row_idx > 0:
                t_ms += PRE_CMD_MS
            row.t_start_ms = t_ms
            n_chars = max(len(row.text) - 2, 0)
            if n_chars > 0:
                type_ms = min(max(n_chars * CMD_CHAR_MS, CMD_MIN_MS), CMD_MAX_MS)
            else:
                type_ms = 0
            t_ms += type_ms
            row.t_type_end_ms = t_ms
            if row.is_cmd_end:
                t_ms += CMD_ENTER_MS
            row.t_cursor_off_ms = t_ms
        else:
            row.t_start_ms = t_ms
            t_ms += OUT_LINE_MS

    fixed_tail_ms = END_HOLD_MS + FADE_MS + RESET_MS
    max_content_ms = MAX_TOTAL_MS - fixed_tail_ms
    if t_ms > max_content_ms and t_ms > 0:
        for row in rows:
            row.t_start_ms = (row.t_start_ms * max_content_ms) // t_ms
            row.t_type_end_ms = (row.t_type_end_ms * max_content_ms) // t_ms
            row.t_cursor_off_ms = (row.t_cursor_off_ms * max_content_ms) // t_ms
        t_ms = max_content_ms

    fade_start_ms = t_ms + END_HOLD_MS
    fade_end_ms = fade_start_ms + FADE_MS
    total_ms = fade_end_ms + RESET_MS
    return fade_start_ms, fade_end_ms, total_ms


def format_pct(hundredths: int) -> str:
    return f"{hundredths // 100}.{hundredths % 100:02d}%"


def format_sec(ms: int) -> str:
    return f"{ms // 1000}.{(ms % 1000) // 10:02d}s"


def _format_progress_dots(dots: str) -> str:
    parts: list[str] = []
    cur_cls = ""
    buf: list[str] = []
    for ch in dots:
        if ch == ".":
            cls = "ok"
        elif ch in ("F", "E"):
            cls = "err b"
        else:
            cls = "warn"
        if cls != cur_cls:
            if buf:
                parts.append(f'<tspan class="{cur_cls}">{escape("".join(buf))}</tspan>')
                buf = []
            cur_cls = cls
        buf.append(ch)
    if buf:
        parts.append(f'<tspan class="{cur_cls}">{escape("".join(buf))}</tspan>')
    return "".join(parts)


def format_line_content(text: str, is_cmd: bool, is_cmd_start: bool) -> tuple[str, str]:
    """Return (css_class, xml_inner) for a terminal line without altering its text."""
    if is_cmd:
        if is_cmd_start and text.startswith("$ "):
            return ("cmd", f'<tspan class="prompt">$ </tspan>{escape(text[2:])}')
        return ("cmd", escape(text))

    progress_match = PROGRESS_RE.match(text)
    if progress_match:
        dots, spaces, pct = progress_match.groups()
        inner = (
            f"{_format_progress_dots(dots)}"
            f"{escape(spaces)}"
            f'<tspan class="dim">{escape(pct)}</tspan>'
        )
        return ("out", inner)

    header_match = HEADER_EQ_RE.match(text)
    if header_match:
        label = header_match.group(1)
        if "FAIL" in label or "ERROR" in label:
            return ("err b", escape(text))
        if "short test summary" in label.lower():
            return ("dim", escape(text))
        return ("head b", escape(text))

    if UNDERLINE_RE.match(text):
        return ("err b", escape(text))

    if text.startswith("FAILED "):
        return ("out", f'<tspan class="err b">FAILED</tspan>{escape(text[6:])}')

    if text == "E" or text.startswith("E "):
        return ("err", escape(text))

    if text.startswith("> "):
        return ("warn", escape(text))

    if text.endswith("Error") and ": " in text and not text.startswith(" "):
        prefix, err_name = text.rsplit(": ", 1)
        return ("out", f'{escape(prefix)}: <tspan class="err">{escape(err_name)}</tspan>')

    if " in " in text and ("passed" in text or "failed" in text) and PYTEST_SUMMARY_RE.search(text):
        chunks: list[str] = []
        pos = 0
        has_fail = False
        for m in PYTEST_SUMMARY_RE.finditer(text):
            if m.start() > pos:
                chunks.append(escape(text[pos : m.start()]))
            token = m.group(1)
            if "failed" in token or "error" in token:
                has_fail = True
                chunks.append(f'<tspan class="err b">{escape(token)}</tspan>')
            elif "passed" in token:
                chunks.append(f'<tspan class="ok b">{escape(token)}</tspan>')
            else:
                chunks.append(f'<tspan class="warn">{escape(token)}</tspan>')
            pos = m.end()
        if pos < len(text):
            chunks.append(escape(text[pos:]))
        base_cls = "ok" if (not has_fail and "passed" in text) else "out"
        return (base_cls, "".join(chunks))

    if text == "Successful: Yes":
        return ("ok b", escape(text))
    if text == "Successful: No":
        return ("err b", escape(text))

    if re.search(r"\bcompleted\b", text):
        parts = re.split(r"(\bcompleted\b)", text)
        inner = "".join(
            '<tspan class="ok b">completed</tspan>' if part == "completed" else escape(part)
            for part in parts
        )
        return ("out", inner)

    if SECTION_RE.match(text):
        return ("head b", escape(text))

    if TABLE_RULE_RE.match(text):
        return ("dim", escape(text))

    if TABLE_HEADER_RE.match(text) and "  " in text:
        return ("dim b", escape(text))

    if re.search(r"\bbitti\b", text):
        parts = re.split(r"(\bbitti\b)", text)
        inner = "".join(
            '<tspan class="ok b">bitti</tspan>' if part == "bitti" else escape(part)
            for part in parts
        )
        return ("out", inner)

    return ("out", escape(text))


def build_svg(raw_lines: list[str]) -> str:
    rows = build_rows(raw_lines)
    fade_start_ms, fade_end_ms, total_ms = schedule_rows(rows)

    num_rows = max(len(rows), 1)
    height = TITLE_BAR_H + PAD_TOP + num_rows * LINE_HEIGHT + PAD_BOTTOM
    dur_str = format_sec(total_ms)
    p_fade_start = (fade_start_ms * 10000) // total_ms
    p_fade_end = (fade_end_ms * 10000) // total_ms
    fade_start_s = format_pct(p_fade_start)
    fade_end_s = format_pct(p_fade_end)

    css_lines: list[str] = [
        f'text{{font-family:"DejaVu Sans Mono",Menlo,Consolas,monospace;font-size:{FONT_SIZE}px;white-space:pre}}',
        ".title{fill:#8b949e;font-size:13px;font-weight:600}",
        ".out{fill:#c9d1d9}",
        ".cmd{fill:#a5d6ff}",
        ".prompt{fill:#58a6ff;font-weight:700}",
        ".err{fill:#f85149}",
        ".ok{fill:#3fb950}",
        ".warn{fill:#e3b341}",
        ".head{fill:#d2a8ff}",
        ".dim{fill:#8b949e}",
        ".b{font-weight:700}",
        (
            f".line{{animation-duration:{dur_str};animation-timing-function:linear;"
            "animation-iteration-count:infinite;animation-fill-mode:both}"
        ),
        (
            f".mask{{opacity:0;animation-duration:{dur_str};animation-timing-function:linear;"
            "animation-iteration-count:infinite;animation-fill-mode:both}"
        ),
    ]

    mask_css: list[str] = []
    body_elems: list[str] = []

    for row in rows:
        if not row.text:
            continue

        idx = row.row_idx
        y = TITLE_BAR_H + PAD_TOP + idx * LINE_HEIGHT + 15
        p_start = (row.t_start_ms * 10000) // total_ms

        if p_start == 0:
            css_lines.append(
                f".l{idx}{{animation-name:l{idx}}}"
                f"@keyframes l{idx}{{0%,{fade_start_s}{{opacity:1}}{fade_end_s},100%{{opacity:0}}}}"
            )
        else:
            start_s = format_pct(p_start)
            css_lines.append(
                f".l{idx}{{animation-name:l{idx}}}"
                f"@keyframes l{idx}{{0%{{opacity:0;animation-timing-function:step-end}}"
                f"{start_s}{{opacity:1;animation-timing-function:linear}}"
                f"{fade_start_s}{{opacity:1}}{fade_end_s},100%{{opacity:0}}}}"
            )

        cls, inner = format_line_content(row.text, row.is_cmd, row.is_cmd_start)
        body_elems.append(
            f'    <text x="0" y="{y}" class="line {cls} l{idx}" xml:space="preserve">{inner}</text>'
        )

        if row.is_cmd:
            n_chars = max(len(row.text) - 2, 0)
            if n_chars > 0:
                slide_px = (n_chars * 85 + 9) // 10 + 8
                mask_w = slide_px + 24
                steps_n = min(n_chars, 48)
                p_end = max((row.t_type_end_ms * 10000) // total_ms, p_start + 1)
                p_off = max((row.t_cursor_off_ms * 10000) // total_ms, p_end + 1)
                p_end = min(p_end, p_fade_start - 2)
                p_off = min(p_off, p_fade_start - 1)
                end_s = format_pct(p_end)
                off_s = format_pct(p_off)

                if p_start == 0:
                    mask_css.append(
                        f".m{idx}{{animation-name:m{idx}}}"
                        f"@keyframes m{idx}{{0%{{opacity:1;transform:translateX(0px);"
                        f"animation-timing-function:steps({steps_n},end)}}"
                        f"{end_s}{{opacity:1;transform:translateX({slide_px}px);"
                        "animation-timing-function:step-end}"
                        f"{off_s},100%{{opacity:0;transform:translateX({slide_px}px)}}}}"
                    )
                else:
                    start_s = format_pct(p_start)
                    mask_css.append(
                        f".m{idx}{{animation-name:m{idx}}}"
                        f"@keyframes m{idx}{{0%{{opacity:0;transform:translateX(0px);"
                        "animation-timing-function:step-end}"
                        f"{start_s}{{opacity:1;transform:translateX(0px);"
                        f"animation-timing-function:steps({steps_n},end)}}"
                        f"{end_s}{{opacity:1;transform:translateX({slide_px}px);"
                        "animation-timing-function:step-end}"
                        f"{off_s},100%{{opacity:0;transform:translateX({slide_px}px)}}}}"
                    )

                body_elems.append(
                    f'    <g class="mask m{idx}">'
                    f'<rect x="{PROMPT_END_X}" y="{y - 15}" width="{mask_w}" height="{LINE_HEIGHT}" fill="#0d1117"/>'
                    f'<rect x="{PROMPT_END_X}" y="{y - 13}" width="8" height="16" rx="1" fill="#58a6ff"/>'
                    "</g>"
                )

    css_lines.extend(mask_css)
    style_block = "\n".join(f"    {line}" for line in css_lines)
    clip_w = WIDTH - PAD_X - 4

    svg_parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height}" '
            f'width="{WIDTH}" height="{height}" font-family="{FONT_FAMILY}" '
            'role="img" aria-label="baton demo terminal recording">'
        ),
        "  <title>baton demo</title>",
        "  <defs>",
        f'    <clipPath id="screen"><rect x="0" y="{TITLE_BAR_H + 1}" width="{clip_w}" height="{height - TITLE_BAR_H - 2}"/></clipPath>',
        "  </defs>",
        "  <style>",
        style_block,
        "  </style>",
        f'  <rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{height - 1}" rx="10" ry="10" fill="#0d1117" stroke="#30363d" stroke-width="1"/>',
        f'  <path d="M 1 10 A 9 9 0 0 1 10 1 H {WIDTH - 10} A 9 9 0 0 1 {WIDTH - 1} 10 V {TITLE_BAR_H} H 1 Z" fill="#161b22"/>',
        f'  <line x1="1" y1="{TITLE_BAR_H}" x2="{WIDTH - 1}" y2="{TITLE_BAR_H}" stroke="#30363d" stroke-width="1"/>',
        '  <circle cx="20" cy="19" r="6" fill="#ff5f56"/>',
        '  <circle cx="40" cy="19" r="6" fill="#ffbd2e"/>',
        '  <circle cx="60" cy="19" r="6" fill="#27c93f"/>',
        f'  <text x="{WIDTH // 2}" y="23" text-anchor="middle" class="title">baton demo</text>',
        f'  <g transform="translate({PAD_X}, 0)" clip-path="url(#screen)">',
        *body_elems,
        "  </g>",
        "</svg>",
    ]
    return "\n".join(svg_parts) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render a terminal transcript into a looping CSS-animated SVG."
    )
    parser.add_argument("input", type=Path, help="Input transcript text file")
    parser.add_argument("output", type=Path, help="Output SVG file path")
    args = parser.parse_args(argv)

    text = args.input.read_text(encoding="utf-8")
    svg = build_svg(text.splitlines())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(svg, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
