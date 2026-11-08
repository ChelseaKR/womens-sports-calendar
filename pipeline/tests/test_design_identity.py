"""The "Floodlight" identity (DECISIONS 0035): the palette clears WCAG AA in
both color schemes, lime stays off text, every page carries the same header
(a visible mark and two site links), and the home page lists the leagues
before the all-games feed, under the anchor the header links to.

Contrast is computed from the tokens in site.STYLE_CSS itself, so a later
token edit that drops below AA fails here, not in a browser months later.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

import pytest

from wsc_pipeline import site

from .fixture_site import build_fixture_site

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def _tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-f]{6});", block))


def _schemes() -> dict[str, dict[str, str]]:
    css = site.STYLE_CSS
    root = css[css.index(":root {") : css.index("}", css.index(":root {"))]
    dark_start = css.index("@media (prefers-color-scheme: dark)")
    dark = css[dark_start : css.index("\n}\n", dark_start)]
    light = _tokens(root)
    return {"light": light, "dark": {**light, **_tokens(dark)}}


def _luminance(hex_color: str) -> float:
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# (foreground, background, minimum): text pairs need 4.5:1, the subscribe
# buttons' outline against the box it sits on 3:1 (WCAG 1.4.11).
TEXT_PAIRS = [
    ("ink", "bg"),
    ("ink", "surface"),
    ("muted", "bg"),
    ("muted", "surface"),
    ("link", "bg"),
    ("link", "surface"),
    ("link-visited", "bg"),
    ("link-visited", "surface"),
    ("on-chrome-fg", "chrome"),
    ("on-chrome-muted", "chrome"),
    ("on-chrome-dim", "chrome"),
    ("on-chrome-link", "chrome"),
    ("on-chrome-link-visited", "chrome"),
    ("chrome", "hi"),
]
NON_TEXT_PAIRS = [
    ("cta-border", "surface"),
    ("focus", "bg"),
    ("on-chrome-focus", "chrome"),
]


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_every_text_pair_clears_aa(scheme: str):
    tokens = _schemes()[scheme]
    low = {
        f"{fg} on {bg}": round(contrast(tokens[fg], tokens[bg]), 2)
        for fg, bg in TEXT_PAIRS
        if contrast(tokens[fg], tokens[bg]) < 4.5
    }
    assert not low, low


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_outlines_and_focus_rings_clear_three_to_one(scheme: str):
    tokens = _schemes()[scheme]
    low = {
        f"{fg} on {bg}": round(contrast(tokens[fg], tokens[bg]), 2)
        for fg, bg in NON_TEXT_PAIRS
        if contrast(tokens[fg], tokens[bg]) < 3
    }
    assert not low, low


def test_control_a_washed_out_muted_fails_the_contrast_check():
    tokens = dict(_schemes()["light"], muted="#a8a3b5")
    assert contrast(tokens["muted"], tokens["bg"]) < 4.5


def test_the_brand_constants_do_not_change_in_dark_mode():
    light, dark = _schemes()["light"], _schemes()["dark"]
    assert (light["chrome"], light["hi"]) == ("#16131d", "#d4f24a")
    assert (dark["chrome"], dark["hi"]) == (light["chrome"], light["hi"])


def test_lime_is_never_a_text_color_and_never_a_link_color():
    """Lime means "a real next game"; as text on paper it is 1.27:1."""
    css = site.STYLE_CSS
    assert not re.search(r"(?<![-\w])color:\s*var\(--hi\)", css)
    for scheme in _schemes().values():
        assert scheme["hi"] not in {scheme["link"], scheme["on-chrome-link"], scheme["ink"]}


def test_a_plain_link_in_the_black_hero_takes_the_on_chrome_colors():
    """The empty hero's "check the seller" link sat ink-on-chrome (about 1:1)
    before 0035. The page's own link color is the hero's color in light mode,
    so the hero must override it."""
    css = site.STYLE_CSS
    tokens = _schemes()["light"]
    assert contrast(tokens["link"], tokens["chrome"]) < 1.5  # why the override is needed
    assert ".next-game a:not(.next-game-cta) { color: var(--on-chrome-link); }" in css
    assert ".next-game a:not(.next-game-cta):visited { color: var(--on-chrome-link-visited); }" in css


def test_theme_color_and_the_mark_use_the_chrome():
    chrome = _schemes()["light"]["chrome"]
    page = site.render_not_found(leagues=[], base_url="https://nexthomegame.com")
    assert f'<meta name="theme-color" content="{chrome}">' in page
    favicon = (ASSETS / "favicon.svg").read_text(encoding="utf-8")
    assert chrome in favicon and _schemes()["light"]["hi"] in favicon
    # Self-contained: nothing for the browser to fetch, no embedded image.
    assert "href" not in favicon and "<image" not in favicon


class _Header(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.links: list[str] = []
        self.brand_img = False
        self.ids: list[str] = []
        self.order: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if a.get("id"):
            self.ids.append(a["id"] or "")
        cls = a.get("class") or ""
        if "league-strip" in cls or "all-games-feed" in cls:
            self.order.append(cls)
        if tag == "header" and cls == "site-header":
            self.depth = 1
        elif self.depth and tag == "a":
            self.links.append(a.get("href") or "")
        elif self.depth and tag == "img" and "brand-mark" in cls:
            self.brand_img = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "header":
            self.depth = 0


def _parse(html: str) -> _Header:
    parser = _Header()
    parser.feed(html)
    return parser


@pytest.fixture(scope="module")
def pages(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    out = tmp_path_factory.mktemp("identity") / "dist"
    build_fixture_site(out, now=datetime(2026, 9, 18, 8, 30, tzinfo=UTC))
    return {
        path.relative_to(out).as_posix(): path.read_text(encoding="utf-8")
        for path in out.rglob("*.html")
        if 'http-equiv="refresh"' not in path.read_text(encoding="utf-8")
    }


def test_every_page_has_the_same_header(pages: dict[str, str]):
    assert len(pages) > 40
    for name, html in pages.items():
        header = _parse(html)
        assert header.links == ["/", "/#leagues", "/schedule/", "/help/"], name
        assert header.brand_img, name
        assert html.count(site.SITE_NAV) == 1, name


def test_the_header_leagues_link_has_a_target(pages: dict[str, str]):
    assert "leagues" in _parse(pages["index.html"]).ids


def test_the_home_page_lists_the_leagues_before_the_all_games_feed(pages: dict[str, str]):
    assert _parse(pages["index.html"]).order == ["league-strip", "all-games-feed"]


# The Big Shoulders faces never swap in after first paint. With
# `font-display: swap`, a runner without Arial Narrow (CI's Linux, most
# Android phones) paints the header in a much wider fallback, the wordmark
# and the two header links wrap onto a second line, and when the webfont
# arrives the header drops back to one line and moves the whole page: CLS
# 0.261 on every Lighthouse page in CI (0035). `optional` keeps whichever
# face is ready at first paint, and both faces are preloaded so it is
# normally the webfont.
def _font_faces(css: str) -> dict[str, str]:
    faces = re.findall(r"@font-face \{(.*?)\}", css, flags=re.S)
    return {re.search(r'font-family: "([^"]+)"', f).group(1): f for f in faces}


def _display_faces_problems(css: str, head: str) -> list[str]:
    problems = []
    faces = _font_faces(css)
    for family, file in (
        ("Big Shoulders Display", "big-shoulders-display-latin.woff2"),
        ("Big Shoulders Text", "big-shoulders-text-latin.woff2"),
    ):
        if "font-display: optional;" not in faces.get(family, ""):
            problems.append(f"{family} is not font-display: optional")
        if f'<link rel="preload" href="/fonts/{file}" as="font"' not in head:
            problems.append(f"{file} is not preloaded")
    return problems


def _head() -> str:
    page = site._base(
        title="t", description="d", canonical_url="https://example.test/", base_url="https://example.test", body=""
    )
    return page[: page.index("</head>")]


def test_display_faces_cannot_shift_the_layout() -> None:
    assert _display_faces_problems(site.STYLE_CSS, _head()) == []


def test_display_faces_control_swap_or_missing_preload_fails() -> None:
    swapped = site.STYLE_CSS.replace("font-display: optional;", "font-display: swap;")
    assert _display_faces_problems(swapped, _head()) != []
    unpreloaded = _head().replace("big-shoulders-text-latin.woff2", "nothing.woff2")
    assert _display_faces_problems(site.STYLE_CSS, unpreloaded) == ["big-shoulders-text-latin.woff2 is not preloaded"]
