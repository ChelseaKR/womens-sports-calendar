"""measure_leagues.py on canned Discovery API responses (no network)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

import httpx
import pytest

from wsc_pipeline import config, measure_leagues
from wsc_pipeline.measure_leagues import (
    CANDIDATES,
    FAILED,
    OVER_CAP,
    Candidate,
    main,
    measure,
    measure_candidate,
    render_markdown,
)
from wsc_pipeline.ticketmaster import DiscoveryClient

from .conftest import make_raw_event

API_KEY = "fake-key"
TODAY = date(2026, 11, 2)
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)

KENTUCKY = "Kentucky Wildcats Womens Basketball"
KANSAS = "Kansas Jayhawks Womens Basketball"


def _event(event_id: str, name: str, day: str = "2026-12-01", **kw: Any) -> dict[str, Any]:
    return make_raw_event(
        event_id=event_id,
        name=name,
        date_time=f"{day}T00:00:00Z",
        local_date=day,
        url=f"https://www.ticketmaster.com/event/{event_id}",
        **kw,
    )


# keyword -> events the fake API returns for it
RESPONSES: dict[str, list[dict[str, Any]]] = {
    KENTUCKY: [
        _event("K-HOME", "Kentucky Wildcats Womens Basketball vs Tennessee Lady Volunteers Womens Basketball"),
        _event("K-AWAY", "Louisville Women's Basketball vs Kentucky Women's Basketball"),
        _event("K-PAST", "Kentucky Women's Basketball vs Ole Miss Women's Basketball", day="2026-10-01"),
        # keyword false positives the site drops
        _event("K-NKU", "Northern Kentucky Women's Basketball vs Xavier Women's Basketball"),
        _event("K-MENS", "Kentucky Wildcats Mens Basketball vs Duke Blue Devils Mens Basketball"),
    ],
    KANSAS: [
        _event("A-ARK", "Arkansas Women's Basketball vs Tulsa Women's Basketball"),
        _event("A-KU", "Kansas Women's Basketball vs Kentucky Women's Basketball"),
    ],
    "Rose BC": [_event("U-1", "Rose BC vs Vinyl BC", day="2027-01-09")],
    "Vinyl BC": [_event("U-1", "Rose BC vs Vinyl BC", day="2027-01-09")],
    "Unrivaled": [
        _event("U-1", "Rose BC vs Vinyl BC", day="2027-01-09"),
        _event("U-STOP", "Unrivaled Boston", day="2027-01-08"),
    ],
}


def _client(fail_on: set[str] | None = None) -> tuple[DiscoveryClient, list[str]]:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        keyword = request.url.params["keyword"]
        seen.append(keyword)
        if fail_on and keyword in fail_on:
            return httpx.Response(500, text=f"upstream error for {request.url}")
        events = RESPONSES.get(keyword, [])
        body: dict[str, Any] = {"page": {"totalPages": 1, "totalElements": len(events)}}
        if events:
            body["_embedded"] = {"events": events}
        return httpx.Response(200, json=body)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    return DiscoveryClient(API_KEY, client=http, min_interval=0.0, max_retries=1), seen


def _candidate(slug: str, teams: tuple[config.Team, ...], **kw: Any) -> Candidate:
    return Candidate(config.League(slug=slug, name=slug, country_codes=("US",), teams=teams), **kw)


def _college(*schools: tuple[str, str]) -> tuple[config.Team, ...]:
    return measure_leagues._college_teams(dict(schools))


def test_counts_only_what_the_site_would_attribute() -> None:
    client, _ = _client()
    result = measure_candidate(client, _candidate("sec", _college(("Kentucky", "Wildcats"))), TODAY)
    (team,) = result.teams
    assert team.status == "measured"
    assert team.events_returned == 5
    # Northern Kentucky and the men's game are dropped, as the site drops them.
    assert team.attributed == 3
    assert team.attributed_upcoming == 2  # K-PAST is before TODAY
    # Only K-HOME: site_data.tracked_team_is_home recognizes the keyword name,
    # not the "Kentucky Women's Basketball" title name, as the home side.
    assert team.home_games == 1
    assert team.truncated is False
    assert result.unique_attributed == 3
    assert result.unique_attributed_upcoming == 2
    assert result.teams_with_upcoming == 1
    assert result.complete is True


def test_northern_kentucky_is_kentucky_without_the_collision_list() -> None:
    """Control: the directional exclusion is what drops K-NKU."""
    client, _ = _client()
    bare = config.Team(slug="ky", name=KENTUCKY, title_name="Kentucky women's basketball")
    result = measure_candidate(client, _candidate("sec", (bare,)), TODAY)
    assert result.teams[0].attributed == 4


def test_kansas_does_not_take_arkansas_games() -> None:
    client, _ = _client()
    result = measure_candidate(client, _candidate("b12", _college(("Kansas", "Jayhawks"))), TODAY)
    assert result.teams[0].events_returned == 2
    assert result.teams[0].attributed == 1


def test_a_game_between_two_candidate_teams_counts_once_and_league_keyword_is_counted() -> None:
    client, _ = _client()
    teams = measure_leagues._pro_teams("Rose BC", "Vinyl BC")
    result = measure_candidate(client, _candidate("unrivaled", teams, league_keyword="Unrivaled"), TODAY)
    assert [t.attributed for t in result.teams] == [1, 1]
    assert result.unique_attributed == 1
    assert result.league_keyword_status == "measured"
    assert result.league_keyword_events == 2
    assert result.league_keyword_attributed == 1  # the tour-stop event names no team


def test_a_failed_fetch_is_failed_not_zero_and_never_shows_the_key(capsys: pytest.CaptureFixture[str]) -> None:
    client, _ = _client(fail_on={KANSAS})
    teams = _college(("Kentucky", "Wildcats"), ("Kansas", "Jayhawks"))
    result = measure_candidate(client, _candidate("x", teams), TODAY)
    failed = result.teams[1]
    assert failed.status == FAILED
    assert failed.events_returned is None and failed.attributed is None
    assert result.complete is False
    assert result.unique_attributed == 3  # the measured team's count stands
    assert API_KEY not in capsys.readouterr().err


def test_request_cap_skips_instead_of_counting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(measure_leagues, "MAX_REQUESTS", 1)
    client, seen = _client()
    teams = _college(("Kentucky", "Wildcats"), ("Kansas", "Jayhawks"))
    result = measure_candidate(client, _candidate("x", teams, league_keyword="Unrivaled"), TODAY)
    assert seen == [KENTUCKY]
    assert result.teams[1].status == OVER_CAP
    assert result.teams[1].attributed is None
    assert result.league_keyword_status == OVER_CAP


def test_unmeasured_teams_render_as_a_dash_not_zero() -> None:
    client, _ = _client()
    cand = _candidate("mlv", measure_leagues._pro_teams("Rose BC"), unmeasured_teams={"Minnesota": "no name yet"})
    report = measure(client, (cand,), TODAY, generated_at=NOW)
    c = report["candidates"][0]
    assert c["teams_total"] == 2
    assert c["complete"] is False
    md = render_markdown(report)
    assert "| Minnesota | – | – | – | – | – | not measured: no name yet |" in md
    assert "Teams measured: 1 of 2 (incomplete" in md


def test_nothing_measured_gives_no_totals() -> None:
    client, _ = _client(fail_on={"Rose BC"})
    result = measure_candidate(client, _candidate("u", measure_leagues._pro_teams("Rose BC")), TODAY)
    assert result.unique_attributed is None
    assert result.teams_with_upcoming is None
    assert "Unique attributed events: –, upcoming: –" in "\n".join(
        measure_leagues._candidate_markdown(
            json.loads(json.dumps(measure_leagues.asdict(result)))  # same shape main() renders
        )
    )


def test_main_writes_counts_only(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    sec = _candidate("ncaaw-sec", _college(("Kentucky", "Wildcats")))
    monkeypatch.setattr(measure_leagues, "CANDIDATES", (sec,))
    client, _ = _client()
    assert main(["--out", str(tmp_path / "out"), "--candidates", "ncaaw-sec"], client=client) == 0
    text = (tmp_path / "out" / "measure.json").read_text() + (tmp_path / "out" / "measure.md").read_text()
    text += summary.read_text()
    data = json.loads((tmp_path / "out" / "measure.json").read_text())
    assert data["candidates"][0]["teams"][0]["attributed"] == 3
    assert data["requests_made"] == 1
    # No event id, name, URL, venue or key in anything written.
    for forbidden in ("K-HOME", "Tennessee", "ticketmaster.com/event", "Gainbridge", "Indianapolis", API_KEY):
        assert forbidden not in text


def test_main_fails_after_writing_when_a_fetch_failed(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(measure_leagues, "CANDIDATES", (_candidate("u", measure_leagues._pro_teams("Rose BC")),))
    client, _ = _client(fail_on={"Rose BC"})
    assert main(["--out", str(tmp_path)], client=client) == 1
    assert json.loads((tmp_path / "measure.json").read_text())["candidates"][0]["teams"][0]["status"] == FAILED


def test_main_fails_when_the_league_keyword_fetch_failed(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    cand = _candidate("u", measure_leagues._pro_teams("Rose BC"), league_keyword="Unrivaled")
    monkeypatch.setattr(measure_leagues, "CANDIDATES", (cand,))
    client, _ = _client(fail_on={"Unrivaled"})
    assert main(["--out", str(tmp_path)], client=client) == 1


def test_main_refuses_without_a_key_or_with_an_unknown_candidate(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TICKETMASTER_API_KEY", raising=False)
    assert main(["--out", str(tmp_path)]) == 2
    assert main(["--out", str(tmp_path), "--candidates", "nope"]) == 2
    assert not (tmp_path / "measure.json").exists()


def test_selecting_all_and_a_subset() -> None:
    assert measure_leagues._select("all") == CANDIDATES
    assert measure_leagues._select(" ") == CANDIDATES
    assert [c.league.slug for c in measure_leagues._select("lovb, mlv")] == ["lovb", "mlv"]


def test_candidate_registry_is_sound() -> None:
    tracked = {lg.slug for lg in config.LEAGUES}
    slugs = [c.league.slug for c in CANDIDATES]
    assert len(slugs) == len(set(slugs))
    # The SEC and the Big Ten are tracked; they stay candidates so the
    # workflow can re-measure the rosters the site ships, and they are those.
    assert tracked & set(slugs) == {"ncaaw-sec", "ncaaw-big-ten"}
    for slug in ("ncaaw-sec", "ncaaw-big-ten"):
        assert next(c for c in CANDIDATES if c.league.slug == slug).league is config.league_by_slug(slug)
    assert set(slugs) == {
        "ncaaw-sec",
        "ncaaw-big-ten",
        "ncaaw-acc",
        "ncaaw-big-12",
        "ncaaw-big-east",
        "mlv",
        "unrivaled",
        "lovb",
    }
    sizes = {c.league.slug: len(c.league.teams) + len(c.unmeasured_teams) for c in CANDIDATES}
    assert sizes == {
        "ncaaw-sec": 16,
        "ncaaw-big-ten": 18,
        "ncaaw-acc": 18,
        "ncaaw-big-12": 16,
        "ncaaw-big-east": 11,
        "mlv": 12,
        "unrivaled": 8,
        "lovb": 10,
    }
    for c in CANDIDATES:
        team_slugs = [t.slug for t in c.league.teams]
        assert len(team_slugs) == len(set(team_slugs))
        assert c.source
        if c.league.slug.startswith("ncaaw-"):
            assert all(t.name.endswith(" Womens Basketball") and t.title_name for t in c.league.teams)
