from __future__ import annotations

from wsc_pipeline.config import League, Team
from wsc_pipeline.coverage import BuildCoverage, LeagueCoverage, compute_league_coverage, render_report
from wsc_pipeline.normalize import normalize_event
from .conftest import make_raw_event

LEAGUE = League(slug="wnba", name="WNBA", country_codes=("US",), teams=(Team("indiana-fever", "Indiana Fever"), Team("new-york-liberty", "New York Liberty")))


def _game(event_id, team_slug, team_name, **kwargs):
    raw = make_raw_event(event_id=event_id, **kwargs)
    return normalize_event(raw, league_slug="wnba", tracked_team_slug=team_slug, tracked_team_name=team_name)


def test_league_coverage_team_hit_rate():
    games = [
        _game("EVT1", "indiana-fever", "Indiana Fever", price_ranges=None),
    ]
    lc = compute_league_coverage(LEAGUE, games, set())
    assert lc.teams_configured == 2
    assert lc.teams_with_games == 1
    assert lc.team_hit_rate == 0.5


def test_league_coverage_price_coverage():
    games = [
        _game("EVT1", "indiana-fever", "Indiana Fever", price_ranges=[{"type": "standard", "currency": "USD", "min": 1.0, "max": 2.0}]),
        _game("EVT2", "indiana-fever", "Indiana Fever", price_ranges=None),
    ]
    lc = compute_league_coverage(LEAGUE, games, set())
    assert lc.games_total == 2
    assert lc.games_with_price == 1
    assert lc.price_coverage == 0.5


def test_league_coverage_empty_is_zero_not_error():
    lc = compute_league_coverage(LEAGUE, [], set())
    assert lc.team_hit_rate == 0.0
    assert lc.price_coverage == 0.0


def test_render_report_includes_two_numbers_everywhere():
    lc = LeagueCoverage(
        league_slug="wnba", league_name="WNBA", teams_configured=15, teams_with_games=10,
        games_total=20, games_with_price=12, games_date_tbd=1,
    )
    coverage = BuildCoverage(leagues=[lc], requests_made=15, bytes_received=12345, api_key_present=True)
    report = render_report(coverage)
    assert "10" in report and "15" in report  # teams hit vs configured
    assert "12" in report and "20" in report  # price coverage
    assert "15 requests" in report
    assert "12345 bytes" in report


def test_render_report_degraded_mode_notes_missing_key():
    coverage = BuildCoverage(leagues=[], requests_made=0, bytes_received=0, api_key_present=False)
    report = render_report(coverage)
    assert "TICKETMASTER_API_KEY not configured" in report
    assert "not a failed build" in report


def test_compute_league_coverage_records_mismatched_teams():
    """A team whose Discovery API keyword search returned a false-positive
    result (rejected by normalize.team_is_participant, see build.py's
    fetch_all_games) must show up in the coverage report -- dropping a
    contaminated event silently, with no trace in the report, would hide
    the exact 2026-09-16 production bug class from ever being noticed again."""
    lc = compute_league_coverage(LEAGUE, [], set(), {"indiana-fever"})
    assert lc.teams_with_mismatched_events == ["indiana-fever"]
    report = render_report(BuildCoverage(leagues=[lc], requests_made=0, bytes_received=0, api_key_present=True))
    assert "indiana-fever" in report
    assert "did not actually name the team" in report
