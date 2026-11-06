"""measure_gap.py on made-up pages and canned Discovery API responses (no network).

The HTML below copies only the shape of Wikipedia's schedule tables. Every
date and score is invented: no Wikipedia event data is committed
(DECISIONS 0034)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from wsc_pipeline import measure_gap
from wsc_pipeline.measure_gap import (
    FAILED,
    MEASURED,
    NO_PAGE,
    NO_TABLE,
    NOT_RUN,
    OVER_CAP,
    WikiGame,
    WikipediaClient,
    WikiSource,
    compare,
    main,
    measure,
    parse_cbb_team,
    parse_pwhl_season,
    render_markdown,
)
from wsc_pipeline.normalize import Game, normalize_event
from wsc_pipeline.ticketmaster import DiscoveryClient

from .conftest import make_raw_event

TODAY = date(2026, 11, 6)
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
SEASON = "2026–27 PWHL season"

PWHL_PAGE = """<html><body>
<h2>Preseason</h2>
<table class="wikitable"><tbody>
<tr><th>Date</th><th>Time</th><th>Visitor</th><th>Score</th><th>Home</th><th>OT</th><th>Location</th></tr>
<tr><td>November 20</td><td>7:00</td><td>Boston</td><td>–</td><td>Minnesota</td><td></td><td>Somewhere</td></tr>
</tbody></table>
<h2>Regular season</h2>
<table class="wikitable"><tbody>
<tr><th>Pos</th><th>Team</th><th>Pts</th></tr>
<tr><td>1</td><td>Minnesota Frost</td><td>0</td></tr>
</tbody></table>
<table class="wikitable"><tbody>
<tr><th>Date</th><th>Time</th><th>Visitor</th><th>Score</th><th>Home</th><th>OT</th><th>Notes</th><th>Recap</th></tr>
<tr><td>December 1</td><td>7:00</td><td><a href="#">Boston</a></td><td>–</td><td><a href="#">Minnesota</a></td>
<td></td><td></td><td></td></tr>
<tr><td>December 3</td><td>7:00</td><td>Minnesota</td><td>–</td><td>Boston</td><td></td><td></td><td></td></tr>
<tr><td>February 30</td><td>7:00</td><td>Boston</td><td>–</td><td>Minnesota</td><td></td><td></td><td></td></tr>
</tbody></table>
<table class="wikitable"><tbody>
<tr><th>Date</th><th>Time</th><th>Visitor</th><th>Score</th><th>Home</th><th>OT</th><th>Notes</th><th>Recap</th></tr>
<tr><td>January 9<sup>[1]</sup></td><td>2:00</td><td>Montreal</td><td>–</td><td>Minnesota</td><td></td><td></td><td></td></tr>
<tr><td>October 1</td><td>2:00</td><td>Montreal</td><td>–</td><td>Minnesota</td><td></td><td></td><td></td></tr>
</tbody></table>
<h2>Transactions</h2>
<table class="wikitable"><tbody>
<tr><th>Date</th><th>Visitor</th><th>Home</th></tr>
<tr><td>March 1</td><td>Boston</td><td>Minnesota</td></tr>
</tbody></table>
</body></html>"""

CBB_PAGE = """<html><body><h2>Schedule and results</h2>
<table class="wikitable"><tbody>
<tr><th>Date<br>time, TV</th><th>Rank #</th><th>Opponent #</th><th>Result</th><th>Site (attendance)<br>city, state</th></tr>
<tr><th colspan="5"><style>.x{color:red}</style>Regular season</th></tr>
<tr><td>November 10, 2026 * 7:00 p.m.</td><td></td><td>Example State</td><td></td>
<td>Home Arena<br>Hometown, ST</td></tr>
<tr><td>November 12, 2026 7:00 p.m.</td><td></td><td>at Road U</td><td></td><td>Far Arena<br>Away, ST</td></tr>
<tr><td>November 14, 2026 1:00 p.m.</td><td></td><td>vs. Neutral College</td><td></td><td>Big Dome<br>Elsewhere, ST</td></tr>
<tr><td>November 18, 2026 7:00 p.m.</td><td></td><td>No. 5 Ranked U</td><td></td><td>Home Arena<br>Hometown, ST</td></tr>
<tr><td>TBA</td><td></td><td>Mystery</td><td></td><td>Home Arena<br>Hometown, ST</td></tr>
<tr><td colspan="5">* Non-conference game.</td></tr>
</tbody></table></body></html>"""


def test_pwhl_page_counts_regular_season_home_rows_with_the_right_year() -> None:
    games = parse_pwhl_season(PWHL_PAGE, SEASON, "Minnesota")
    assert games is not None
    # Preseason, the standings table, Boston's home game, the impossible
    # date and the Transactions table are all left out.
    assert sorted(g.day for g in games) == [date(2026, 10, 1), date(2026, 12, 1), date(2027, 1, 9)]
    assert {g.opponent for g in games} == {"Boston", "Montreal"}
    assert all(g.site == "" for g in games)


def test_pwhl_page_without_a_schedule_table_is_not_zero_games() -> None:
    assert parse_pwhl_season("<h2>Regular season</h2><p>TBA</p>", SEASON, "Minnesota") is None
    assert parse_pwhl_season(PWHL_PAGE, "PWHL season", "Minnesota") is None
    # A recognized table with no home rows is a real 0.
    assert parse_pwhl_season(PWHL_PAGE, SEASON, "Nowhere") == []


def test_college_page_counts_only_home_rows() -> None:
    games = parse_cbb_team(CBB_PAGE)
    assert games == [
        WikiGame(day=date(2026, 11, 10), opponent="Example State", site="Home Arena Hometown, ST"),
        WikiGame(day=date(2026, 11, 18), opponent="Ranked U", site="Home Arena Hometown, ST"),
    ]


def test_college_page_without_a_schedule_table_is_none() -> None:
    assert parse_cbb_team("<table class='wikitable'><tr><th>Name</th></tr></table>") is None
    assert parse_cbb_team("<p>No table</p>") is None
    # A table that is not a wikitable is not read.
    assert parse_cbb_team(CBB_PAGE.replace("wikitable", "infobox")) is None


def _game(
    name: str, day: str, *, venue: str = "Home Arena", city: str = "Hometown", slug: str = "minnesota-frost"
) -> Game:
    raw = make_raw_event(
        event_id=f"{name}-{day}",
        name=name,
        date_time=f"{day}T23:00:00Z",
        local_date=day,
        venue_name=venue,
        venue_city=city,
    )
    game = normalize_event(raw, league_slug="pwhl", tracked_team_slug=slug, tracked_team_name="Minnesota Frost")
    assert game is not None
    return game


def test_compare_pairs_by_opponent_and_checks_date_and_venue() -> None:
    wiki = [
        WikiGame(date(2026, 12, 1), "Boston", ""),  # same date, no venue to compare
        WikiGame(date(2026, 12, 10), "Montreal", ""),  # Ticketmaster says a day later
        WikiGame(date(2026, 12, 20), "Example State", "Home Arena Hometown, ST"),  # venue agrees by city
        WikiGame(date(2026, 12, 22), "Ranked U", "Other Hall Faraway, ST"),  # venue disagrees
        WikiGame(date(2026, 12, 24), "Nobody", ""),  # Ticketmaster has no such game
        WikiGame(date(2027, 1, 30), "Boston", ""),  # too far from any Boston game
    ]
    tm = [
        _game("Minnesota Frost vs Boston Fleet", "2026-12-01"),
        _game("Minnesota Frost vs La Victoire De Montréal", "2026-12-11"),
        _game("Minnesota Frost vs Example State", "2026-12-20", venue="Renamed Center"),
        _game("Minnesota Frost vs Ranked U", "2026-12-22", venue="Home Arena"),
        _game("Minnesota Frost vs Boston Fleet", "2027-01-15"),
    ]
    out = compare(wiki, tm)
    assert (out.shared, out.date_agree, out.venue_compared, out.venue_agree, out.agree) == (4, 3, 2, 1, 2)


def test_compare_uses_each_ticketmaster_game_once() -> None:
    wiki = [WikiGame(date(2026, 12, 1), "Boston", ""), WikiGame(date(2026, 12, 2), "Boston", "")]
    out = compare(wiki, [_game("Minnesota Frost vs Boston Fleet", "2026-12-02")])
    assert out.shared == 1


def _wiki_client(pages: dict[str, tuple[int, str]]) -> tuple[WikipediaClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        for title, (status, body) in pages.items():
            if request.url == httpx.URL(WikipediaClient.url_for(title)):
                return httpx.Response(status, text=body)
        return httpx.Response(404, text="missing")

    http = httpx.Client(transport=httpx.MockTransport(handler), headers={"User-Agent": measure_gap.WIKI_USER_AGENT})
    return WikipediaClient(client=http, min_interval=0.0), seen


def test_wikipedia_client_reads_article_pages_once_with_an_honest_user_agent() -> None:
    client, seen = _wiki_client({SEASON: (200, PWHL_PAGE)})
    assert client.page(SEASON) == (MEASURED, PWHL_PAGE)
    assert client.page(SEASON) == (MEASURED, PWHL_PAGE)
    assert len(seen) == 1 and client.requests_made == 1
    url = str(seen[0].url)
    # robots.txt disallows /w/ and /api/ (including /api/rest_v1/) for every
    # user agent; article pages under /wiki/ are allowed.
    assert url.startswith("https://en.wikipedia.org/wiki/2026%E2%80%9327_PWHL_season")
    assert "/w/" not in url and "/api/" not in url
    assert measure_gap.WIKI_BASE == "https://en.wikipedia.org/wiki/"
    ua = seen[0].headers["User-Agent"]
    assert "nexthomegame.com" in ua and "@" in ua


def test_default_client_sends_the_user_agent() -> None:
    with WikipediaClient() as client:
        assert client._client.headers["User-Agent"] == measure_gap.WIKI_USER_AGENT


def test_wikipedia_client_reports_missing_failed_and_capped_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _wiki_client({"Broken": (503, "busy")})
    assert client.page("Does not exist") == (NO_PAGE, None)
    assert client.page("Broken") == (FAILED, None)
    monkeypatch.setattr(measure_gap, "WIKI_MAX_REQUESTS", 2)
    assert client.page("Third title") == (OVER_CAP, None)


def test_wikipedia_client_network_error_is_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    client = WikipediaClient(client=httpx.Client(transport=httpx.MockTransport(handler)), min_interval=0.0)
    assert client.page(SEASON) == (FAILED, None)


def test_wikipedia_client_waits_between_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr(measure_gap.time, "sleep", slept.append)
    client, _ = _wiki_client({})
    client._min_interval = 3.0
    client.page("A")
    client.page("B")
    assert len(slept) == 1 and 0 < slept[0] <= 3.0


# Ticketmaster responses by search keyword.
TM_RESPONSES: dict[str, list[dict[str, Any]]] = {
    "Minnesota Frost": [
        make_raw_event(event_id="F1", name="Minnesota Frost vs Boston Fleet", local_date="2026-12-01"),
        make_raw_event(event_id="F2", name="Boston Fleet vs Minnesota Frost", local_date="2026-12-03"),
        make_raw_event(event_id="F0", name="Minnesota Frost vs Boston Fleet", local_date="2026-10-01"),
    ],
    "Boston Fleet": [
        make_raw_event(event_id="F2", name="Boston Fleet vs Minnesota Frost", local_date="2026-12-03"),
    ],
}


def _tm_client(fail_on: set[str] | None = None) -> DiscoveryClient:
    def handler(request: httpx.Request) -> httpx.Response:
        keyword = request.url.params["keyword"]
        if fail_on and keyword in fail_on:
            return httpx.Response(500, text="upstream error")
        events = TM_RESPONSES.get(keyword, [])
        body: dict[str, Any] = {"page": {"totalPages": 1, "totalElements": len(events)}}
        if events:
            body["_embedded"] = {"events": events}
        return httpx.Response(200, json=body)

    return DiscoveryClient(
        "fake-key", client=httpx.Client(transport=httpx.MockTransport(handler)), min_interval=0.0, max_retries=1
    )


SOURCES = (
    WikiSource("pwhl", "minnesota-frost", SEASON, "pwhl-season", "Minnesota", gap_team=True),
    WikiSource("pwhl", "boston-fleet", SEASON, "pwhl-season", "Boston"),
    WikiSource(
        "ncaaw-big-ten",
        "minnesota-golden-gophers-womens-basketball",
        "2026–27 Made Up team",
        "cbb-team",
        gap_team=True,
    ),
)


def test_measure_counts_gap_and_agreement() -> None:
    wiki, seen = _wiki_client({SEASON: (200, PWHL_PAGE)})
    report = measure(wiki, _tm_client(), TODAY, generated_at=NOW, sources=SOURCES)
    assert len(seen) == 2  # one request per title, the season page shared
    frost, boston, gophers = report["teams"]
    # Wikipedia: Dec 1 and Jan 9 (Oct 1 is past). Ticketmaster: Dec 1.
    assert (frost["wikipedia_home"], frost["ticketmaster_home"], frost["missing"]) == (2, 1, 1)
    assert (frost["shared"], frost["agree"]) == (1, 1)
    assert (boston["wikipedia_home"], boston["ticketmaster_home"], boston["missing"]) == (1, 1, 0)
    assert boston["agree"] == 1
    # The college page does not exist: not measured, never 0.
    assert gophers["wikipedia_status"] == NO_PAGE
    assert gophers["wikipedia_home"] is None and gophers["missing"] is None
    assert gophers["ticketmaster_home"] == 0 and gophers["ticketmaster_status"] == MEASURED
    assert (report["shared_games"], report["agreeing_games"], report["agreement"]) == (2, 2, 1.0)
    assert report["meets_bar"] is True
    assert (report["gap_teams_measured"], report["gap_teams_total"], report["gap_missing_total"]) == (1, 2, 1)


def test_measure_without_ticketmaster_leaves_every_comparison_unmeasured() -> None:
    wiki, _ = _wiki_client({SEASON: (200, PWHL_PAGE), "2026–27 Made Up team": (200, "<p>stub</p>")})
    report = measure(wiki, None, TODAY, generated_at=NOW, sources=SOURCES)
    assert report["ticketmaster_requests"] is None
    assert all(t["ticketmaster_status"] == NOT_RUN and t["ticketmaster_home"] is None for t in report["teams"])
    assert report["teams"][2]["wikipedia_status"] == NO_TABLE
    assert report["agreement"] is None and report["meets_bar"] is None and report["gap_missing_total"] is None
    md = render_markdown(report)
    assert "bar: not measured" in md and "| – |" in md


def test_ticketmaster_failure_and_cap_are_not_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    wiki, _ = _wiki_client({SEASON: (200, PWHL_PAGE)})
    report = measure(wiki, _tm_client(fail_on={"Minnesota Frost"}), TODAY, generated_at=NOW, sources=SOURCES[:2])
    assert report["teams"][0]["ticketmaster_status"] == FAILED
    assert report["teams"][0]["ticketmaster_home"] is None
    monkeypatch.setattr(measure_gap, "TM_MAX_REQUESTS", 0)
    wiki, _ = _wiki_client({SEASON: (200, PWHL_PAGE)})
    report = measure(wiki, _tm_client(), TODAY, generated_at=NOW, sources=SOURCES[:1])
    assert report["teams"][0]["ticketmaster_status"] == OVER_CAP


def test_markdown_reports_a_missed_bar() -> None:
    report = {
        "generated_at": NOW.isoformat(),
        "counted_from": TODAY.isoformat(),
        "wikipedia_requests": 1,
        "ticketmaster_requests": 2,
        "agreement_bar": 0.95,
        "shared_games": 10,
        "agreeing_games": 9,
        "agreement": 0.9,
        "meets_bar": False,
        "gap_teams_measured": 0,
        "gap_teams_total": 0,
        "gap_missing_total": None,
        "teams": [],
    }
    assert "9 of 10 (90.0%); bar 95%: not met" in render_markdown(report)


def test_every_source_names_a_tracked_team_and_an_article_title() -> None:
    for s in measure_gap.WIKI_SOURCES:
        league, team = measure_gap._team(s)
        assert league.slug == s.league_slug
        assert team.slug == s.team_slug
        assert s.kind in ("pwhl-season", "cbb-team")
        assert s.title.startswith("2026–27 ")
        assert s.kind != "pwhl-season" or s.wiki_name
    assert sum(s.gap_team for s in measure_gap.WIKI_SOURCES) == 9


def test_main_writes_counts_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(measure_gap, "WIKI_SOURCES", SOURCES)
    monkeypatch.setattr(measure_gap, "measure", _measure_with(SOURCES))
    wiki, _ = _wiki_client({SEASON: (200, PWHL_PAGE)})
    assert main(["--out", str(tmp_path / "out")], wiki=wiki, tm=_tm_client()) == 0
    written = (tmp_path / "out" / "gap.md").read_text() + (tmp_path / "out" / "gap.json").read_text()
    assert summary.read_text().strip() == (tmp_path / "out" / "gap.md").read_text().strip()
    json.loads((tmp_path / "out" / "gap.json").read_text())
    # No date, opponent or venue from either source is written.
    for leaked in ("2026-12-01", "December", "Montreal", "Gainbridge", "Indianapolis", "F1", "ticketmaster.com/event"):
        assert leaked not in written, leaked


def _measure_with(sources: tuple[WikiSource, ...]) -> Any:
    real = measure

    def run(wiki: WikipediaClient, tm: DiscoveryClient | None, today: date, *, generated_at: datetime) -> Any:
        return real(wiki, tm, today, generated_at=generated_at, sources=sources)

    return run


def test_main_needs_a_key_unless_wikipedia_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TICKETMASTER_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert main(["--out", str(tmp_path)]) == 2
    monkeypatch.setattr(measure_gap, "measure", _measure_with(SOURCES))
    wiki, _ = _wiki_client({SEASON: (503, "busy")})
    # A failed page still writes every count, then fails the run.
    assert main(["--out", str(tmp_path), "--wikipedia-only"], wiki=wiki) == 1
    assert (tmp_path / "gap.json").exists()


def test_main_builds_a_ticketmaster_client_from_the_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TICKETMASTER_API_KEY", "fake-key")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    made: list[str] = []

    def fake_client(key: str) -> DiscoveryClient:
        made.append(key)
        return _tm_client()

    monkeypatch.setattr(measure_gap, "DiscoveryClient", fake_client)
    monkeypatch.setattr(measure_gap, "measure", _measure_with(SOURCES))
    wiki, _ = _wiki_client({SEASON: (200, PWHL_PAGE)})
    assert main(["--out", str(tmp_path)], wiki=wiki) == 0
    assert made == ["fake-key"]
