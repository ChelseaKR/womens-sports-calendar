"""Generate the site's favicon and Open Graph / Twitter card images.

Hand-authored SVG geometry, rendered to raster with `rsvg-convert` -- the
same pattern used elsewhere in this portfolio (no AI-generated bitmap art).
This script is a one-time/occasional dev tool, not part of the pipeline
build: its *outputs* (the .svg sources and the rendered .png files) are
committed to `pipeline/assets/`, and `build.py::_write_static` copies them
into `dist/` on every run -- so a normal build (including the nightly CI
run) never needs `rsvg-convert` installed. Re-run this script and commit
the results only when the artwork itself changes.

Palette (contrast-checked against WCAG 2.2 AA, same rigor as
`site.STYLE_CSS`):
  navy   #0b1f3a  -- background / glyph fill
  gold   #f4c94c  -- highlighted "next game" cell / accent
  white  #ffffff  -- title text, card background, seam lines
  light  #c9d6ea  -- subtitle text on navy (contrast 11.24:1)
  muted  #8fa8cf  -- small footer/domain text on navy (contrast 6.82:1)
  border #c7ccd1  -- decorative calendar grid lines (non-text, no contrast
                      requirement, but kept off any text use)
Checked ratios (relative-luminance formula, WCAG 2.2 1.4.3):
  navy/white   16.52:1   navy/light  11.24:1   navy/muted  6.82:1
  gold/navy    10.47:1 (glyph fill on the highlighted cell)
All comfortably clear the 4.5:1 (normal text) and 3:1 (large text /
graphical object) AA thresholds.
"""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"

NAVY = "#0b1f3a"
GOLD = "#f4c94c"
WHITE = "#ffffff"
LIGHT = "#c9d6ea"
MUTED = "#8fa8cf"
BORDER = "#c7ccd1"

# The three real leagues this product tracks (wsc_pipeline.config.LEAGUES).
# Order matches config.py.
LEAGUE_GLYPHS = ("wnba", "nwsl", "pwhl")


def _basketball(cx: float, cy: float, r: float) -> str:
    """Circle + seam lines: the classic flat basketball glyph."""
    return f"""
<circle cx="{cx}" cy="{cy}" r="{r}" fill="{NAVY}"/>
<path d="M{cx - r} {cy} H{cx + r} M{cx} {cy - r} V{cy + r}" stroke="{WHITE}" stroke-width="{r * 0.14}" fill="none"/>
<path d="M{cx - r * 0.6} {cy - r} C{cx - r * 0.05} {cy - r * 0.4} {cx - r * 0.05} {cy + r * 0.4} {cx - r * 0.6} {cy + r}"
      stroke="{WHITE}" stroke-width="{r * 0.14}" fill="none"/>
<path d="M{cx + r * 0.6} {cy - r} C{cx + r * 0.05} {cy - r * 0.4} {cx + r * 0.05} {cy + r * 0.4} {cx + r * 0.6} {cy + r}"
      stroke="{WHITE}" stroke-width="{r * 0.14}" fill="none"/>
"""


def _soccer_ball(cx: float, cy: float, r: float) -> str:
    """Circle + a center pentagon + spokes: the classic flat soccer-ball glyph."""
    pts = []
    for i in range(5):
        angle = math.radians(-90 + i * 72)
        pts.append((cx + r * 0.4 * math.cos(angle), cy + r * 0.4 * math.sin(angle)))
    pentagon = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    spokes = "".join(
        f'<path d="M{cx:.1f} {cy:.1f} L{x:.1f} {y:.1f}" stroke="{WHITE}" stroke-width="{r * 0.1}"/>' for x, y in pts
    )
    return f"""
<circle cx="{cx}" cy="{cy}" r="{r}" fill="{NAVY}"/>
{spokes}
<polygon points="{pentagon}" fill="{WHITE}"/>
"""


def _hockey_puck(cx: float, cy: float, r: float) -> str:
    """A short, wide rounded ellipse -- the puck's silhouette (never a circle)."""
    rx, ry = r * 1.05, r * 0.55
    return f"""
<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{NAVY}"/>
<path d="M{cx - rx * 0.7} {cy - ry * 0.15} H{cx + rx * 0.7}" stroke="{WHITE}" stroke-width="{ry * 0.22}" opacity="0.8"/>
"""


GLYPHS = {
    "wnba": _basketball,
    "nwsl": _soccer_ball,
    "pwhl": _hockey_puck,
}


def _calendar_card(*, highlights: list[tuple[int, int, object]]) -> str:
    """The calendar-with-highlighted-game-day(s) motif shared by every
    variant. A 4x7 grid of decorative cells (no dates/numbers -- nothing
    here asserts a real date or count); each (row, col, glyph_fn) in
    `highlights` becomes a gold cell marking "a next home game," with the
    matching sport's glyph. The league variants pass one highlight; the
    site-wide default passes one per tracked league, so it reads as "one
    calendar, three leagues" rather than three glyphs crammed into a
    single cell.
    """
    card_x, card_y, card_w, card_h = 70, 95, 460, 350
    header_h = 72
    cols, rows = 7, 4
    cell, gap_x, gap_y = 46, 10, 12
    grid_w = cols * cell + (cols - 1) * gap_x
    grid_x = card_x + (card_w - grid_w) / 2
    grid_y = card_y + header_h + 24

    highlight_map = {(r, c): fn for r, c, fn in highlights}
    cells = []
    for row in range(rows):
        for col in range(cols):
            x = grid_x + col * (cell + gap_x)
            y = grid_y + row * (cell + gap_y)
            glyph_fn = highlight_map.get((row, col))
            if glyph_fn is not None:
                cells.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="10" fill="{GOLD}"/>')
                cells.append(glyph_fn(x + cell / 2, y + cell / 2, cell * 0.34))
            else:
                cells.append(
                    f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="10" fill="{BORDER}" opacity="0.35"/>'
                )

    # LIGHT, not NAVY: these sit above the card, directly on the navy page
    # background, so a navy fill here would be invisible (same colour as
    # the background it's drawn on).
    tabs = "".join(
        f'<rect x="{card_x + card_w * frac - 6}" y="{card_y - 20}" width="12" height="26" rx="4" fill="{LIGHT}"/>'
        for frac in (0.22, 0.78)
    )

    # A path for the header, rounded at the top to match the card's own
    # corner radius and square at the bottom, rather than a plain rect
    # clipped by the card's rounded-rect clipPath: librsvg's anti-aliased
    # clip mask leaves a faint fringe just outside the card when a sharp
    # interior corner coincides with the mask's rounded corner (visible as
    # two stray arcs above the card) -- a path with the same corner radius
    # sidesteps clipping (and that artifact) entirely.
    r = 24
    header_path = (
        f"M{card_x} {card_y + header_h} "
        f"V{card_y + r} "
        f"A{r} {r} 0 0 1 {card_x + r} {card_y} "
        f"H{card_x + card_w - r} "
        f"A{r} {r} 0 0 1 {card_x + card_w} {card_y + r} "
        f"V{card_y + header_h} Z"
    )

    return f"""
{tabs}
<rect x="{card_x}" y="{card_y}" width="{card_w}" height="{card_h}" rx="{r}" fill="{WHITE}"/>
<path d="{header_path}" fill="{NAVY}"/>
{"".join(cells)}
"""


def _wrap(body: str, *, width: int = 1200, height: int = 630) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">
<rect width="{width}" height="{height}" fill="{NAVY}"/>
{body}
</svg>
"""


def og_image_svg(*, highlights: list[tuple[int, int, object]], title: str, subtitle: str, footer: str) -> str:
    """`title` is always exactly two lines (joined with "\\n") so the
    subtitle's fixed y-offset below it is always correct -- callers below
    only ever pass two-line titles. `subtitle` may be one or two lines;
    the text column is ~560px wide (text_x=580 to the 1200 edge, minus a
    right margin), so anything longer than ~34 characters at font-size 28
    must be pre-wrapped by the caller rather than left to overflow.
    """
    card = _calendar_card(highlights=highlights)
    text_x = 580
    title_top_y = 220
    title_line_height = 68
    subtitle_y = title_top_y + title_line_height * 2 + 30
    return _wrap(f"""
{card}
<text x="{text_x}" y="{title_top_y}" font-family="-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif" font-size="58" font-weight="700" fill="{WHITE}">
{_tspans(title, x=text_x, line_height=title_line_height)}
</text>
<text x="{text_x}" y="{subtitle_y}" font-family="-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif" font-size="28" fill="{LIGHT}">
{_tspans(subtitle, x=text_x, line_height=38)}
</text>
<text x="70" y="590" font-family="-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif" font-size="24" font-weight="600" fill="{MUTED}">{_escape(footer)}</text>
""")


def _tspans(text: str, *, x: int, line_height: int) -> str:
    lines = text.split("\n")
    out = [f'<tspan x="{x}">{_escape(lines[0])}</tspan>']
    for line in lines[1:]:
        out.append(f'<tspan x="{x}" dy="{line_height}">{_escape(line)}</tspan>')
    return "\n".join(out)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def favicon_svg() -> str:
    """A reduced version of the same mark (navy rounded square, gold
    highlighted-day dot, two binder tabs) -- legible down to 16x16."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64" role="img">
<rect x="14" y="2" width="8" height="16" rx="4" fill="{NAVY}"/>
<rect x="42" y="2" width="8" height="16" rx="4" fill="{NAVY}"/>
<rect x="4" y="10" width="56" height="50" rx="12" fill="{NAVY}"/>
<circle cx="32" cy="38" r="15" fill="{GOLD}"/>
</svg>
"""


LEAGUE_NAMES = {"wnba": "WNBA", "nwsl": "NWSL", "pwhl": "PWHL"}


def build_svgs() -> dict[str, str]:
    files: dict[str, str] = {}
    files["favicon.svg"] = favicon_svg()
    # One highlighted cell per tracked league, in config.py order, so the
    # default card reads as "one calendar, three leagues" rather than three
    # glyphs crammed into a single cell.
    files["og-image.svg"] = og_image_svg(
        highlights=[(1, 2, _basketball), (1, 3, _soccer_ball), (1, 4, _hockey_puck)],
        title="Your next\nhome game.",
        subtitle="Subscribe-once calendars for\nWNBA, NWSL & PWHL",
        footer="nexthomegame.com",
    )
    for slug in LEAGUE_GLYPHS:
        name = LEAGUE_NAMES[slug]
        files[f"og-image-{slug}.svg"] = og_image_svg(
            highlights=[(1, 3, GLYPHS[slug])],
            title=f"Your next\n{name} home game.",
            subtitle="One calendar, subscribe once,\nupdated nightly",
            footer="nexthomegame.com",
        )
    return files


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    svgs = build_svgs()
    for name, content in svgs.items():
        (ASSETS / name).write_text(content, encoding="utf-8")
        print(f"wrote {ASSETS / name}")

    renders = [
        ("favicon.svg", "favicon-32.png", 32, 32),
        ("favicon.svg", "apple-touch-icon.png", 180, 180),
        ("og-image.svg", "og-image.png", 1200, 630),
    ]
    for slug in LEAGUE_GLYPHS:
        renders.append((f"og-image-{slug}.svg", f"og-image-{slug}.png", 1200, 630))

    rsvg_convert = shutil.which("rsvg-convert")
    if rsvg_convert is None:
        raise SystemExit("rsvg-convert not found on PATH (brew install librsvg / apt install librsvg2-bin)")
    for src, out, w, h in renders:
        src_path, out_path = ASSETS / src, ASSETS / out
        subprocess.run(
            [rsvg_convert, "--width", str(w), "--height", str(h), str(src_path), "--output", str(out_path)],
            check=True,
        )
        print(f"rendered {out_path} ({w}x{h})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
