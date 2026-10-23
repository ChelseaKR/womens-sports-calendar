"""Team-page block order: the next home game above the subscribe block, behind
one build-time constant (site.TEAM_PAGE_NEXT_GAME_FIRST), off by default.

- Off (as shipped): the page is byte-identical to what main rendered. The
  goldens in tests/golden/team_order_*.html were rendered by main's
  render_team before this constant existed.
- On: the "Next home game" section comes before the subscribe section, and
  the page is otherwise the same text (same lines, same links, same rel
  attributes, same "Paid link" labels). Only a page with a next home game
  changes order; a page with none keeps the subscribe block first.
- The calendar feeds and data files do not depend on the constant.

Pages are read with html.parser, never a regex over markup.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

import pytest

from wsc_pipeline import site
from wsc_pipeline.config import LEAGUES
from wsc_pipeline.normalize import normalize_event
from wsc_pipeline.site import render_team
from wsc_pipeline.site_data import team_data

from .conftest import make_raw_event, set_affiliate_links
from .fixture_site import build_fixture_site

GOLDEN = Path(__file__).parent / "golden"
BASE = "https://nexthomegame.com"
SEATGEEK_LINK = "https://seatgeek.pxf.io/c/1234567/890123/45678"
FANATICS_LINK = "https://fanatics.93n6tx.net/c/1234567/612734/9663"

NWSL = next(lg for lg in LEAGUES if lg.slug == "nwsl")
THORNS = next(t for t in NWSL.teams if t.slug == "portland-thorns")
SCENARIOS = ("plain", "paid", "away_only", "no_games", "not_fetched")


def _game(event_id: str, name: str, **kw):
    raw = make_raw_event(event_id=event_id, name=name, url=f"https://www.ticketmaster.com/event/{event_id}", **kw)
    game = normalize_event(raw, league_slug="nwsl", tracked_team_slug=THORNS.slug, tracked_team_name=THORNS.name)
    assert game is not None
    return game


def _home():
    return _game(
        "T1",
        "Portland Thorns FC vs Seattle Reign FC",
        venue_name="Providence Park",
        venue_city="Portland",
        venue_state="OR",
    )


def _away():
    return _game(
        "T2",
        "Angel City FC vs Portland Thorns FC",
        date_time="2026-06-20T23:00:00Z",
        local_date="2026-06-20",
    )


def page(scenario: str, monkeypatch: pytest.MonkeyPatch | None = None) -> str:
    """The Thorns team page for one scenario. 'paid' needs a monkeypatch to
    set the owner's Impact links the way a deploy would."""
    if scenario == "paid":
        assert monkeypatch is not None
        set_affiliate_links(monkeypatch, seatgeek=SEATGEEK_LINK, fanatics=FANATICS_LINK)
    games = {
        "plain": [_home(), _away()],
        "paid": [_home(), _away()],
        "away_only": [_away()],
        "no_games": [],
        "not_fetched": [],
    }[scenario]
    payload = team_data(THORNS, NWSL, games)
    if scenario == "not_fetched":
        payload["fetched"] = False
    return render_team(team=payload, base_url=BASE, paid_links=scenario == "paid")


class _Order(HTMLParser):
    """Heading ids of the two blocks, in document order, plus every link's
    (href, rel, text) and the number of "Paid link" labels."""

    def __init__(self) -> None:
        super().__init__()
        self.section_ids: list[str] = []
        self.links: list[tuple[str, str, str]] = []
        self.labels = 0
        self._open: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "h2" and a.get("id") in ("subscribe-heading", "next-game-heading"):
            self.section_ids.append(a["id"] or "")
        if tag == "span" and a.get("class") == "paid-link":
            self.labels += 1
        if tag == "a":
            self._open = [a.get("href") or "", a.get("rel") or "", ""]

    def handle_data(self, data: str) -> None:
        if self._open is not None:
            self._open[2] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._open is not None:
            self.links.append((self._open[0], self._open[1], self._open[2]))
            self._open = None


def _read(html: str) -> _Order:
    parsed = _Order()
    parsed.feed(html)
    return parsed


def hero_comes_first(html: str) -> bool:
    return _read(html).section_ids == ["next-game-heading", "subscribe-heading"]


def subscribe_comes_first(html: str) -> bool:
    return _read(html).section_ids == ["subscribe-heading", "next-game-heading"]


@pytest.fixture
def order_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(site, "TEAM_PAGE_NEXT_GAME_FIRST", True)


def test_the_constant_ships_off():
    assert site.TEAM_PAGE_NEXT_GAME_FIRST is False


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_off_is_byte_identical_to_what_main_rendered(scenario: str, monkeypatch: pytest.MonkeyPatch):
    golden = (GOLDEN / f"team_order_{scenario}.html").read_bytes()
    assert page(scenario, monkeypatch).encode() == golden


def test_off_pages_have_the_subscribe_block_first():
    assert subscribe_comes_first(page("plain"))


def test_on_puts_the_next_home_game_and_its_ticket_link_above_the_subscribe_block(
    order_on: None, monkeypatch: pytest.MonkeyPatch
):
    html = page("plain", monkeypatch)
    assert hero_comes_first(html)
    links = _read(html).links
    ticket = next(i for i, link in enumerate(links) if link[2].startswith("Buy tickets"))
    first_subscribe = next(i for i, link in enumerate(links) if link[2] == "Add to Google Calendar")
    assert ticket < first_subscribe


@pytest.mark.parametrize("scenario", ["plain", "paid"])
def test_on_changes_nothing_but_the_order(scenario: str, monkeypatch: pytest.MonkeyPatch):
    off = page(scenario, monkeypatch)
    monkeypatch.setattr(site, "TEAM_PAGE_NEXT_GAME_FIRST", True)
    on = page(scenario, monkeypatch)
    assert on != off
    assert sorted(on.splitlines()) == sorted(off.splitlines())
    assert sorted(_read(on).links) == sorted(_read(off).links)


def test_on_keeps_every_paid_link_labelled_and_sponsored(monkeypatch: pytest.MonkeyPatch):
    off = _read(page("paid", monkeypatch))
    monkeypatch.setattr(site, "TEAM_PAGE_NEXT_GAME_FIRST", True)
    html = page("paid", monkeypatch)
    on = _read(html)
    assert hero_comes_first(html)
    paid = [link for link in on.links if "sponsored" in link[1].split()]
    assert len(paid) >= 3  # the hero and the home row buy links, and the team shop
    assert all(link[1].split() == ["sponsored", "noopener"] for link in paid)
    assert on.labels == off.labels == len(paid)
    # Every paid link is one the page already labelled; none is new.
    assert sorted(paid) == sorted(link for link in off.links if "sponsored" in link[1].split())


@pytest.mark.parametrize("scenario", ["away_only", "no_games", "not_fetched"])
def test_on_leaves_a_page_without_a_next_home_game_exactly_as_it_was(scenario: str, monkeypatch: pytest.MonkeyPatch):
    off = page(scenario, monkeypatch)
    monkeypatch.setattr(site, "TEAM_PAGE_NEXT_GAME_FIRST", True)
    assert page(scenario, monkeypatch) == off
    assert subscribe_comes_first(off)


def _without_dtstamps(raw: bytes) -> bytes:
    # Each build stamps every event with its own fetch time (see build._write_ics),
    # so two builds a second apart differ in exactly those lines and nowhere else.
    return re.sub(rb"DTSTAMP:\d{8}T\d{6}Z", b"DTSTAMP:X", raw)


def test_the_constant_does_not_reach_the_feeds_or_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    off_dir, on_dir = tmp_path / "off", tmp_path / "on"
    # One fixed fetch time for both builds: with the wall clock, a second ticking
    # over between them changed fetched_at in the data files and failed this test.
    built_at = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    build_fixture_site(off_dir, now=built_at)
    monkeypatch.setattr(site, "TEAM_PAGE_NEXT_GAME_FIRST", True)
    build_fixture_site(on_dir, now=built_at)
    for sub in ("ics", "data"):
        off_files = sorted(p.relative_to(off_dir) for p in (off_dir / sub).rglob("*") if p.is_file())
        on_files = sorted(p.relative_to(on_dir) for p in (on_dir / sub).rglob("*") if p.is_file())
        assert off_files == on_files and off_files
        for rel in off_files:
            if rel.name == "site.json":
                continue  # carries build timing, if anything
            assert _without_dtstamps((off_dir / rel).read_bytes()) == _without_dtstamps((on_dir / rel).read_bytes()), (
                rel
            )
    # ...while the pages really did change, so the comparison above had teeth.
    team = Path("wnba/las-vegas-aces/index.html")
    assert (off_dir / team).read_bytes() != (on_dir / team).read_bytes()
    assert hero_comes_first((on_dir / team).read_text())


def test_no_feed_carries_a_paid_marker_when_on(order_on: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    set_affiliate_links(monkeypatch, seatgeek=SEATGEEK_LINK, fanatics=FANATICS_LINK)
    build_fixture_site(tmp_path)
    for feed in (tmp_path / "ics").rglob("*.ics"):
        text = feed.read_text()
        assert "pxf.io" not in text and "93n6tx" not in text and "sponsored" not in text.lower(), feed


# ---- negative controls: each sabotages the build, asserts it landed, and
# asserts the check then fails ------------------------------------------------


def test_control_the_order_check_fails_when_the_order_does_not_change(monkeypatch: pytest.MonkeyPatch):
    off = page("plain")
    # Sabotage: the constant is turned on, but the renderer ignores it.
    monkeypatch.setattr(site, "TEAM_PAGE_NEXT_GAME_FIRST", True)
    monkeypatch.setattr(site, "_has_next_home_game", lambda team: False)
    ignored = page("plain")
    assert ignored == off  # the sabotage applied: no reorder happened
    assert not hero_comes_first(ignored)


def test_control_the_golden_comparison_fails_when_the_default_output_drifts(monkeypatch: pytest.MonkeyPatch):
    golden = (GOLDEN / "team_order_plain.html").read_bytes()
    real = site._next_game_hero
    monkeypatch.setattr(site, "_next_game_hero", lambda team: real(team) + " ")
    drifted = page("plain").encode()
    assert b"</section>\n \n" in drifted  # the sabotage applied
    assert drifted != golden


def test_control_the_paid_check_fails_when_a_paid_link_loses_its_label(monkeypatch: pytest.MonkeyPatch):
    html = page("paid", monkeypatch)
    sabotaged = html.replace('<span class="paid-link">Paid link</span>', "", 1)
    assert sabotaged != html  # the sabotage applied
    assert _read(sabotaged).labels != _read(html).labels
