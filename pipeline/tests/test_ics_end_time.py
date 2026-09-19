"""The estimated end time of a game in the .ics feeds.

Ticketmaster publishes a start and never an end, and a DTEND-less event
is a zero-length marker in some calendar apps. The maintainer decided
(DECISIONS 0015) that each timed event carries an end estimated from its
sport's usual game length (config.GAME_DURATIONS, overridable per league)
and says so in its description. These tests hold that to every sport the
site tracks, to the labeling, and to the validator.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from icalendar import Calendar

from wsc_pipeline import build as build_module
from wsc_pipeline import validate_ics
from wsc_pipeline.config import GAME_DURATIONS, LEAGUES, League, estimated_duration
from wsc_pipeline.ics import END_ESTIMATE_NOTE, build_calendar, make_uid
from wsc_pipeline.normalize import normalize_event

from . import rfc5545
from .conftest import BUILD_TIME, make_raw_event

CHICAGO = "America/Chicago"


def _game(league: League, event_id: str, *, date_time="2026-06-15T23:00:00Z", local_date="2026-06-15", tz=CHICAGO):
    team = league.teams[0]
    raw = make_raw_event(
        event_id=event_id,
        name=f"{team.name} vs Visiting Team",
        date_time=date_time,
        local_date=local_date,
        timezone=tz,
    )
    game = normalize_event(raw, league_slug=league.slug, tracked_team_slug=team.slug, tracked_team_name=team.name)
    assert game is not None
    return game


def _text(prop) -> str:
    return rfc5545.unescape_text(prop.value)


def test_every_sport_the_site_tracks_has_an_estimate():
    """A sport added to config without a duration would silently publish
    zero-length events; this fails first."""
    for league in LEAGUES:
        assert estimated_duration(league) is not None, f"{league.slug} ({league.sport!r}) has no game duration"
    assert {lg.sport for lg in LEAGUES} <= set(GAME_DURATIONS)
    assert all(timedelta(hours=1) <= d <= timedelta(hours=5) for d in GAME_DURATIONS.values())


def test_a_league_can_override_its_sports_duration_and_an_unknown_sport_has_none():
    wnba = LEAGUES[0]
    assert estimated_duration(replace(wnba, game_duration=timedelta(hours=3))) == timedelta(hours=3)
    assert estimated_duration(replace(wnba, game_duration=timedelta(0))) == timedelta(0)
    assert estimated_duration(replace(wnba, sport="Curling")) is None
    assert estimated_duration(replace(wnba, sport="")) is None


def _built_with_a_game_per_league(tmp_path: Path, monkeypatch) -> Path:
    games = [_game(lg, f"END-{lg.slug}") for lg in LEAGUES]
    empty = {lg.slug: set() for lg in LEAGUES}
    monkeypatch.setattr(build_module, "fetch_all_games", lambda api_key: (games, empty, empty, 1, 1))
    out_dir = tmp_path / "dist"
    build_module.build(out_dir=out_dir, base_url="https://nexthomegame.com", api_key="fake-key", affiliate_id=None)
    return out_dir


def test_every_league_in_a_real_build_ends_its_games_one_estimated_duration_after_the_start(
    tmp_path: Path, monkeypatch
):
    dist = _built_with_a_game_per_league(tmp_path, monkeypatch)
    start = datetime(2026, 6, 15, 18, 0)  # 23:00Z is 18:00 in Chicago (CDT)
    for league in LEAGUES:
        expected_end = (start + estimated_duration(league)).strftime("%Y%m%dT%H%M%S")
        feeds = [dist / "ics" / f"{league.slug}.ics", dist / "ics" / league.slug / f"{league.teams[0].slug}.ics"]
        for feed in feeds:
            (vevent,) = rfc5545.parse(feed.read_bytes()).walk("VEVENT")
            dtstart, dtend = vevent.first("DTSTART"), vevent.first("DTEND")
            assert dtend is not None, f"{feed}: no DTEND"
            assert dtend.value == expected_end, f"{feed}: {league.sport} game should end at {expected_end}"
            assert dtend.param("TZID") == dtstart.param("TZID") == CHICAGO
            assert END_ESTIMATE_NOTE in _text(vevent.first("DESCRIPTION")).split("\n")
    assert validate_ics.main([str(dist)]) == 0


def test_the_estimate_is_labeled_in_the_description_in_the_words_the_maintainer_chose():
    assert END_ESTIMATE_NOTE == "End time estimated; not published by the ticket source."


def test_a_calendar_with_no_duration_writes_no_end_and_no_label():
    """Negative control: the end and its label appear together or not at all,
    and a sport with no estimate never gets a guessed one."""
    game = _game(LEAGUES[0], "NO-END")
    raw = build_calendar([game], cal_name="T", dtstamp=BUILD_TIME, game_duration=None).to_ical()
    (vevent,) = rfc5545.parse(raw).walk("VEVENT")
    assert vevent.first("DTEND") is None and vevent.first("DURATION") is None
    assert END_ESTIMATE_NOTE not in _text(vevent.first("DESCRIPTION"))
    with_end = build_calendar([game], cal_name="T", dtstamp=BUILD_TIME, game_duration=timedelta(hours=2)).to_ical()
    (vevent,) = rfc5545.parse(with_end).walk("VEVENT")
    assert vevent.first("DTEND") is not None
    assert END_ESTIMATE_NOTE in _text(vevent.first("DESCRIPTION"))


def test_the_end_is_the_estimated_duration_later_even_across_a_clock_change():
    """1:30 AM CDT on 2026-11-01, the night the clocks go back: two and a
    half hours later is 3:00 AM CST by the clock, not 4:00. The duration is
    added to the UTC instant, then shown in the venue's zone."""
    game = _game(LEAGUES[0], "DST-1", date_time="2026-11-01T06:30:00Z", local_date="2026-11-01")
    raw = build_calendar([game], cal_name="T", dtstamp=BUILD_TIME, game_duration=timedelta(hours=2, minutes=30))
    (vevent,) = rfc5545.parse(raw.to_ical()).walk("VEVENT")
    assert vevent.first("DTSTART").value == "20261101T013000"
    assert vevent.first("DTEND").value == "20261101T030000"
    start = datetime(2026, 11, 1, 6, 30, tzinfo=UTC)
    assert (start + timedelta(hours=2, minutes=30)).astimezone(ZoneInfo(CHICAGO)).strftime("%H:%M") == "03:00"


def test_a_game_with_no_venue_zone_ends_in_utc_like_it_starts():
    game = _game(LEAGUES[0], "UTC-1", tz=None)
    raw = build_calendar([game], cal_name="T", dtstamp=BUILD_TIME, game_duration=timedelta(hours=2))
    (vevent,) = rfc5545.parse(raw.to_ical()).walk("VEVENT")
    assert vevent.first("DTSTART").value == "20260615T230000Z"
    assert vevent.first("DTEND").value == "20260616T010000Z"


@pytest.mark.parametrize("duration", [None, timedelta(hours=2)])
def test_the_uid_does_not_depend_on_the_estimate(duration):
    raw = build_calendar([_game(LEAGUES[0], "UID-END")], cal_name="T", dtstamp=BUILD_TIME, game_duration=duration)
    uid_lines = [line for line in raw.to_ical().split(b"\r\n") if line.startswith(b"UID:")]
    assert uid_lines == [f"UID:{make_uid('UID-END')}".encode()]


# --- the validator ----------------------------------------------------------


def _drop_the_end(vevent) -> None:
    del vevent["dtend"]


def _drop_the_label(vevent) -> None:
    description = str(vevent["description"])
    assert END_ESTIMATE_NOTE in description
    vevent["description"] = description.replace(END_ESTIMATE_NOTE, "").replace("\n\n", "\n")


def _end_before_the_start(vevent) -> None:
    del vevent["dtend"]
    vevent.add("dtend", vevent.decoded("dtstart") - timedelta(hours=1))


@pytest.mark.parametrize(
    "sabotage,match",
    [
        (_drop_the_end, "has no DTEND but its DESCRIPTION carries"),  # the line with no end: false
        (_drop_the_label, "has a DTEND but its DESCRIPTION lacks"),  # an estimate presented as data
        (_end_before_the_start, "not after DTSTART"),
    ],
)
def test_a_feed_whose_end_time_and_label_disagree_or_precede_the_start_fails(
    tmp_path: Path, monkeypatch, sabotage, match
):
    dist = _built_with_a_game_per_league(tmp_path, monkeypatch)
    league = LEAGUES[0]
    feed = dist / "ics" / league.slug / f"{league.teams[0].slug}.ics"
    cal = Calendar.from_ical(feed.read_bytes())
    (vevent,) = cal.walk("VEVENT")
    before = vevent.to_ical()
    sabotage(vevent)
    assert vevent.to_ical() != before, "the sabotage did not apply"
    feed.write_bytes(cal.to_ical())
    with pytest.raises(validate_ics.FeedError, match=match):
        validate_ics.validate_dist(dist)
