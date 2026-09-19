"""The publish guard: a build that would take a league's or a team's upcoming
games out of subscribers' calendars is refused, and the last good deploy stays
live (#21). See guard.py for the rules and config.PublishGuard for the numbers.

Dates are fixed and every test passes its own clock, so nothing here depends
on today's date.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from wsc_pipeline import build as build_module
from wsc_pipeline import config, guard
from wsc_pipeline.config import GuardOverride, PublishGuard
from wsc_pipeline.coverage import BuildCoverage, render_report
from wsc_pipeline.guard import PreviousGame, PreviousPublish, PublishRefused, evaluate
from wsc_pipeline.normalize import Game, normalize_event

from .conftest import REAL_FETCH_PREVIOUS_PUBLISH, make_raw_event
from .test_build import _FakeDiscoveryClient

NOW = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
SETTINGS = PublishGuard(settle_hours=24, min_previous_upcoming=3, max_league_vanished_share=0.5)
BASE_URL = "https://nexthomegame.com"

FEVER = "indiana-fever"
LIBERTY = "new-york-liberty"


def _start(days: float) -> datetime:
    return NOW + timedelta(days=days)


def _prev(event_id: str, days: float, status: str | None = None) -> PreviousGame:
    return PreviousGame(event_id=event_id, name=f"Event {event_id}", start=_start(days), status=status)


def _previous(**teams: list[PreviousGame]) -> PreviousPublish:
    """A previous publish. Keys are 'league__team' with dashes as underscores
    for readability at the call site."""
    out = PreviousPublish(fetched_at="2026-05-31T08:00:00+00:00")
    for key, games in teams.items():
        league, team = key.split("__")
        out.games[(league, team.replace("_", "-"))] = games
    return out


def _fresh(event_id: str, league: str, team: str, days: float, *, status: str | None = None, **kwargs) -> Game:
    start = _start(days)
    raw = make_raw_event(
        event_id=event_id,
        name=f"Event {event_id}",
        date_time=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        local_date=start.strftime("%Y-%m-%d"),
        status=status,
        **kwargs,
    )
    game = normalize_event(raw, league_slug=league, tracked_team_slug=team, tracked_team_name=team)
    assert game is not None
    return game


def _run(previous: PreviousPublish, games: list[Game], **kwargs):
    kwargs.setdefault("settings", SETTINGS)
    kwargs.setdefault("overrides", ())
    kwargs.setdefault("now", NOW)
    return evaluate(previous, games, kwargs.pop("truncated", {}), **kwargs)


def _feed_of(*ids_and_days: tuple[str, float], team: str = FEVER, league: str = "wnba") -> list[Game]:
    return [_fresh(e, league, team, d) for e, d in ids_and_days]


# --- the numbers -----------------------------------------------------------------------------------------


def test_the_default_thresholds_are_the_documented_ones():
    """docs/adr/0006 and config.PublishGuard's docstring quote these."""
    assert PublishGuard(settle_hours=24, min_previous_upcoming=3, max_league_vanished_share=0.5) == config.PUBLISH_GUARD
    assert config.PUBLISH_GUARD_OVERRIDES == ()


# --- a team loses its games -----------------------------------------------------------------------------


def test_a_team_losing_all_its_upcoming_games_refuses_and_names_the_team_and_games():
    previous = _previous(
        wnba__indiana_fever=[_prev("A", 10), _prev("B", 20), _prev("C", 30)],
        wnba__new_york_liberty=[_prev(f"L{i}", 12 + i) for i in range(5)],
    )
    # The Fever's three games are gone; the Liberty's five are all still listed,
    # so the league as a whole (3 of 8 gone) is under the share limit.
    fresh = _feed_of(*[(f"L{i}", 12 + i) for i in range(5)], team=LIBERTY)
    report = _run(previous, fresh)
    assert report.refused
    (violation,) = report.violations
    assert violation.rule == "team-all" and violation.team_slug == FEVER
    for needle in (FEVER, "lost all 3", "A (Event A", "B (Event B", "C (Event C"):
        assert needle in violation.message
    text = str(PublishRefused(report))
    assert "wnba/indiana-fever" in text and "Nothing was written" in text and "PUBLISH_GUARD_OVERRIDES" in text


def test_a_team_that_kept_one_of_its_games_is_not_refused_but_the_loss_is_listed():
    previous = _previous(
        wnba__indiana_fever=[_prev("A", 10), _prev("B", 20), _prev("C", 30)],
        wnba__new_york_liberty=[_prev(f"L{i}", 12 + i) for i in range(6)],
    )
    kept = _feed_of(("C", 30)) + _feed_of(*[(f"L{i}", 12 + i) for i in range(6)], team=LIBERTY)
    report = _run(previous, kept)
    assert not report.refused
    assert [v.event_id for v in report.vanished] == ["A", "B"]


def test_a_team_with_fewer_than_the_minimum_games_is_listed_but_never_blocks():
    """Negative control for the minimum: two games leaving is ordinary churn."""
    previous = _previous(
        wnba__indiana_fever=[_prev("A", 10), _prev("B", 20)],
        wnba__new_york_liberty=[_prev(f"L{i}", 12 + i) for i in range(6)],
    )
    report = _run(previous, _feed_of(*[(f"L{i}", 12 + i) for i in range(6)], team=LIBERTY))
    assert not report.refused
    assert [v.event_id for v in report.vanished] == ["A", "B"]


# --- a league loses its games ---------------------------------------------------------------------------


def _league_previous(n_fever: int, n_liberty: int) -> PreviousPublish:
    return _previous(
        wnba__indiana_fever=[_prev(f"F{i}", 10 + i) for i in range(n_fever)],
        wnba__new_york_liberty=[_prev(f"L{i}", 10 + i) for i in range(n_liberty)],
    )


def test_a_league_calendar_that_would_be_empty_is_refused_even_for_a_single_game():
    """Never publish an empty feed over a non-empty one: no minimum applies."""
    report = _run(_previous(wnba__indiana_fever=[_prev("A", 10)]), [])
    (violation,) = report.violations
    assert violation.rule == "league-empty"
    assert "EMPTY calendar" in violation.message and "1 upcoming" in violation.message


def test_a_league_losing_more_than_half_its_games_is_refused():
    previous = _league_previous(4, 4)
    kept = _feed_of(("F0", 10), team=FEVER) + _feed_of(("L0", 10), team=LIBERTY)
    report = _run(previous, kept)  # 6 of 8 gone = 75%
    rules = sorted(v.rule for v in report.violations)
    assert "league-share" in rules
    share = next(v for v in report.violations if v.rule == "league-share")
    assert "lost 6 of 8" in share.message and "75%" in share.message and "limit is 50%" in share.message


def test_a_league_at_exactly_the_share_limit_passes_and_just_over_it_refuses():
    """The limit is 'more than 50%'. Losing every Liberty game out of ten is
    exactly 50% (the Liberty's own team rule fires, the league rule does not);
    losing one more Fever game makes it 60% and the league rule fires too."""
    previous = _league_previous(5, 5)
    keep_all_fever = [(f"F{i}", 10 + i) for i in range(5)]
    at_limit = _run(previous, _feed_of(*keep_all_fever, team=FEVER))
    assert [v.rule for v in at_limit.violations] == ["team-all"]
    assert (at_limit.league_vanished, at_limit.previous_upcoming) == (5, 10)

    over = _run(previous, _feed_of(*keep_all_fever[:4], team=FEVER))
    assert (over.league_vanished, over.previous_upcoming) == (6, 10)
    assert "league-share" in [v.rule for v in over.violations]


def test_a_small_league_drop_is_listed_but_does_not_block():
    """Negative control for the share: 2 of 10 games gone is churn."""
    previous = _league_previous(5, 5)
    kept = _feed_of(*[(f"F{i}", 10 + i) for i in range(4)], team=FEVER) + _feed_of(
        *[(f"L{i}", 10 + i) for i in range(4)], team=LIBERTY
    )
    report = _run(previous, kept)
    assert not report.refused
    assert report.league_vanished == 2 and report.previous_upcoming == 10


# --- what does not count as vanished ------------------------------------------------------------------


def test_a_league_whose_season_ended_passes():
    """Every previous game is in the past by now: nothing vanished, nothing
    to alarm, and no season calendar was needed to know it."""
    previous = _previous(wnba__indiana_fever=[_prev("A", -20), _prev("B", -10), _prev("C", -1)])
    report = _run(previous, [])
    assert not report.refused and report.vanished == [] and report.previous_upcoming == 0


def test_a_game_that_starts_inside_the_settling_window_is_not_counted():
    """A game a few hours away that Ticketmaster has already dropped is the
    ordinary end of a listing, not a loss."""
    previous = _previous(wnba__indiana_fever=[_prev("A", 0.2), _prev("B", 0.5), _prev("C", 0.9)])
    report = _run(previous, [])
    assert not report.refused and report.previous_upcoming == 0
    just_outside = _previous(wnba__indiana_fever=[_prev("A", 1.01)])
    assert _run(just_outside, []).refused  # more than 24 hours away: counted, and the league is empty


def test_a_game_the_previous_publish_marked_cancelled_or_postponed_is_not_counted_and_is_reported():
    previous = _previous(
        wnba__indiana_fever=[_prev("A", 10, "Cancelled"), _prev("B", 20, "Postponed"), _prev("C", 30)],
    )
    report = _run(previous, _feed_of(("C", 30)))
    assert not report.refused
    assert report.vanished == []
    assert len(report.removed_after_cancel) == 2
    section = "\n".join(guard.render_section(report))
    assert "removed after being marked cancelled or postponed (expected, not counted): 2" in section


def test_a_game_still_listed_but_now_cancelled_passes_and_is_reported():
    previous = _previous(wnba__indiana_fever=[_prev("A", 10), _prev("B", 20), _prev("C", 30)])
    fresh = [
        _fresh("A", "wnba", FEVER, 10, status="cancelled"),
        _fresh("B", "wnba", FEVER, 20),
        _fresh("C", "wnba", FEVER, 30),
    ]
    report = _run(previous, fresh)
    assert not report.refused and report.vanished == []
    assert report.newly_cancelled == ["wnba: A (Event A)"]
    assert "newly cancelled or postponed, still listed: 1" in "\n".join(guard.render_section(report))


def test_a_game_still_listed_but_now_date_tbd_is_still_present():
    """The feed drops a date-TBD game by an existing, documented rule; it has
    not vanished from Ticketmaster's listing."""
    previous = _previous(wnba__indiana_fever=[_prev("A", 10)])
    tbd = normalize_event(
        make_raw_event(event_id="A", date_time=None, local_date="2026-06-11", local_time=None, date_tbd=True),
        league_slug="wnba",
        tracked_team_slug=FEVER,
        tracked_team_name="Indiana Fever",
    )
    assert tbd is not None
    report = _run(previous, [tbd, *_feed_of(("Z", 40))])
    assert report.vanished == []


def test_previously_date_tbd_games_are_not_counted_because_no_feed_ever_carried_them():
    payload = {
        "fetched": True,
        "fetched_at": "2026-05-31T08:00:00+00:00",
        "games": [
            {"event_id": "TBD1", "in_calendar_feed": False, "start_utc": None, "status": None},
            {"event_id": "OK1", "in_calendar_feed": True, "start_utc": "2026-06-20T18:00:00+00:00", "status": None},
        ],
    }
    parsed = guard._parse_previous_team(payload)
    assert parsed is not None
    fetched_at, games = parsed
    assert fetched_at == "2026-05-31T08:00:00+00:00"
    assert [g.event_id for g in games] == ["OK1"]


# --- possibly-incomplete fetches -------------------------------------------------------------------------


def test_a_team_whose_fetch_was_cut_short_is_not_blamed_for_missing_games():
    """Ticketmaster results are read in date order and a truncated read stops
    before the end, so what is missing is not known to be gone."""
    previous = _previous(wnba__indiana_fever=[_prev("A", 10), _prev("B", 20), _prev("C", 30)])
    report = _run(previous, [], truncated={"wnba": {FEVER}})
    assert not report.refused
    assert report.vanished == [] and len(report.unverifiable) == 3
    assert "possibly-incomplete" in "\n".join(guard.render_section(report))


# --- the override --------------------------------------------------------------------------------------


def test_an_active_override_accepts_the_shrink_but_says_so():
    previous = _previous(wnba__indiana_fever=[_prev("A", 10), _prev("B", 20), _prev("C", 30)])
    override = GuardOverride("wnba", "the league withdrew the listings", date(2026, 6, 15))
    report = _run(previous, [], overrides=(override,))
    assert not report.refused
    assert {v.rule for v in report.accepted} == {"team-all", "league-empty"}
    section = "\n".join(guard.render_section(report))
    assert "ACCEPTED BY OVERRIDE (the league withdrew the listings (until 2026-06-15))" in section


def test_an_override_for_one_league_does_not_cover_another():
    previous = _previous(
        wnba__indiana_fever=[_prev("A", 10), _prev("B", 20), _prev("C", 30)],
        nwsl__angel_city=[_prev("N1", 10), _prev("N2", 20), _prev("N3", 30)],
    )
    override = GuardOverride("wnba", "off-season", date(2026, 6, 15))
    report = _run(previous, [], overrides=(override,))
    assert {v.league_slug for v in report.violations} == {"nwsl"}
    assert {v.league_slug for v in report.accepted} == {"wnba"}


def test_an_expired_override_no_longer_applies_and_the_build_says_so():
    previous = _previous(wnba__indiana_fever=[_prev("A", 10), _prev("B", 20), _prev("C", 30)])
    override = GuardOverride("wnba", "off-season", date(2026, 5, 31))  # the day before NOW
    report = _run(previous, [], overrides=(override,))
    assert report.refused and report.accepted == []
    assert "expired on 2026-05-31" in report.expired_overrides[0]
    assert "expired on 2026-05-31" in "\n".join(guard.render_section(report))


def test_an_override_is_still_active_on_its_last_day():
    previous = _previous(wnba__indiana_fever=[_prev("A", 10)])
    override = GuardOverride("wnba", "off-season", NOW.date())
    assert not _run(previous, [], overrides=(override,)).refused


# --- an unreadable previous publish is reported, not skipped ----------------------------------------------


def _fetch_with(handler: Callable[[httpx.Request], httpx.Response]) -> PreviousPublish:
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return REAL_FETCH_PREVIOUS_PUBLISH(BASE_URL, client=client)


def test_a_site_that_cannot_be_read_is_reported_and_does_not_block():
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    previous = _fetch_with(down)
    assert previous.games == {} and len(previous.unreadable) == len(config.all_teams())
    assert previous.unreadable[("wnba", "minnesota-lynx")] == "request failed (ConnectError)"
    report = _run(previous, [])
    assert report.compared is False and not report.refused
    assert "NOT compared with it" in report.note
    assert "NOT COMPARED" in "\n".join(guard.render_section(report))


def test_a_site_that_stops_answering_is_given_up_on_after_a_few_requests():
    calls = []

    def down(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        raise httpx.ConnectTimeout("slow")

    previous = _fetch_with(down)
    assert len(calls) == guard._GIVE_UP_AFTER  # not 67 timeouts
    assert len(previous.unreadable) == len(config.all_teams())
    assert previous.unreadable[("wnba", "seattle-storm")].startswith("not tried")


def test_a_missing_page_is_a_new_team_and_other_failures_are_unreadable():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen[path] = seen.get(path, 0) + 1
        if path.endswith("/indiana-fever.json"):
            return httpx.Response(404)
        if path.endswith("/new-york-liberty.json"):
            return httpx.Response(503)
        if path.endswith("/seattle-storm.json"):
            return httpx.Response(200, text="<html>not json</html>")
        if path.endswith("/las-vegas-aces.json"):
            return httpx.Response(200, json={"fetched": False, "games": []})  # a degraded build's file
        return httpx.Response(200, json={"fetched": True, "fetched_at": "2026-05-31T08:00:00+00:00", "games": []})

    previous = _fetch_with(handler)
    assert previous.games[("wnba", "indiana-fever")] == [] and ("wnba", "indiana-fever") in previous.new_teams
    assert previous.unreadable[("wnba", "new-york-liberty")] == "HTTP 503"
    assert "not a fetched team file" in previous.unreadable[("wnba", "seattle-storm")]
    assert "not a fetched team file" in previous.unreadable[("wnba", "las-vegas-aces")]
    assert previous.fetched_at == "2026-05-31T08:00:00+00:00"


def test_teams_that_could_not_be_read_are_named_in_the_report_and_the_rest_are_still_compared():
    previous = _previous(wnba__indiana_fever=[_prev("A", 10), _prev("B", 20), _prev("C", 30)])
    previous.unreadable[("wnba", "seattle-storm")] = "HTTP 503"
    report = _run(previous, _feed_of(("A", 10), ("B", 20), ("C", 30)))
    assert report.compared and not report.refused
    section = "\n".join(guard.render_section(report))
    assert "WARNING: 1 team file(s) of the previous publish could not be read" in section
    assert "wnba/seattle-storm (HTTP 503)" in section


# --- end to end through the real build --------------------------------------------------------------------


def _raw(event_id: str, *, opponent: str, days: float, home: str = "Indiana Fever", **kwargs) -> dict:
    start = _start(days)
    return make_raw_event(
        event_id=event_id,
        name=f"{home} vs {opponent}",
        date_time=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        local_date=start.strftime("%Y-%m-%d"),
        **kwargs,
    )


def _serve(dist: Path) -> Callable[[httpx.Request], httpx.Response]:
    """The live site, as a mock transport over a directory a build wrote."""

    def handler(request: httpx.Request) -> httpx.Response:
        target = dist / request.url.path.lstrip("/")
        if not target.is_file():
            return httpx.Response(404)
        return httpx.Response(200, content=target.read_bytes())

    return handler


def _build(out: Path, responses: dict[str, list[dict]], monkeypatch, previous: PreviousPublish | None):
    monkeypatch.setattr(build_module, "DiscoveryClient", lambda api_key: _FakeDiscoveryClient(responses))
    return build_module.build(
        out_dir=out, base_url=BASE_URL, api_key="fake-key", affiliate_id=None, previous_publish=previous, now=NOW
    )


def _five_fever_games() -> list[dict]:
    return [_raw(f"G{i}", opponent="Chicago Sky", days=10 + i) for i in range(5)]


def _liberty_games(n: int = 12) -> list[dict]:
    """Enough games for another team that a Fever-only loss stays under the
    league share limit (and the build's own all-teams-empty check is quiet)."""
    return [_raw(f"L{i}", home="New York Liberty", opponent="Seattle Storm", days=10 + i) for i in range(n)]


def test_two_builds_in_a_row_where_a_team_loses_its_games_refuses_the_second(tmp_path: Path, monkeypatch):
    """The whole path: build 1 publishes; build 2 reads build 1's real data
    files (over a mock transport) and refuses, leaving build 1's site alone."""
    live = tmp_path / "live"
    _build(live, {FEVER: _five_fever_games(), LIBERTY: _liberty_games()}, monkeypatch, None)
    good_feed = (live / "ics" / "wnba" / f"{FEVER}.ics").read_bytes()

    with httpx.Client(transport=httpx.MockTransport(_serve(live))) as client:
        previous = REAL_FETCH_PREVIOUS_PUBLISH(BASE_URL, client=client)
    assert len(previous.games[("wnba", FEVER)]) == 5

    with pytest.raises(PublishRefused) as raised:
        _build(
            live, {FEVER: [], LIBERTY: _liberty_games()}, monkeypatch, previous
        )  # the Fever's search matches nothing
    assert "lost all 5 of its upcoming games" in str(raised.value)
    assert (live / "ics" / "wnba" / f"{FEVER}.ics").read_bytes() == good_feed  # untouched
    assert not live.with_name("live.tmp").exists()


def test_a_build_that_keeps_all_its_games_publishes_and_the_report_says_it_compared(tmp_path: Path, monkeypatch):
    live = tmp_path / "live"
    _build(live, {FEVER: _five_fever_games()}, monkeypatch, None)
    with httpx.Client(transport=httpx.MockTransport(_serve(live))) as client:
        previous = REAL_FETCH_PREVIOUS_PUBLISH(BASE_URL, client=client)

    out = tmp_path / "next"
    coverage = _build(out, {FEVER: _five_fever_games()}, monkeypatch, previous)
    assert coverage.publish_guard is not None and coverage.publish_guard.compared and not coverage.publish_guard.refused
    text = (out / "COVERAGE.txt").read_text()
    n = len(config.all_teams())
    assert "-- Publish guard" in text and "vanished from this build: 0" in text
    assert f"{n} of {n} team files read" in text


def test_a_small_loss_publishes_and_the_coverage_report_lists_the_vanished_game(tmp_path: Path, monkeypatch):
    live = tmp_path / "live"
    _build(live, {FEVER: _five_fever_games()}, monkeypatch, None)
    with httpx.Client(transport=httpx.MockTransport(_serve(live))) as client:
        previous = REAL_FETCH_PREVIOUS_PUBLISH(BASE_URL, client=client)

    out = tmp_path / "next"
    _build(out, {FEVER: _five_fever_games()[:4]}, monkeypatch, previous)  # one of five gone
    text = (out / "COVERAGE.txt").read_text()
    assert "vanished, wnba/indiana-fever: G4 (Indiana Fever vs Chicago Sky" in text
    assert "vanished from this build: 1" in text


def test_an_empty_league_is_never_published_over_a_non_empty_one(tmp_path: Path, monkeypatch):
    """WNBA has upcoming games in the previous publish; this build finds games
    for NWSL only. The WNBA calendar would be empty: refused, though NWSL is fine."""
    live = tmp_path / "live"
    _build(live, {FEVER: _five_fever_games()}, monkeypatch, None)
    with httpx.Client(transport=httpx.MockTransport(_serve(live))) as client:
        previous = REAL_FETCH_PREVIOUS_PUBLISH(BASE_URL, client=client)
    nwsl_only = {"angel-city": [_raw("N1", opponent="Bay FC", days=12, home="Angel City")]}
    with pytest.raises(PublishRefused) as raised:
        _build(tmp_path / "next", nwsl_only, monkeypatch, previous)
    assert "WNBA (wnba) would publish an EMPTY calendar" in str(raised.value)
    assert not (tmp_path / "next").exists()


def test_a_build_with_no_previous_publish_read_says_it_was_not_compared(tmp_path: Path, monkeypatch):
    out = tmp_path / "out"
    _build(out, {FEVER: _five_fever_games()}, monkeypatch, None)
    assert "NOT COMPARED: the previous publish was not read" in (out / "COVERAGE.txt").read_text()


def test_a_degraded_build_has_no_guard_section(tmp_path: Path):
    """Nothing was fetched, so there is nothing to compare."""
    out = tmp_path / "out"
    coverage = build_module.build(out_dir=out, base_url=BASE_URL, api_key=None, affiliate_id=None)
    assert coverage.publish_guard is None
    assert "Publish guard" not in (out / "COVERAGE.txt").read_text()


def test_the_published_report_names_no_repository_file(tmp_path: Path):
    """COVERAGE.txt is public; guard messages that name repo paths belong in the run log only."""
    report = guard.GuardReport(compared=True, previous_fetched_at="x", teams_read=1, teams_configured=1)
    report.expired_overrides.append("the guard override for wnba expired on 2026-05-31 and no longer applies (x)")
    text = render_report(
        BuildCoverage(leagues=[], requests_made=0, bytes_received=0, api_key_present=True, publish_guard=report)
    )
    assert "docs/" not in text and "config.py" not in text and "ADR" not in text


# --- main(): the loud failure -----------------------------------------------------------------------------


def _main_with(monkeypatch, tmp_path: Path, previous: PreviousPublish, responses: dict[str, list[dict]]):
    monkeypatch.setattr(build_module, "DiscoveryClient", lambda api_key: _FakeDiscoveryClient(responses))
    monkeypatch.setattr(guard, "fetch_previous_publish", lambda base_url, **kwargs: previous)
    monkeypatch.setenv("TICKETMASTER_API_KEY", "fake-key")
    out = tmp_path / "dist"
    # main() uses the real clock; the previous games are placed relative to it.
    return build_module.main(["--out", str(out), "--base-url", BASE_URL, "--require-api-key"]), out


def _real_now_previous() -> PreviousPublish:
    soon = datetime.now(UTC)
    games = [PreviousGame(f"R{i}", f"Event R{i}", soon + timedelta(days=10 + i), None) for i in range(4)]
    return PreviousPublish(games={("wnba", FEVER): games}, fetched_at="2026-05-31T08:00:00+00:00")


def test_main_exits_nonzero_writes_nothing_and_says_what_and_why(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    other_league = {"angel-city": [_raw("N1", opponent="Bay FC", days=12, home="Angel City")]}
    rc, out = _main_with(monkeypatch, tmp_path, _real_now_previous(), other_league)
    err = capsys.readouterr().err
    assert rc == 1 and not out.exists()
    assert "BUILD FAILED: the publish guard refused this build" in err
    assert "wnba/indiana-fever" in err and "lost all 4" in err
    assert "the last good deploy" in err and "PUBLISH_GUARD_OVERRIDES" in err
    assert "::error" not in err


def test_main_under_github_actions_also_emits_an_error_annotation(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    other_league = {"angel-city": [_raw("N1", opponent="Bay FC", days=12, home="Angel City")]}
    rc, _out = _main_with(monkeypatch, tmp_path, _real_now_previous(), other_league)
    assert rc == 1
    assert "::error title=Publish guard refused the build::" in capsys.readouterr().err


def test_main_warns_when_the_previous_publish_could_not_be_read(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    unreadable = PreviousPublish()
    unreadable.unreadable[("wnba", FEVER)] = "HTTP 503"
    rc, out = _main_with(monkeypatch, tmp_path, unreadable, {FEVER: [_raw("G1", opponent="Chicago Sky", days=10)]})
    err = capsys.readouterr().err
    assert rc == 0 and out.exists()
    assert "WARNING: publish guard: NOT COMPARED with the previous publish" in err
    assert "NOT COMPARED" in (out / "COVERAGE.txt").read_text()


def test_the_data_files_this_guard_reads_carry_the_fields_it_relies_on(tmp_path: Path, monkeypatch):
    """The guard parses the published team JSON; if site_data ever renames
    one of these keys the guard would go blind, and this fails first."""
    out = tmp_path / "dist"
    _build(out, {FEVER: _five_fever_games()}, monkeypatch, None)
    team_json = json.loads((out / "data" / "wnba" / f"{FEVER}.json").read_text())
    assert team_json["fetched"] is True and team_json["fetched_at"]
    game = team_json["games"][0]
    for key in ("event_id", "event_name", "start_utc", "in_calendar_feed", "status"):
        assert key in game
