"""The home page links the all-leagues feed (ics/all.ics, #36), says what it
is, and uses the feed's own wording for a game with no announced start time.

Parsed with html.parser, never a regex over markup.
"""

from __future__ import annotations

from html.parser import HTMLParser

import pytest

from wsc_pipeline import ics, site
from wsc_pipeline.config import LEAGUES, LEAGUES_EXAMINED_NOT_INCLUDED

BASE = "https://nexthomegame.com"
FEED = f"{BASE}/ics/all.ics"


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.scripts = 0
        self.script_types: list[str] = []
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.links.append(dict(attrs).get("href") or "")
        if tag == "script":
            self.scripts += 1
            self.script_types.append(dict(attrs).get("type") or "")

    def handle_data(self, data: str) -> None:
        self.text.append(data)


def _parse(html: str) -> _Page:
    page = _Page()
    page.feed(html)
    return page


def _index(ga4_id: str | None = None) -> str:
    leagues = [{"slug": lg.slug, "name": lg.name, "games_count": 2} for lg in LEAGUES]
    return site.render_index(
        leagues=leagues, not_included=list(LEAGUES_EXAMINED_NOT_INCLUDED), base_url=BASE, ga4_id=ga4_id
    )


def _problems(html: str) -> list[str]:
    """What the home page must have; empty when it does."""
    page = _parse(html)
    text = " ".join(" ".join(page.text).split())
    out = []
    if FEED not in page.links:
        out.append("no https link to ics/all.ics")
    if FEED.replace("https://", "webcal://") not in page.links:
        out.append("no webcal link to ics/all.ics")
    if "every game listed in every league" not in text:
        out.append("does not say what the file is")
    if ics.TIME_TBA_NOTE not in text or ics.TIME_TBA_SUFFIX.strip() not in text:
        out.append("does not use the feed's own time-TBA wording")
    return out


def test_home_page_links_the_all_leagues_feed_and_says_what_it_is():
    assert _problems(_index()) == []


def test_the_link_is_a_plain_calendar_link_with_no_added_script_or_tracking_parameter():
    page = _parse(_index())
    # The only script on a page without analytics is the JSON-LD data block.
    assert page.script_types == ["application/ld+json"]
    feed_links = [h for h in page.links if "all.ics" in h]
    assert sorted(feed_links) == sorted([FEED, FEED.replace("https://", "webcal://")])
    # analytics.py counts calendar_subscribe on a webcal: link or a path
    # ending .ics, so no event name or listener is added for this link.
    assert all(h.endswith("/ics/all.ics") for h in feed_links)


def test_the_ga4_loader_and_its_event_names_are_unchanged_by_the_new_link(monkeypatch: pytest.MonkeyPatch):
    with_block = _index("G-TEST123456")
    monkeypatch.setattr(site, "_all_games_feed_block", lambda base_url: "")
    without_block = _index("G-TEST123456")
    assert with_block != without_block  # the block was removed
    assert _parse(with_block).script_types == _parse(without_block).script_types
    assert "calendar_subscribe" in with_block


def test_negative_control_a_page_without_the_block_fails_the_check(monkeypatch: pytest.MonkeyPatch):
    good = _index()
    monkeypatch.setattr(site, "_all_games_feed_block", lambda base_url: "")
    sabotaged = _index()
    assert sabotaged != good  # the sabotage applied
    assert "all.ics" not in sabotaged
    assert _problems(sabotaged) != []


def test_negative_control_wording_that_drifts_from_the_feed_fails_the_check(monkeypatch: pytest.MonkeyPatch):
    good = _index()
    # Only the page's copy of the note changes; the check still reads the
    # feed's real ics.TIME_TBA_NOTE.
    monkeypatch.setattr(site, "TIME_TBA_NOTE", "Time TBA: something else.")
    drifted = _index()
    assert drifted != good  # the sabotage applied
    assert "something else" in drifted
    assert "does not use the feed's own time-TBA wording" in _problems(drifted)
