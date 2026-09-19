"""Canceled, postponed and rescheduled games in the .ics feeds.

A canceled game used to be written as an ordinary confirmed event, so a
subscriber's calendar kept it until Ticketmaster dropped the listing. These
tests pin what the feed says now, that the page and the feed agree (the
validator fails on a feed that lacks the status its page shows, with planted
failures), that no UID moves, and that the bytes are still valid RFC 5545
according to a reader that does not use icalendar (tests/rfc5545.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wsc_pipeline import build as build_module
from wsc_pipeline import validate_ics
from wsc_pipeline.config import LEAGUES
from wsc_pipeline.ics import FEED_STATUS, league_calendar, make_uid
from wsc_pipeline.normalize import normalize_event
from wsc_pipeline.site_data import NOTABLE_STATUSES

from . import rfc5545
from .conftest import BUILD_TIME, make_raw_event
from .fixture_site import build_fixture_site

WNBA = LEAGUES[0]
TEAM_A = WNBA.teams[0]


def _game(event_id: str, status: str | None, **kwargs):
    raw = make_raw_event(event_id=event_id, status=status, **kwargs)
    game = normalize_event(
        raw, league_slug="wnba", tracked_team_slug="indiana-fever", tracked_team_name="Indiana Fever"
    )
    assert game is not None
    return game


def _vevent(game):
    cal = rfc5545.parse(_calendar_bytes([game]))
    (vevent,) = cal.walk("VEVENT")
    return vevent


def _calendar_bytes(games) -> bytes:
    return league_calendar("wnba", "WNBA", games, base_url="https://nexthomegame.com", dtstamp=BUILD_TIME).to_ical()


def _text(prop) -> str:
    return rfc5545.unescape_text(prop.value)


def test_a_canceled_game_is_marked_in_the_machine_readable_status_and_the_visible_summary():
    vevent = _vevent(_game("C1", "cancelled"))
    assert vevent.first("STATUS").value == "CANCELLED"
    assert _text(vevent.first("SUMMARY")) == "Canceled: Indiana Fever vs New York Liberty"
    first_line = _text(vevent.first("DESCRIPTION")).split("\n")[0]
    assert first_line == "Canceled: Ticketmaster lists this game as canceled."


def test_the_american_spelling_of_the_status_code_is_treated_the_same():
    vevent = _vevent(_game("C2", "canceled"))
    assert vevent.first("STATUS").value == "CANCELLED"


def test_a_postponed_game_is_tentative_and_does_not_look_confirmed_at_its_old_time():
    vevent = _vevent(_game("P1", "postponed"))
    assert vevent.first("STATUS").value == "TENTATIVE"
    assert _text(vevent.first("SUMMARY")) == "Postponed: Indiana Fever vs New York Liberty"
    description = _text(vevent.first("DESCRIPTION"))
    assert description.startswith("Postponed: Ticketmaster lists this game as postponed.")
    assert "original" in description.split("\n")[0]


def test_a_rescheduled_game_stays_an_ordinary_event_and_says_so_in_its_description():
    vevent = _vevent(_game("R1", "rescheduled"))
    assert vevent.first("STATUS") is None
    assert _text(vevent.first("SUMMARY")) == "Indiana Fever vs New York Liberty"
    assert _text(vevent.first("DESCRIPTION")).split("\n")[0].startswith("Rescheduled: ")


@pytest.mark.parametrize("status", [None, "onsale", "offsale"])
def test_a_game_with_no_notable_status_is_byte_for_byte_what_it_was(status):
    """No STATUS, no marker, and a DESCRIPTION that still opens with the
    league line: nothing changes for the games that are simply going ahead."""
    vevent = _vevent(_game("N1", status))
    assert vevent.first("STATUS") is None
    assert _text(vevent.first("SUMMARY")) == "Indiana Fever vs New York Liberty"
    assert _text(vevent.first("DESCRIPTION")).split("\n")[0] == "League: WNBA"


@pytest.mark.parametrize("status", [None, "cancelled", "postponed", "rescheduled", "onsale"])
def test_the_uid_is_the_same_whatever_the_status(status):
    """Subscribers' calendars key on the UID: a status must update the event
    they already hold, never add a second one or drop the first."""
    game = _game("KEEP-1", status)
    raw = _calendar_bytes([game])
    uid_lines = [line for line in raw.split(b"\r\n") if line.startswith(b"UID:")]
    assert uid_lines == [b"UID:tm-KEEP-1@womens-sports-calendar.invalid"]
    assert make_uid("KEEP-1") == "tm-KEEP-1@womens-sports-calendar.invalid"


def test_every_page_status_word_has_a_feed_rule_and_only_those():
    """A new word in the page's table without a feed rule would publish a
    game the page marks but the feed does not."""
    assert set(NOTABLE_STATUSES.values()) == set(FEED_STATUS)


def test_the_feed_is_still_valid_rfc5545_with_statuses_commas_and_multibyte_names():
    """Read by tests/rfc5545.py, which does not use icalendar: CRLF, folded
    at 75 octets without splitting a character, TEXT escaped, one of each
    once-only property."""
    long_name = "Équipe Été, Réseau; Ünïcode \\ back\\slash — " + "Ñandú " * 30 + "vs Rivals"
    games = [
        _game("V1", "cancelled", name=long_name),
        _game("V2", "postponed", name="Indiana Fever vs New York Liberty, Game 2; Finals"),
        _game("V3", "rescheduled"),
        _game("V4", None),
    ]
    raw = _calendar_bytes(games)
    assert max(len(line) for line in raw.split(b"\r\n")) <= 75
    assert b"\r\n " in raw  # something really was folded, so the fold checks examined it
    cal = rfc5545.parse(raw)
    vevents = {v.first("UID").value: v for v in cal.walk("VEVENT")}
    assert set(vevents) == {make_uid(f"V{i}") for i in (1, 2, 3, 4)}
    assert _text(vevents[make_uid("V1")].first("SUMMARY")) == "Canceled: " + long_name
    assert vevents[make_uid("V2")].first("STATUS").value == "TENTATIVE"


def test_a_calendar_built_without_a_duration_writes_no_end_time():
    """Only a sport with a known game length gets an estimated end
    (test_ics_end_time.py); nothing else is ever guessed."""
    cal = rfc5545.parse(_calendar_bytes([_game("E1", "cancelled"), _game("E2", None)]))
    for vevent in cal.walk("VEVENT"):
        assert vevent.first("DTEND") is None and vevent.first("DURATION") is None


# --- the validator: a game the page marks must be marked in its feed --------


def _build_with_statuses(tmp_path: Path, monkeypatch) -> Path:
    def game(event_id: str, status: str | None, day: int):
        raw = make_raw_event(
            event_id=event_id,
            name=f"{TEAM_A.name} vs Visiting Team",
            status=status,
            date_time=f"2026-06-{day:02d}T23:00:00Z",
            local_date=f"2026-06-{day:02d}",
        )
        built = normalize_event(
            raw, league_slug=WNBA.slug, tracked_team_slug=TEAM_A.slug, tracked_team_name=TEAM_A.name
        )
        assert built is not None
        return built

    games = [
        game("S-CANCELLED", "cancelled", 15),
        game("S-POSTPONED", "postponed", 16),
        game("S-RESCHEDULED", "rescheduled", 17),
        game("S-PLAIN", None, 18),
    ]
    empty = {lg.slug: set() for lg in LEAGUES}
    monkeypatch.setattr(build_module, "fetch_all_games", lambda api_key: (games, empty, empty, 1, 1))
    out_dir = tmp_path / "dist"
    build_module.build(out_dir=out_dir, base_url="https://nexthomegame.com", api_key="fake-key", affiliate_id=None)
    return out_dir


def _feeds(dist: Path) -> list[Path]:
    return [dist / "ics" / f"{WNBA.slug}.ics", dist / "ics" / WNBA.slug / f"{TEAM_A.slug}.ics"]


def test_a_built_site_with_every_status_validates(tmp_path: Path, monkeypatch):
    dist = _build_with_statuses(tmp_path, monkeypatch)
    assert validate_ics.main([str(dist)]) == 0
    for feed in _feeds(dist):
        cal = rfc5545.parse(feed.read_bytes())
        by_uid = {v.first("UID").value: v for v in cal.walk("VEVENT")}
        assert by_uid[make_uid("S-CANCELLED")].first("STATUS").value == "CANCELLED"
        assert by_uid[make_uid("S-POSTPONED")].first("STATUS").value == "TENTATIVE"
        assert by_uid[make_uid("S-RESCHEDULED")].first("STATUS") is None
        assert by_uid[make_uid("S-PLAIN")].first("STATUS") is None


def _sabotage(feed: Path, old: bytes, new: bytes) -> None:
    before = feed.read_bytes()
    feed.write_bytes(before.replace(old, new))
    assert feed.read_bytes() != before, "the sabotage did not apply"


def _first_event_block(feed: Path, uid: str) -> bytes:
    raw = feed.read_bytes()
    start = raw.rindex(b"BEGIN:VEVENT", 0, raw.index(uid.encode()))
    return raw[start : raw.index(b"END:VEVENT", start)]


@pytest.mark.parametrize(
    "uid,old,new,match",
    [
        # the canceled game loses its STATUS: the failure this work exists to prevent
        ("S-CANCELLED", b"STATUS:CANCELLED\r\n", b"", "STATUS"),
        # ...or is confirmed instead
        ("S-CANCELLED", b"STATUS:CANCELLED\r\n", b"STATUS:CONFIRMED\r\n", "STATUS"),
        # the postponed game is written as cancelled
        ("S-POSTPONED", b"STATUS:TENTATIVE\r\n", b"STATUS:CANCELLED\r\n", "STATUS"),
        # a game the page does not mark claims to be canceled
        ("S-PLAIN", b"DTSTART", b"STATUS:CANCELLED\r\nDTSTART", "STATUS"),
        # the visible marker is gone from the summary
        ("S-CANCELLED", b"SUMMARY:Canceled: ", b"SUMMARY:", "SUMMARY"),
        # the rescheduled note is gone from the description
        ("S-RESCHEDULED", b"Rescheduled: Ticketmaster", b"Ticketmaster", "DESCRIPTION"),
    ],
)
def test_a_feed_that_lacks_the_status_its_page_shows_fails(tmp_path: Path, monkeypatch, uid, old, new, match):
    dist = _build_with_statuses(tmp_path, monkeypatch)
    feed = dist / "ics" / WNBA.slug / f"{TEAM_A.slug}.ics"
    block = _first_event_block(feed, make_uid(uid))
    assert old in block, "the planted failure would not land in the intended event"
    raw = feed.read_bytes()
    feed.write_bytes(raw.replace(block, block.replace(old, new, 1)))
    assert feed.read_bytes() != raw, "the sabotage did not apply"
    with pytest.raises(validate_ics.FeedError, match=match):
        validate_ics.validate_dist(dist)


def test_the_fixture_sites_canceled_game_is_checked_against_its_feed(tmp_path: Path):
    """`make validate-fixture-site` runs validate_ics on this site; its
    canceled home game (FX-CANCELLED) is in the feed and marked."""
    dist = tmp_path / "fixture"
    build_fixture_site(dist)
    assert validate_ics.main([str(dist)]) == 0
    feed = dist / "ics" / "wnba" / "las-vegas-aces.ics"
    block = _first_event_block(feed, make_uid("FX-CANCELLED"))
    assert b"STATUS:CANCELLED\r\n" in block
    assert b"SUMMARY:Canceled: Las Vegas Aces vs Los Angeles Sparks\r\n" in block
    # ...and the check has teeth on that same game.
    _sabotage(feed, b"STATUS:CANCELLED\r\n", b"")
    with pytest.raises(validate_ics.FeedError, match="STATUS"):
        validate_ics.validate_dist(dist)


def test_uids_across_the_fixture_site_are_exactly_the_ones_published_before_this_change(tmp_path: Path):
    """Subscribers' calendars key on these lines. golden/fixture_site_ics_uids.txt
    was captured from the feeds this pipeline wrote before statuses were
    carried (one `path<TAB>UID:` line per event per feed); the UID lines a
    build writes now must match it byte for byte."""
    dist = tmp_path / "fixture"
    build_fixture_site(dist)
    lines = []
    for feed in sorted((dist / "ics").rglob("*.ics")):
        for raw in feed.read_bytes().split(b"\r\n"):
            if raw.startswith(b"UID:"):
                lines.append(f"{feed.relative_to(dist).as_posix()}\t{raw.decode()}")
    golden = (Path(__file__).parent / "golden" / "fixture_site_ics_uids.txt").read_text(encoding="utf-8")
    assert "\n".join(lines) + "\n" == golden
    assert len(lines) == 17  # a build that wrote no events would compare equal to nothing
