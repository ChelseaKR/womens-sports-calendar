"""The /schedule/ page (#35): every tracked league's games, day by day.

What it must never do is render an absence as a value: an unfetched build
is not "no games", a time-TBA game gets no invented time, a game whose teams
were not parsed is not "TBD vs TBD", and a static page built at night never
calls a date "today".
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from wsc_pipeline import build as build_module
from wsc_pipeline import config, site, site_data
from wsc_pipeline.normalize import Game, normalize_event

from .conftest import make_raw_event

BUILD = datetime(2026, 10, 1, 8, 13, 0, tzinfo=UTC)  # a nightly build: Thursday, October 1
WNBA = config.LEAGUES[0]
NWSL = next(lg for lg in config.LEAGUES if lg.slug == "nwsl")


def _game(event_id: str, name: str, *, league: config.League = WNBA, team: config.Team | None = None, **kw) -> Game:
    team = team or league.teams[0]
    game = normalize_event(
        make_raw_event(event_id=event_id, name=name, url=f"https://www.ticketmaster.com/event/{event_id}", **kw),
        league_slug=league.slug,
        tracked_team_slug=team.slug,
        tracked_team_name=team.name,
    )
    assert game is not None
    return game


def _by_league(*games: Game) -> dict[str, list[Game]]:
    out: dict[str, list[Game]] = {lg.slug: [] for lg in config.LEAGUES}
    for g in games:
        out[g.league_slug].append(g)
    return out


def _render(games_by_league, *, fetched: bool = True, fetched_at: datetime | None = BUILD, incomplete=frozenset()):
    payload = site_data.schedule_data(
        list(config.LEAGUES),
        games_by_league,
        fetched=fetched,
        fetched_at=fetched_at,
        possibly_incomplete_leagues=set(incomplete),
    )
    payload.update(site_data.provenance(fetched_at if fetched else None))
    leagues = [{"slug": lg.slug, "name": lg.name} for lg in config.LEAGUES]
    return payload, site.render_schedule(schedule=payload, leagues=leagues, base_url="https://nexthomegame.com")


def _populated() -> dict[str, list[Game]]:
    fever = WNBA.teams[0]
    return _by_league(
        _game(
            "TIMED",
            f"{fever.name} vs Seattle Storm",
            date_time="2026-10-01T23:00:00Z",
            local_date="2026-10-01",
            local_time="19:00:00",
            timezone="America/New_York",
        ),
        _game(
            "TBA",
            f"{fever.name} vs Las Vegas Aces",
            date_time=None,
            local_date="2026-10-03",
            local_time=None,
            time_tba=True,
        ),
        # Ticketmaster's date-TBD placeholder: a date inside the window that is not real.
        _game(
            "DATE-TBD",
            f"{fever.name} vs Dallas Wings",
            date_time=None,
            local_date="2026-10-02",
            local_time=None,
            date_tbd=True,
        ),
        _game(
            "NO-VS",
            f"{fever.name} Fan Fest",
            date_time="2026-10-02T16:00:00Z",
            local_date="2026-10-02",
            local_time="12:00:00",
        ),
        _game(
            "LAST-DAY",
            f"{fever.name} vs Chicago Sky",
            date_time="2026-10-07T23:00:00Z",
            local_date="2026-10-07",
            local_time="19:00:00",
        ),
        _game(
            "TOO-LATE",
            f"{fever.name} vs Atlanta Dream",
            date_time="2026-10-08T23:00:00Z",
            local_date="2026-10-08",
            local_time="19:00:00",
        ),
        _game(
            "YESTERDAY",
            f"{fever.name} vs Phoenix Mercury",
            date_time="2026-10-01T00:00:00Z",
            local_date="2026-09-30",
            local_time="20:00:00",
        ),
        _game(
            "NWSL-1",
            f"{NWSL.teams[0].name} vs Orlando Pride",
            league=NWSL,
            date_time="2026-10-01T20:00:00Z",
            local_date="2026-10-01",
            local_time="16:00:00",
        ),
    )


def test_an_unfetched_build_says_so_and_never_says_there_are_no_games():
    payload, html = _render(_by_league(), fetched=False, fetched_at=None)
    assert payload["days"] == [] and payload["first_day"] is None
    assert site.NOT_FETCHED_MSG in html
    assert "lists no games" not in html and "No games" not in html
    assert "Listings as of" not in html  # no fetch time to state


def test_a_fetched_week_with_nothing_listed_names_the_dates_it_checked():
    _payload, html = _render(_by_league())
    assert (
        "Ticketmaster lists no games for any tracked league from Thursday, October 1 through Wednesday, October 7."
        in html
    )
    assert site.NOT_FETCHED_MSG not in html


def test_days_are_named_by_date_and_never_called_today():
    payload, html = _render(_populated())
    assert [d["date"] for d in payload["days"]] == ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-07"]
    for label in ("Thursday, October 1", "Friday, October 2", "Saturday, October 3", "Wednesday, October 7"):
        assert f">{label}</h2>" in html
    assert "today" not in html.lower()
    assert "Listings as of" in html  # the fetch time is stated, so a stale page shows its age


def test_the_window_is_seven_days_from_the_build_and_skips_undated_games():
    payload, _html = _render(_populated())
    listed = {g["event_id"] for d in payload["days"] for g in d["games"]}
    assert listed == {"TIMED", "NWSL-1", "NO-VS", "TBA", "LAST-DAY"}  # not TOO-LATE, YESTERDAY or DATE-TBD


def test_a_time_tba_game_shows_no_time():
    payload, html = _render(_populated())
    tba = next(g for d in payload["days"] for g in d["games"] if g["event_id"] == "TBA")
    assert tba["start_display"] == "Sat, Oct 3, 2026 (time TBA)"
    assert '<time datetime="2026-10-03">Sat, Oct 3, 2026 (time TBA)</time>' in html


def test_a_game_without_two_parsed_teams_shows_its_listing_name_not_tbd():
    _payload, html = _render(_populated())
    assert f"{WNBA.teams[0].name} Fan Fest" in html
    assert "TBD vs" not in html and "vs TBD" not in html


def test_a_day_lists_its_games_soonest_first_across_leagues():
    payload, html = _render(_populated())
    first_day = payload["days"][0]
    assert [g["event_id"] for g in first_day["games"]] == ["NWSL-1", "TIMED"]  # 20:00Z before 23:00Z
    assert f'<a href="/nwsl/">{NWSL.name}</a>' in html


def test_the_build_date_is_taken_in_us_eastern_time():
    late_evening = datetime(2026, 10, 2, 2, 0, tzinfo=UTC)  # 10 PM Eastern on October 1
    payload, _html = _render(_by_league(), fetched_at=late_evening)
    assert payload["first_day"] == "2026-10-01"


def test_a_possibly_incomplete_league_is_said():
    _payload, html = _render(_populated(), incomplete={"wnba"})
    assert f"more matching listings for {WNBA.name} than this build reads" in html


def test_a_game_two_tracked_teams_share_is_listed_once():
    storm = next(t for t in WNBA.teams if t.slug == "seattle-storm")
    kw = {"date_time": "2026-10-01T23:00:00Z", "local_date": "2026-10-01", "local_time": "19:00:00"}
    a = _game("H2H", f"{WNBA.teams[0].name} vs Seattle Storm", **kw)
    b = _game("H2H", f"{WNBA.teams[0].name} vs Seattle Storm", team=storm, **kw)
    payload, _html = _render(_by_league(a, b))
    assert [g["event_id"] for d in payload["days"] for g in d["games"]] == ["H2H"]


def test_the_build_writes_the_page_and_lists_it_in_the_sitemap(tmp_path: Path, monkeypatch):
    games = [g for gs in _populated().values() for g in gs]
    empty = {lg.slug: set() for lg in config.LEAGUES}
    monkeypatch.setattr(build_module, "fetch_all_games", lambda api_key: (games, empty, empty, 1, 1))
    out = tmp_path / "dist"
    build_module.build(out_dir=out, base_url="https://nexthomegame.com", api_key="k", affiliate_id=None)
    html = (out / "schedule" / "index.html").read_text(encoding="utf-8")
    assert "<h1>The week ahead in every league</h1>" in html
    assert "<loc>https://nexthomegame.com/schedule/</loc>" in (out / "sitemap.xml").read_text(encoding="utf-8")
    assert '"/schedule/"' in (out / "lastmod.json").read_text(encoding="utf-8")
    assert f'href="{site.SCHEDULE_PATH}"' in (out / "index.html").read_text(encoding="utf-8")
