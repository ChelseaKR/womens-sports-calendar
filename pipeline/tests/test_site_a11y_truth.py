"""The games table's scroll box, the freshness line and the table's ticket
links (2026-11-05 site audit), checked on rendered pages."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from wsc_pipeline import site

from .test_site_html import _pages


@pytest.mark.parametrize(
    ("instant", "shown"),
    [
        # 08:25 UTC in November is 12:25 AM Pacific Standard Time, the same day.
        (datetime(2026, 11, 5, 8, 25, tzinfo=UTC), "Thursday, Nov. 5, 2026, 12:25 AM PT"),
        # 07:05 UTC in July is 12:05 AM PDT; AP spells out July.
        (datetime(2026, 7, 2, 7, 5, tzinfo=UTC), "Thursday, July 2, 2026, 12:05 AM PT"),
        # 03:00 UTC is still the previous evening in California; AP's "Sept."
        (datetime(2026, 9, 18, 3, 0, tzinfo=UTC), "Thursday, Sept. 17, 2026, 8:00 PM PT"),
        (datetime(2026, 3, 9, 19, 30, tzinfo=UTC), "Monday, March 9, 2026, 12:30 PM PT"),
    ],
)
def test_the_freshness_stamp_is_us_order_in_pacific_time(instant, shown):
    assert site._pacific_stamp(instant) == shown


def test_the_freshness_line_keeps_the_utc_datetime_attribute():
    note = site._freshness_note({"fetched": True, "fetched_at": "2026-11-05T08:25:00+00:00"})
    assert '<time datetime="2026-11-05T08:25:00+00:00">Thursday, Nov. 5, 2026, 12:25 AM PT</time>' in note
    assert "UTC" not in note and "5 November" not in note


@pytest.mark.parametrize("name", ["league", "team"])
def test_the_scroll_box_is_a_focusable_region_named_by_the_caption(name):
    html = _pages()[name]
    wraps = re.findall(r'<div class="games-table-wrap"[^>]*>', html)
    assert wraps == ['<div class="games-table-wrap" role="region" tabindex="0" aria-labelledby="games-caption">']
    assert html.count('id="games-caption"') == 1
    assert re.search(r'<caption id="games-caption" class="sr-caption">Upcoming [^<]+ games', html)
    assert ".games-table-wrap:focus-visible" in site.STYLE_CSS


def test_a_table_ticket_link_is_short_and_names_the_seller_and_the_game():
    html = _pages()["league"]
    rows = re.findall(r"<tbody>.*?</tbody>", html, re.S)
    assert rows
    links = re.findall(r"<a [^>]*>(.*?)</a>", rows[0])
    tickets = [t for t in links if t.startswith("Tickets")]
    assert tickets
    for text in tickets:
        visible = re.sub(r'<span class="sr-only">.*?</span>', "", text)
        # The seller stays visible (DECISIONS 0013, 0018): Ticketmaster, or the
        # home team's own seller where one is known.
        assert re.fullmatch(r"Tickets \((Ticketmaster|Jump|AXS|SeatGeek)\)", visible), visible
        assert re.fullmatch(r'Tickets \([^)]+\)<span class="sr-only"> for .+ vs .+ on [^<]+</span>', text), text
    assert "Buy tickets for" not in rows[0]
    assert ".sr-only" in site.STYLE_CSS


def test_the_hero_keeps_the_full_sentence():
    html = _pages()["team"]
    hero = re.search(r'<section class="next-game".*?</section>', html, re.S)
    assert hero is not None
    assert re.search(r'class="next-game-cta"[^>]*>Buy tickets for .+ from [^<]+</a>', hero.group(0))
