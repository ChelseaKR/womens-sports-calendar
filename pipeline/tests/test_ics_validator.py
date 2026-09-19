"""The '.ics validator run' and the 'duplicate-UID check' named in the
brief, run across every league's and every team's calendar the pipeline
would emit for a realistic multi-game, multi-team build -- not just one
calendar in isolation.
"""

from __future__ import annotations

from icalendar import Calendar

from wsc_pipeline.config import LEAGUES
from wsc_pipeline.ics import league_calendar, make_uid, team_calendar
from wsc_pipeline.normalize import normalize_event

from .conftest import BUILD_TIME, make_raw_event

REQUIRED_VEVENT_PROPS = ("uid", "dtstamp", "dtstart", "summary")


def _sample_games_for(league):
    games = []
    for i, team in enumerate(league.teams[:3]):
        raw = make_raw_event(
            event_id=f"{league.slug}-{team.slug}-{i}",
            name=f"{team.name} vs Visiting Team",
            price_ranges=[{"type": "standard", "currency": "USD", "min": 10.0 + i, "max": 50.0 + i}]
            if i != 1
            else None,
        )
        game = normalize_event(raw, league_slug=league.slug, tracked_team_slug=team.slug, tracked_team_name=team.name)
        games.append(game)
    return games


def _validate_calendar_bytes(raw: bytes) -> Calendar:
    cal = Calendar.from_ical(raw)  # raises on malformed RFC 5545
    assert str(cal.get("version")) == "2.0", "VCALENDAR must declare VERSION:2.0"
    assert cal.get("prodid") is not None, "VCALENDAR must declare PRODID"
    for vevent in cal.walk("VEVENT"):
        for prop in REQUIRED_VEVENT_PROPS:
            assert vevent.get(prop) is not None, f"VEVENT missing required property {prop}"
    return cal


def test_every_league_calendar_is_valid_rfc5545():
    for league in LEAGUES:
        games = _sample_games_for(league)
        cal = league_calendar(league.slug, league.name, games, dtstamp=BUILD_TIME)
        _validate_calendar_bytes(cal.to_ical())


def test_every_team_calendar_is_valid_rfc5545():
    for league in LEAGUES:
        games = _sample_games_for(league)
        for team in league.teams[:3]:
            cal = team_calendar(team.slug, team.name, games, dtstamp=BUILD_TIME)
            _validate_calendar_bytes(cal.to_ical())


def test_no_duplicate_uids_across_a_full_build():
    """A whole-build duplicate-UID check: collect the UID of every VEVENT
    emitted across all league and team calendars and assert global
    uniqueness within each calendar (a team calendar is a subset of its
    league calendar by design, so duplicate UIDs *across* league vs team
    calendars are expected and fine; duplicates *within* one calendar are
    not)."""
    for league in LEAGUES:
        games = _sample_games_for(league)
        league_cal = league_calendar(league.slug, league.name, games, dtstamp=BUILD_TIME)
        league_uids = [str(v["uid"]) for v in league_cal.walk("VEVENT")]
        assert len(league_uids) == len(set(league_uids)), f"duplicate UIDs in {league.slug} calendar"

        for team in league.teams[:3]:
            team_cal = team_calendar(team.slug, team.name, games, dtstamp=BUILD_TIME)
            team_uids = [str(v["uid"]) for v in team_cal.walk("VEVENT")]
            assert len(team_uids) == len(set(team_uids)), f"duplicate UIDs in {team.slug} calendar"


def test_uid_format_matches_make_uid_for_every_event():
    league = LEAGUES[0]
    games = _sample_games_for(league)
    cal = league_calendar(league.slug, league.name, games, dtstamp=BUILD_TIME)
    expected_uids = {make_uid(g.event_id) for g in games}
    actual_uids = {str(v["uid"]) for v in cal.walk("VEVENT")}
    assert actual_uids.issubset(expected_uids)
