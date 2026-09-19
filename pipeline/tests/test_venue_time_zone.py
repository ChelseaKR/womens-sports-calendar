"""One unrecognized venue time zone must not stop the nightly build (#22).

Timezone.from_tzid raises ValueError on a name it cannot resolve. Before the
fix, ics.build_calendar called it directly, so one event with a zone name
Ticketmaster mistyped (or that this build's zone database lacks) crashed the
whole build with a traceback and no league updated that night. The zone
lookup now goes through normalize.zone_for, and a game whose venue zone cannot
be used is written with its real UTC instant, keeps its UID, and is named in
the coverage report. Its zone is never guessed from the venue's city or state.
"""

from __future__ import annotations

import json
import zoneinfo
from pathlib import Path

import pytest
from icalendar import Calendar, Timezone

from wsc_pipeline import build as build_module
from wsc_pipeline.coverage import MAX_NAMED_GAMES, BuildCoverage, compute_league_coverage, render_report
from wsc_pipeline.ics import build_calendar, make_uid
from wsc_pipeline.normalize import normalize_event, zone_for, zone_problem

from .conftest import make_raw_event
from .test_build import _FakeDiscoveryClient
from .test_coverage import LEAGUE


def _game(event_id: str, **kwargs):
    return normalize_event(
        make_raw_event(event_id=event_id, **kwargs),
        league_slug="wnba",
        tracked_team_slug="indiana-fever",
        tracked_team_name="Indiana Fever",
    )


def _ical_text(cal: Calendar) -> str:
    return cal.to_ical().decode("utf-8")


def test_unknown_zone_builds_with_a_utc_start_and_keeps_its_uid():
    """The reproduction from the issue: this raised ValueError."""
    game = _game("Z1", timezone="Mars/Olympus", date_time="2026-06-15T23:00:00Z")
    cal = build_calendar([game], cal_name="x")
    (event,) = cal.walk("VEVENT")
    assert str(event["uid"]) == make_uid("Z1")
    text = _ical_text(cal)
    assert "DTSTART:20260615T230000Z" in text  # the real instant, in UTC
    assert "TZID" not in text  # no zone was guessed, so none is claimed
    assert cal.walk("VTIMEZONE") == []


@pytest.mark.parametrize("tzid", [None, "", "   ", "America/New_York ", "../etc/passwd", "Not/AZone"])
def test_missing_or_malformed_zone_builds_with_a_utc_start(tzid):
    game = _game("Z2", timezone=tzid, date_time="2026-06-15T23:00:00Z")
    cal = build_calendar([game], cal_name="x")
    (event,) = cal.walk("VEVENT")
    assert str(event["uid"]) == make_uid("Z2")
    assert "DTSTART:20260615T230000Z" in _ical_text(cal)
    assert cal.walk("VTIMEZONE") == []


def test_one_bad_zone_does_not_change_its_neighbors():
    """The bad game degrades alone: a valid game beside it still gets
    DTSTART;TZID=... and its VTIMEZONE."""
    good = _game("GOOD", timezone="America/Indiana/Indianapolis", date_time="2026-06-15T23:00:00Z")
    bad = _game("BAD", timezone="Mars/Olympus", date_time="2026-06-16T23:00:00Z")
    cal = build_calendar([good, bad], cal_name="x")
    assert {str(e["uid"]) for e in cal.walk("VEVENT")} == {make_uid("GOOD"), make_uid("BAD")}
    text = _ical_text(cal)
    assert "DTSTART;TZID=America/Indiana/Indianapolis:20260615T190000" in text
    assert "DTSTART:20260616T230000Z" in text
    assert [str(tz["tzid"]) for tz in cal.walk("VTIMEZONE")] == ["America/Indiana/Indianapolis"]


def test_a_valid_zone_is_written_exactly_as_before():
    """Negative control for the fix: nothing changes for a zone that resolves."""
    game = _game("OK", timezone="America/Los_Angeles", date_time="2026-06-15T23:00:00Z")
    text = _ical_text(build_calendar([game], cal_name="x"))
    assert "DTSTART;TZID=America/Los_Angeles:20260615T160000" in text
    assert "BEGIN:VTIMEZONE" in text and "TZID:America/Los_Angeles" in text


def test_every_zone_the_database_knows_gets_a_vtimezone():
    """zone_for and icalendar must agree on which names are usable, so a
    zone that zone_for accepts is never written as a TZID with no VTIMEZONE."""
    disagreements = []
    for name in sorted(zoneinfo.available_timezones()):
        assert zone_for(name) is not None, name
        try:
            Timezone.from_tzid(name)
        except ValueError:
            disagreements.append(name)
    assert disagreements == []


def test_zone_problem_tells_missing_from_unrecognized():
    assert zone_problem("America/Chicago") is None
    assert zone_problem(None) == "no venue time zone sent"
    assert zone_problem("  ") == "no venue time zone sent"
    assert zone_problem("Mars/Olympus") == "unrecognized venue time zone 'Mars/Olympus'"


def test_coverage_names_the_games_that_fell_back_to_utc():
    games = [
        _game("Z-BAD", timezone="Mars/Olympus", name="Indiana Fever vs New York Liberty"),
        _game("Z-NONE", timezone=None, venue_name=None, venue_city=None, venue_state=None),
        _game("Z-OK", timezone="America/Chicago"),
    ]
    lc = compute_league_coverage(LEAGUE, games, set())
    assert [(z.event_id, z.reason) for z in lc.zone_fallbacks] == [
        ("Z-BAD", "unrecognized venue time zone 'Mars/Olympus'"),
        ("Z-NONE", "no venue time zone sent"),
    ]
    report = render_report(BuildCoverage(leagues=[lc], requests_made=1, bytes_received=1, api_key_present=True))
    assert "WARNING: 2 game(s) are in the calendar with a UTC start" in report
    assert "Z-BAD (Indiana Fever vs New York Liberty): unrecognized venue time zone 'Mars/Olympus'" in report
    assert "Z-OK" not in report


def test_a_game_with_no_date_is_not_reported_as_a_zone_fallback():
    """A date-TBD game is not in the feed at all, so it has no start to write."""
    tbd = _game("Z-TBD", timezone="Mars/Olympus", date_time=None, date_tbd=True, local_time=None)
    assert compute_league_coverage(LEAGUE, [tbd], set()).zone_fallbacks == []


def test_a_clean_build_reports_no_zone_warning():
    lc = compute_league_coverage(LEAGUE, [_game("Z-OK", timezone="America/Chicago")], set())
    report = render_report(BuildCoverage(leagues=[lc], requests_made=1, bytes_received=1, api_key_present=True))
    assert "UTC start" not in report


def test_the_report_names_a_bounded_number_of_games_and_counts_the_rest():
    games = [_game(f"Z{i:03d}", timezone="Mars/Olympus") for i in range(MAX_NAMED_GAMES + 5)]
    lc = compute_league_coverage(LEAGUE, games, set())
    report = render_report(BuildCoverage(leagues=[lc], requests_made=1, bytes_received=1, api_key_present=True))
    assert f"{MAX_NAMED_GAMES + 5} game(s)" in report
    assert "and 5 more" in report
    assert f"Z{MAX_NAMED_GAMES:03d}" not in report  # named up to the cap, counted after it


def test_a_full_build_survives_one_unknown_zone_and_says_so(tmp_path: Path, monkeypatch, capsys):
    """End to end through main(): the build succeeds, the bad game is in its
    team's and its league's feed with its UID, COVERAGE.txt names it, and the
    run log carries a WARNING. Every other game is untouched."""
    bad = make_raw_event(event_id="EVT-BAD", name="Indiana Fever vs Chicago Sky", timezone="Mars/Olympus")
    good = make_raw_event(
        event_id="EVT-GOOD",
        name="Indiana Fever vs Atlanta Dream",
        date_time="2026-06-17T23:00:00Z",
        local_date="2026-06-17",
        timezone="America/Indiana/Indianapolis",
    )
    fake_client = _FakeDiscoveryClient({"indiana-fever": [bad, good]})
    monkeypatch.setattr(build_module, "DiscoveryClient", lambda api_key: fake_client)
    monkeypatch.setenv("TICKETMASTER_API_KEY", "fake-key")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    out_dir = tmp_path / "dist"

    rc = build_module.main(["--out", str(out_dir), "--base-url", "https://nexthomegame.com"])

    assert rc == 0
    err = capsys.readouterr().err
    assert "BUILD FAILED" not in err
    assert "WARNING: 1 game(s) were written to the calendars with a UTC start" in err
    assert "::warning" not in err  # the annotation is only for Actions
    coverage_txt = (out_dir / "COVERAGE.txt").read_text()
    assert "EVT-BAD" in coverage_txt and "unrecognized venue time zone 'Mars/Olympus'" in coverage_txt
    assert "EVT-GOOD" not in coverage_txt
    for feed in ("wnba.ics", "wnba/indiana-fever.ics"):
        cal = Calendar.from_ical((out_dir / "ics" / feed).read_bytes())
        assert {str(e["uid"]) for e in cal.walk("VEVENT")} == {make_uid("EVT-BAD"), make_uid("EVT-GOOD")}
        text = cal.to_ical().decode("utf-8")
        assert "DTSTART:20260615T230000Z" in text
        assert "DTSTART;TZID=America/Indiana/Indianapolis:20260617T190000" in text
    team_json = json.loads((out_dir / "data" / "wnba" / "indiana-fever.json").read_text())
    assert {g["event_id"] for g in team_json["games"]} == {"EVT-BAD", "EVT-GOOD"}


def test_a_github_actions_run_also_gets_a_workflow_annotation(tmp_path: Path, monkeypatch, capsys):
    bad = make_raw_event(event_id="EVT-BAD", name="Indiana Fever vs Chicago Sky", timezone="Mars/Olympus")
    fake_client = _FakeDiscoveryClient({"indiana-fever": [bad]})
    monkeypatch.setattr(build_module, "DiscoveryClient", lambda api_key: fake_client)
    monkeypatch.setenv("TICKETMASTER_API_KEY", "fake-key")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    rc = build_module.main(["--out", str(tmp_path / "dist"), "--base-url", "https://nexthomegame.com"])

    assert rc == 0
    assert "::warning title=Unknown venue time zone::1 game(s)" in capsys.readouterr().err
