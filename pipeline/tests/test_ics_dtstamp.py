"""DTSTAMP in the .ics feeds is the build's time, not the game's start time.

RFC 5545 section 3.8.7.2: for a calendar with METHOD:PUBLISH (these feeds),
DTSTAMP is when that copy of the calendar object was created. It used to be
the game's own start, which for a game next month is in the future, moves
when the game does, and goes backward when a game is moved earlier (a client
that orders copies by DTSTAMP could then keep the stale time). The build's
fetch time is passed in (ics.build_calendar never reads the clock), so these
tests pin it, and a given build is reproducible.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from wsc_pipeline import build as build_module
from wsc_pipeline import validate_ics
from wsc_pipeline.config import LEAGUES
from wsc_pipeline.ics import build_calendar, league_calendar, make_uid, team_calendar
from wsc_pipeline.normalize import normalize_event

from . import rfc5545
from .conftest import BUILD_TIME, make_raw_event
from .fixture_site import build_fixture_site

WNBA = LEAGUES[0]
TEAM_A = WNBA.teams[0]


def _game(event_id: str, *, date_time: str = "2026-06-15T23:00:00Z", local_date: str = "2026-06-15", **kwargs):
    raw = make_raw_event(event_id=event_id, date_time=date_time, local_date=local_date, **kwargs)
    game = normalize_event(raw, league_slug=WNBA.slug, tracked_team_slug=TEAM_A.slug, tracked_team_name=TEAM_A.name)
    assert game is not None
    return game


def _lines(raw: bytes, prefix: bytes) -> list[bytes]:
    return [line for line in raw.split(b"\r\n") if line.startswith(prefix)]


def test_dtstamp_is_the_build_time_not_the_games_start():
    raw = build_calendar([_game("D1")], cal_name="T", dtstamp=BUILD_TIME).to_ical()
    assert _lines(raw, b"DTSTAMP") == [b"DTSTAMP:20260601T083000Z"]
    # ...and the game's own start is unchanged, still its local time.
    assert _lines(raw, b"DTSTART;TZID=") == [b"DTSTART;TZID=America/Indiana/Indianapolis:20260615T190000"]


def test_moving_a_game_earlier_does_not_lower_its_dtstamp():
    """The same event, moved a week earlier between two builds: its DTSTAMP is
    the second build's time, later than the first's, so a client that keeps the
    copy with the later DTSTAMP keeps the new time."""
    first_build = BUILD_TIME
    second_build = BUILD_TIME + timedelta(days=1)
    before = build_calendar([_game("MOVE-1")], cal_name="T", dtstamp=first_build).to_ical()
    moved = _game("MOVE-1", date_time="2026-06-08T23:00:00Z", local_date="2026-06-08")
    after = build_calendar([moved], cal_name="T", dtstamp=second_build).to_ical()
    assert _lines(before, b"DTSTART;TZID=") != _lines(after, b"DTSTART;TZID=")  # it did move
    assert _lines(before, b"DTSTAMP") == [b"DTSTAMP:20260601T083000Z"]
    assert _lines(after, b"DTSTAMP") == [b"DTSTAMP:20260602T083000Z"]
    assert _lines(before, b"UID") == _lines(after, b"UID")


def test_every_event_of_one_build_shares_one_dtstamp():
    games = [_game("A", date_time="2026-06-15T23:00:00Z"), _game("B", date_time="2026-09-01T23:00:00Z")]
    cal = rfc5545.parse(build_calendar(games, cal_name="T", dtstamp=BUILD_TIME).to_ical())
    assert {v.first("DTSTAMP").value for v in cal.walk("VEVENT")} == {"20260601T083000Z"}


def test_the_same_build_time_gives_the_same_bytes():
    """Reproducible: nothing in the feed depends on when it is generated."""
    games = [_game("R1"), _game("R2", date_time="2026-06-20T23:00:00Z", local_date="2026-06-20")]
    first = league_calendar("wnba", "WNBA", games, base_url="https://nexthomegame.com", dtstamp=BUILD_TIME)
    second = league_calendar("wnba", "WNBA", games, base_url="https://nexthomegame.com", dtstamp=BUILD_TIME)
    assert first.to_ical() == second.to_ical()


def test_a_dtstamp_in_another_zone_is_written_as_the_same_utc_instant_in_whole_seconds():
    eastern = datetime(2026, 6, 1, 4, 30, 0, 999999, tzinfo=timezone(timedelta(hours=-4)))
    raw = build_calendar([_game("Z1")], cal_name="T", dtstamp=eastern).to_ical()
    assert _lines(raw, b"DTSTAMP") == [b"DTSTAMP:20260601T083000Z"]


def test_a_naive_dtstamp_is_refused_rather_than_guessed():
    with pytest.raises(ValueError, match="timezone-aware"):
        build_calendar([_game("N1")], cal_name="T", dtstamp=datetime(2026, 6, 1, 8, 30, 0))


def test_a_feed_with_events_and_no_dtstamp_is_refused_rather_than_stamped_with_a_guess():
    with pytest.raises(ValueError, match="needs dtstamp"):
        build_calendar([_game("M1")], cal_name="T")
    with pytest.raises(ValueError, match="needs dtstamp"):
        team_calendar(TEAM_A.slug, TEAM_A.name, [_game("M2")])


def test_a_feed_with_no_events_needs_no_dtstamp():
    """A build that fetched nothing writes empty calendars: no event, nothing
    to stamp."""
    cal = league_calendar("wnba", "WNBA", [], fetched=False, base_url="https://nexthomegame.com")
    assert cal.walk("VEVENT") == []


@pytest.mark.parametrize("status", [None, "cancelled", "postponed", "rescheduled"])
def test_the_uid_does_not_depend_on_the_dtstamp(status):
    a = build_calendar([_game("U1", status=status)], cal_name="T", dtstamp=BUILD_TIME).to_ical()
    b = build_calendar([_game("U1", status=status)], cal_name="T", dtstamp=BUILD_TIME + timedelta(days=400)).to_ical()
    assert _lines(a, b"UID") == _lines(b, b"UID") == [f"UID:{make_uid('U1')}".encode()]


def test_no_end_time_sequence_or_last_modified_is_written():
    """DTEND: Ticketmaster publishes no end time, and estimating one is the
    maintainer's decision (issue 20). SEQUENCE and LAST-MODIFIED: nothing here
    could give them a value that stays stable across identical rebuilds."""
    raw = build_calendar([_game("X1")], cal_name="T", dtstamp=BUILD_TIME).to_ical()
    for prop in (b"DTEND", b"DURATION", b"SEQUENCE", b"LAST-MODIFIED"):
        assert not _lines(raw, prop), prop


# --- the build and the validator -------------------------------------------


def _built(tmp_path: Path, monkeypatch) -> Path:
    games = [
        _game("B-1", name=f"{TEAM_A.name} vs Visiting Team"),
        _game(
            "B-2",
            name=f"{TEAM_A.name} vs Visiting Team",
            date_time="2026-06-20T23:00:00Z",
            local_date="2026-06-20",
        ),
    ]
    empty = {lg.slug: set() for lg in LEAGUES}
    monkeypatch.setattr(build_module, "fetch_all_games", lambda api_key: (games, empty, empty, 1, 1))
    out_dir = tmp_path / "dist"
    build_module.build(out_dir=out_dir, base_url="https://nexthomegame.com", api_key="fake-key", affiliate_id=None)
    return out_dir


def _fetched_at(dist: Path) -> datetime:
    return datetime.fromisoformat(json.loads((dist / "data" / "site.json").read_text())["fetched_at"])


def _stamp_line(when: datetime) -> bytes:
    return b"DTSTAMP:" + when.strftime("%Y%m%dT%H%M%SZ").encode() + b"\r\n"


def test_a_build_stamps_every_event_of_every_feed_with_its_own_fetch_time(tmp_path: Path, monkeypatch):
    dist = _built(tmp_path, monkeypatch)
    expected = _fetched_at(dist).strftime("%Y%m%dT%H%M%SZ")
    stamps = []
    for feed in sorted((dist / "ics").rglob("*.ics")):
        cal = rfc5545.parse(feed.read_bytes())
        stamps += [v.first("DTSTAMP").value for v in cal.walk("VEVENT")]
    assert len(stamps) == 4  # two games, in the league feed and in the team feed
    assert set(stamps) == {expected}
    assert validate_ics.main([str(dist)]) == 0


def test_the_fixture_site_has_no_dtstamp_after_its_fetch_time(tmp_path: Path):
    """What `make validate-fixture-site` checks, run here too."""
    dist = tmp_path / "fixture"
    build_fixture_site(dist)
    assert validate_ics.main([str(dist)]) == 0
    fetched = _fetched_at(dist)
    seen = 0
    for feed in sorted((dist / "ics").rglob("*.ics")):
        for vevent in rfc5545.parse(feed.read_bytes()).walk("VEVENT"):
            stamp = datetime.strptime(vevent.first("DTSTAMP").value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
            assert stamp == fetched, f"{feed}: {stamp} is not the build's fetch time"
            seen += 1
    assert seen == 17  # the check looked at every event the fixture writes


def _sabotage_first_dtstamp(dist: Path, fetched: datetime, replacement: bytes) -> None:
    feed = dist / "ics" / WNBA.slug / f"{TEAM_A.slug}.ics"
    before = feed.read_bytes()
    assert _stamp_line(fetched) in before
    feed.write_bytes(before.replace(_stamp_line(fetched), replacement, 1))
    assert feed.read_bytes() != before, "the sabotage did not apply"


@pytest.mark.parametrize(
    "later_by",
    [
        # the old defect: a game's own start time, a month after the build
        timedelta(days=30),
        # one second after the build
        timedelta(seconds=1),
    ],
)
def test_a_feed_with_a_dtstamp_after_the_build_fails(tmp_path: Path, monkeypatch, later_by):
    dist = _built(tmp_path, monkeypatch)
    fetched = _fetched_at(dist)
    _sabotage_first_dtstamp(dist, fetched, _stamp_line(fetched + later_by))
    with pytest.raises(validate_ics.FeedError, match="after the build's fetch time"):
        validate_ics.validate_dist(dist)


def test_a_feed_with_a_dtstamp_that_is_not_utc_fails(tmp_path: Path, monkeypatch):
    dist = _built(tmp_path, monkeypatch)
    _sabotage_first_dtstamp(dist, _fetched_at(dist), b"DTSTAMP:20200101T000000\r\n")
    with pytest.raises(validate_ics.FeedError, match="not a UTC date-time"):
        validate_ics.validate_dist(dist)


def test_a_feed_with_events_but_no_fetch_time_to_check_them_against_fails(tmp_path: Path, monkeypatch):
    dist = _built(tmp_path, monkeypatch)
    data = dist / "data" / WNBA.slug / f"{TEAM_A.slug}.json"
    payload = json.loads(data.read_text())
    assert payload["fetched_at"]
    payload["fetched_at"] = None
    data.write_text(json.dumps(payload))
    with pytest.raises(validate_ics.FeedError, match="no fetch time"):
        validate_ics.validate_dist(dist)
