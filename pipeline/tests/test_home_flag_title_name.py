"""A Big Ten home game billed under the school's title name is a home game.

The build accepts a game for a team through its title name (Team.match_names,
#64), but the home flag read only Team.all_names. The live build of
2026-11-02 listed "Nebraska Women's Basketball vs San Jose State - TIME
SUBJECT TO CHANGE" (Z7r9jZ1AAvg3e, Pinnacle Bank Arena) on Nebraska's page
with no home flag, so it was missing from the Big Ten and combined home-game
feeds. The title name counts only at the start of a side: as a plain phrase
"Michigan women's basketball" is inside "Western Michigan Women's Basketball".
"""

from __future__ import annotations

import pytest

from wsc_pipeline import config, feeds, site_data
from wsc_pipeline.config import league_by_slug
from wsc_pipeline.normalize import Game, normalize_event, side_begins_with

from .conftest import make_raw_event

LEAGUE = "ncaaw-big-ten"
NEBRASKA_LIVE = "Nebraska Women's Basketball vs San Jose State - TIME SUBJECT TO CHANGE"


def _team(slug: str) -> config.Team:
    return next(t for t in league_by_slug(LEAGUE).teams if t.slug == slug)


def _game(team: config.Team, name: str, event_id: str = "Z7r9jZ1AAvg3e") -> Game:
    raw = make_raw_event(
        event_id=event_id,
        name=name,
        date_time="2026-11-02T18:00:00Z",
        local_date="2026-11-02",
        local_time="12:00:00",
        venue_name="Pinnacle Bank Arena",
        venue_city="Lincoln",
        venue_state="NE",
        timezone="America/Chicago",
    )
    game = normalize_event(raw, league_slug=LEAGUE, tracked_team_slug=team.slug, tracked_team_name=team.name)
    assert game is not None
    return game


def test_the_live_title_name_event_is_a_home_game():
    nebraska = _team("nebraska-cornhuskers-womens-basketball")
    game = _game(nebraska, NEBRASKA_LIVE)
    assert game.home_team == "Nebraska Women's Basketball" and game.home_away_known
    assert site_data.tracked_team_is_home(nebraska, game) is True


def test_it_is_in_the_home_game_feeds():
    nebraska = _team("nebraska-cornhuskers-womens-basketball")
    games = {lg.slug: [] for lg in config.LEAGUES}
    games[LEAGUE] = [_game(nebraska, NEBRASKA_LIVE)]
    out = feeds.build_feeds(games, base_url="https://nexthomegame.com", fetched=True)
    assert "Z7r9jZ1AAvg3e" in out[LEAGUE]
    assert "Z7r9jZ1AAvg3e" in out[feeds.ALL_KEY]
    payload = site_data.team_data(nebraska, league_by_slug(LEAGUE), games[LEAGUE])
    assert payload["next_home_event_id"] == "Z7r9jZ1AAvg3e"


def test_an_away_game_under_the_opponents_title_name_stays_away():
    nebraska = _team("nebraska-cornhuskers-womens-basketball")
    game = _game(nebraska, "Iowa Women's Basketball vs Nebraska Cornhuskers Womens Basketball")
    assert site_data.tracked_team_is_home(nebraska, game) is False


@pytest.mark.parametrize(
    ("slug", "name"),
    [
        ("michigan-wolverines-womens-basketball", "Western Michigan Women's Basketball vs Michigan"),
        ("michigan-wolverines-womens-basketball", "Central Michigan Women's Basketball vs Michigan Wolverines"),
        ("illinois-fighting-illini-womens-basketball", "Northern Illinois Women's Basketball vs Illinois"),
        ("iowa-hawkeyes-womens-basketball", "Northern Iowa Women's Basketball vs Iowa Hawkeyes"),
        ("washington-huskies-womens-basketball", "George Washington Women's Basketball vs Washington Huskies"),
        ("maryland-terrapins-womens-basketball", "Loyola Maryland Women's Basketball vs Maryland Terrapins"),
    ],
)
def test_another_school_whose_name_contains_the_title_name_is_not_this_team(slug, name):
    team = _team(slug)
    assert site_data.tracked_team_is_home(team, _game(team, name)) is False


@pytest.mark.parametrize(
    ("side", "expected"),
    [
        ("Nebraska Women's Basketball", True),
        ("NEBRASKA WOMEN'S BASKETBALL - TIME SUBJECT TO CHANGE", True),
        ("Western Nebraska Women's Basketball", False),
        ("Nebraska Women's Basketballers", False),
        ("Nebraska", False),
    ],
)
def test_side_begins_with_whole_words_only(side, expected):
    assert side_begins_with("Nebraska women's basketball", side) is expected
