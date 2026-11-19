#!/usr/bin/env python3
"""Generate the 1280x640 GitHub social preview PNG for gemini-baton-for-claude-code.

Reproduce the default image (assets/social-preview.png):
    python3 scripts/make_social_preview.py

Write to a custom output path:
    python3 scripts/make_social_preview.py /path/to/output.png
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1280
HEIGHT = 640
SCALE = 2

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_OUTPUT = REPO_ROOT / "assets" / "social-preview.png"

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
FONT_BOLD_PATH = FONT_DIR / "DejaVuSans-Bold.ttf"
FONT_REGULAR_PATH = FONT_DIR / "DejaVuSans.ttf"
FONT_MONO_PATH = FONT_DIR / "DejaVuSansMono.ttf"

# Dark theme palette centered around GitHub dark (#0d1117).
BG_TOP: tuple[int, int, int] = (16, 21, 29)
BG_BOTTOM: tuple[int, int, int] = (10, 14, 19)
FRAME_BORDER: tuple[int, int, int] = (33, 38, 45)
ACCENT_BLUE: tuple[int, int, int] = (88, 166, 255)
TITLE_COLOR: tuple[int, int, int] = (240, 246, 252)
SUBTITLE_COLOR: tuple[int, int, int] = (154, 165, 177)
ARROW_COLOR: tuple[int, int, int] = (125, 133, 144)

TITLE_TEXT = "gemini-baton-for-claude-code"
SUBTITLE_TEXT = "Claude plans & verifies. Gemini implements."


@dataclass(frozen=True)
class NodeSpec:
    """Visual specification for one step in the flow diagram."""

    label: str
    font_kind: str
    base_width: int
    fill: tuple[int, int, int]
    outline: tuple[int, int, int]
    text_color: tuple[int, int, int]


FLOW_NODES: tuple[NodeSpec, ...] = (
    NodeSpec(
        label="Claude Code",
        font_kind="bold",
        base_width=232,
        fill=(22, 27, 34),
        outline=(59, 70, 84),
        text_color=(240, 246, 252),
    ),
    NodeSpec(
        label="baton",
        font_kind="mono",
        base_width=160,
        fill=(19, 28, 40),
        outline=(88, 166, 255),
        text_color=(121, 192, 255),
    ),
    NodeSpec(
        label="agy",
        font_kind="mono",
        base_width=160,
        fill=(22, 27, 34),
        outline=(59, 70, 84),
        text_color=(201, 209, 217),
    ),
    NodeSpec(
        label="Gemini",
        font_kind="bold",
        base_width=232,
        fill=(22, 27, 34),
        outline=(59, 70, 84),
        text_color=(240, 246, 252),
    ),
)


def load_font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    """Load a required TrueType font; raise a clear error instead of falling back."""
    if not path.is_file():
        raise FileNotFoundError(
            f"Required font file not found: {path}. "
            "Install DejaVu TrueType fonts (e.g. fonts-dejavu-core)."
        )
    try:
        return ImageFont.truetype(str(path), size=size)
    except OSError as exc:
        raise RuntimeError(f"Could not load TrueType font '{path}': {exc}") from exc


def fit_font(
    path: Path,
    text: str,
    max_width: int,
    start_size: int,
    min_size: int = 12,
) -> ImageFont.FreeTypeFont:
    """Load a TrueType font at the largest size <= start_size that fits max_width."""
    for size in range(start_size, min_size - 1, -1):
        font = load_font(path, size)
        left, _, right, _ = font.getbbox(text)
        if (right - left) <= max_width:
            return font
    raise ValueError(f"Text {text!r} does not fit within {max_width}px even at {min_size}px.")


def _make_background(width: int, height: int) -> Image.Image:
    """Create a subtle dark vertical gradient centered around #0d1117."""
    top_r, top_g, top_b = BG_TOP
    bot_r, bot_g, bot_b = BG_BOTTOM
    denom = max(height - 1, 1)
    buf = bytearray(height * 3)
    for y in range(height):
        t = y / denom
        offset = y * 3
        buf[offset] = round(top_r + (bot_r - top_r) * t)
        buf[offset + 1] = round(top_g + (bot_g - top_g) * t)
        buf[offset + 2] = round(top_b + (bot_b - top_b) * t)
    strip = Image.frombytes("RGB", (1, height), bytes(buf))
    return strip.resize((width, height), Image.Resampling.BILINEAR)


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    center_x: float,
    center_y: float,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
) -> tuple[float, float, float, float]:
    """Draw text horizontally centered on center_x and cap-height centered on center_y."""
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    _, cap_top, _, cap_bottom = draw.textbbox((0, 0), "H", font=font)
    x = center_x - (left + right) / 2
    y = center_y - (cap_top + cap_bottom) / 2
    draw.text((x, y), text, font=font, fill=fill)
    return (x + left, y + top, x + right, y + bottom)


def _draw_arrow(
    draw: ImageDraw.ImageDraw,
    start_x: float,
    end_x: float,
    center_y: float,
    scale: int,
) -> None:
    """Draw a horizontal right-pointing arrow (shaft + filled triangular head)."""
    head_len = 11 * scale
    head_half_h = 6.5 * scale
    shaft_width = 3 * scale
    shaft_end_x = end_x - head_len + 2 * scale
    draw.line(
        [(start_x, center_y), (shaft_end_x, center_y)],
        fill=ARROW_COLOR,
        width=shaft_width,
    )
    draw.polygon(
        [
            (end_x, center_y),
            (end_x - head_len, center_y - head_half_h),
            (end_x - head_len, center_y + head_half_h),
        ],
        fill=ARROW_COLOR,
    )


def render_social_preview() -> Image.Image:
    """Render the 1280x640 social preview image using 2x supersampling."""
    s = SCALE
    canvas_w = WIDTH * s
    canvas_h = HEIGHT * s
    image = _make_background(canvas_w, canvas_h)
    draw = ImageDraw.Draw(image)

    # Subtle inset border frame.
    frame_margin = 36 * s
    draw.rounded_rectangle(
        [frame_margin, frame_margin, canvas_w - frame_margin, canvas_h - frame_margin],
        radius=18 * s,
        outline=FRAME_BORDER,
        width=1 * s,
    )

    # Minimal accent bar above the title.
    pill_half_w = 28 * s
    pill_half_h = 2 * s
    pill_cy = 148 * s
    draw.rounded_rectangle(
        [
            canvas_w / 2 - pill_half_w,
            pill_cy - pill_half_h,
            canvas_w / 2 + pill_half_w,
            pill_cy + pill_half_h,
        ],
        radius=2 * s,
        fill=ACCENT_BLUE,
    )

    # Main title and subtitle.
    max_text_w = (WIDTH - 2 * 100) * s
    title_font = fit_font(FONT_BOLD_PATH, TITLE_TEXT, max_text_w, start_size=58 * s, min_size=24 * s)
    subtitle_font = fit_font(
        FONT_REGULAR_PATH, SUBTITLE_TEXT, max_text_w, start_size=29 * s, min_size=16 * s
    )

    _draw_centered_text(draw, canvas_w / 2, 214 * s, TITLE_TEXT, title_font, TITLE_COLOR)
    _draw_centered_text(draw, canvas_w / 2, 294 * s, SUBTITLE_TEXT, subtitle_font, SUBTITLE_COLOR)

    # Flow diagram: Claude Code -> baton -> agy -> Gemini.
    node_fonts: dict[str, ImageFont.FreeTypeFont] = {
        "bold": load_font(FONT_BOLD_PATH, 24 * s),
        "mono": load_font(FONT_MONO_PATH, 24 * s),
    }

    min_pad_x = 24 * s
    box_h = 80 * s
    arrow_gap = 64 * s
    arrow_pad = 12 * s
    box_cy = 432 * s
    box_y0 = box_cy - box_h / 2
    box_y1 = box_cy + box_h / 2

    box_widths: list[int] = []
    for node in FLOW_NODES:
        font = node_fonts[node.font_kind]
        left, _, right, _ = font.getbbox(node.label)
        text_w = right - left
        box_widths.append(max(node.base_width * s, int(text_w + 2 * min_pad_x)))

    total_w = sum(box_widths) + arrow_gap * (len(FLOW_NODES) - 1)
    max_diagram_w = (WIDTH - 2 * 80) * s
    if total_w > max_diagram_w:
        raise ValueError(
            f"Flow diagram width ({total_w / s:.0f}px) exceeds safe canvas width "
            f"({max_diagram_w / s:.0f}px)."
        )

    cursor_x = (canvas_w - total_w) / 2
    for index, (node, box_w) in enumerate(zip(FLOW_NODES, box_widths)):
        x0 = cursor_x
        x1 = cursor_x + box_w
        draw.rounded_rectangle(
            [x0, box_y0, x1, box_y1],
            radius=14 * s,
            fill=node.fill,
            outline=node.outline,
            width=2 * s,
        )
        font = node_fonts[node.font_kind]
        ink_x0, ink_y0, ink_x1, ink_y1 = _draw_centered_text(
            draw, (x0 + x1) / 2, box_cy, node.label, font, node.text_color
        )
        if ink_x0 < x0 + 8 * s or ink_x1 > x1 - 8 * s or ink_y0 < box_y0 + 8 * s or ink_y1 > box_y1 - 8 * s:
            raise ValueError(f"Label {node.label!r} overflows its flow diagram box.")

        if index < len(FLOW_NODES) - 1:
            _draw_arrow(draw, x1 + arrow_pad, x1 + arrow_gap - arrow_pad, box_cy, s)
        cursor_x = x1 + arrow_gap

    return image.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the 1280x640 social preview PNG for gemini-baton-for-claude-code."
    )
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        default=None,
        help="Optional output PNG path (default: assets/social-preview.png relative to the repo root).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    output_path: Path = args.output if args.output is not None else DEFAULT_OUTPUT

    try:
        image = render_social_preview()
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
