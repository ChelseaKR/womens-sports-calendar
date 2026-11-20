"""Fixes from the 2026-11-20 accessibility conformance review
(docs/a11y/ACR.md): what a screen reader user hears, and instructions that
name a control instead of describing its shape."""

from __future__ import annotations

import re

from wsc_pipeline import site
from wsc_pipeline.config import LEAGUES, LEAGUES_EXAMINED_NOT_INCLUDED

BASE = "https://nexthomegame.com"


def test_other_calendar_apps_steps_name_googles_control_rather_than_its_shape() -> None:
    """WCAG 1.3.3: "select the + icon" relies on the icon's shape. Google
    labels the control "Add other calendars", which is what a screen reader
    announces and what the calendar help page already says."""
    html = site._other_apps_block(ics_https_url=f"{BASE}/ics/wnba/las-vegas-aces.ics")
    assert "+ icon" not in html
    assert "select Add other calendars (+) &rsaquo; From URL" in html


def test_each_league_row_link_name_keeps_a_space_between_league_and_count() -> None:
    """The two spans sit side by side in a flex row, so no space shows; with
    none in the markup either, a screen reader can run them together
    ("WNBA8 upcoming games"). A space between them renders nothing in flex
    layout and keeps the link's name "WNBA 8 upcoming games" (WCAG 2.4.4,
    4.1.2)."""
    leagues = [{"slug": lg.slug, "name": lg.name, "games_count": 8} for lg in LEAGUES]
    html = site.render_index(leagues=leagues, not_included=list(LEAGUES_EXAMINED_NOT_INCLUDED), base_url=BASE)
    rows = re.findall(r'<a class="league-row-link"[^>]*>(.*?)</a>', html)
    assert len(rows) == len(LEAGUES)
    for row in rows:
        assert '</span> <span class="league-row-count">' in row, row


def _rule(selector_fragment: str) -> str:
    """The declarations of the first STYLE_CSS rule whose selector list
    contains `selector_fragment`."""
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", site.STYLE_CSS):
        if selector_fragment in selectors:
            return body
    raise AssertionError(f"no rule for {selector_fragment}")


def test_home_page_lines_can_wrap_under_wcag_text_spacing() -> None:
    """WCAG 1.4.12 at 320 CSS px: with the criterion's letter and word
    spacing, the home page's all-games feed address and the long NCAA league
    names beside their unbreakable game count, and a run of names joined by
    slashes in the not-included list pushed the page to 367px. Each may now
    break inside a word, which happens only when a word cannot fit.
    The browser half is the text-spacing check in
    scripts/a11y_browser_checks.mjs, run by `make a11y`."""
    assert "overflow-wrap: anywhere" in _rule(".all-games-feed p a")
    main_rules = [b for sel, b in re.findall(r"([^{}]+)\{([^{}]*)\}", site.STYLE_CSS) if sel.strip().endswith("main")]
    assert any("overflow-wrap: break-word" in b for b in main_rules)
    name = _rule(".league-row-name")
    assert "overflow-wrap: anywhere" in name
    assert "min-width: 0" in name
