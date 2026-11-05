"""Empty WNBA team pages name the season they wait for, and seller-table
teams' meta descriptions match their page body (DECISIONS 0029)."""

from __future__ import annotations

from wsc_pipeline import config, site
from wsc_pipeline.site_data import team_data

from .fixture_site import BASE_URL
from .test_titles_descriptions import _away_games, _head

WNBA = config.league_by_slug("wnba")
PWHL = config.league_by_slug("pwhl")


def _team(league: config.League, slug: str) -> config.Team:
    return next(t for t in league.teams if t.slug == slug)


def _render(league, team, games, fetched_at: str | None = "2026-11-05T08:25:00+00:00", **kw) -> tuple[str, str, str]:
    html = site.render_team(team={**team_data(team, league, games, **kw), "fetched_at": fetched_at}, base_url=BASE_URL)
    return (*_head(html), html)


def test_an_empty_wnba_page_names_the_next_season_and_says_it_is_not_listed() -> None:
    title, description, html = _render(WNBA, _team(WNBA, "phoenix-mercury"), [])
    assert title == "Phoenix Mercury 2027 schedule: add it to your calendar"
    assert description.startswith("Phoenix Mercury 2027 schedule. Ticketmaster has not listed the 2027 schedule yet")
    assert "No upcoming games found from Ticketmaster right now." in html  # the body still says so
    assert '"SportsEvent"' not in html
    # Before October the empty page waits for this year's season.
    title, _, _ = _render(WNBA, _team(WNBA, "phoenix-mercury"), [], fetched_at="2027-03-01T08:00:00+00:00")
    assert title.startswith("Phoenix Mercury 2027 schedule")


def test_no_year_without_a_fetch_outside_the_wnba_or_for_a_seller_table_team() -> None:
    cases = [
        _render(WNBA, _team(WNBA, "phoenix-mercury"), [], fetched=False),
        _render(WNBA, _team(WNBA, "phoenix-mercury"), [], fetched_at=None),
        _render(PWHL, _team(PWHL, "boston-fleet"), []),
        _render(WNBA, _team(WNBA, "las-vegas-aces"), []),
    ]
    for title, description, _ in cases:
        assert "2027" not in title + description, title
    # The Aces sell on AXS: the description says so, as the body does, and
    # promises nothing about the calendar filling in.
    _, aces, html = cases[-1]
    assert "main ticket seller is AXS, not Ticketmaster" in aces and "games appear" not in aces
    assert "main ticket seller is AXS, not Ticketmaster" in html.split("</head>")[1]


def test_minnesota_frost_with_only_away_games_never_promises_every_home_game() -> None:
    frost = _team(PWHL, "minnesota-frost")
    _, description, html = _render(PWHL, frost, _away_games(PWHL, frost))
    assert "every home and away game" not in description
    assert "No home game is listed: the team's main ticket seller is SeatGeek." in description
    assert "Ticketmaster lists no upcoming Minnesota Frost home game" in html
    # Control: a team that sells on Ticketmaster keeps the old wording.
    fleet = _team(PWHL, "boston-fleet")
    assert "every home and away game" in _render(PWHL, fleet, _away_games(PWHL, fleet))[1]
