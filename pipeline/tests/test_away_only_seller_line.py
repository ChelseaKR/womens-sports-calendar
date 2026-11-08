"""An away-only team page names who sells the team's home games, as the
no-games page does (DECISIONS 0038 not needed: wording and links reuse
_seller_sentences). A team that sells on Ticketmaster is unchanged."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from wsc_pipeline import config, sellers, site
from wsc_pipeline.site_data import team_data

from .fixture_site import BASE_URL
from .test_titles_descriptions import _game

GOLDEN = Path(__file__).parent / "golden"
SELLER_TEAMS = sorted(sellers.PRIMARY_SELLERS)
NOTE = re.compile(r'<p class="next-game-note">(.*?)</p>', re.S)


def _team(league_slug: str, team_slug: str) -> tuple[config.League, config.Team]:
    league = config.league_by_slug(league_slug)
    return league, next(t for t in league.teams if t.slug == team_slug)


def _away_games(league, team):
    # A neutral visitor: the shared helper's opponent shares a name with a Minnesota team.
    return [
        _game(
            league,
            team,
            "A1",
            f"Visiting Opponents vs {team.name}",
            date_time="2026-11-20T01:00:00Z",
            local_date="2026-11-19",
        )
    ]


def _page(league_slug: str, team_slug: str) -> str:
    league, team = _team(league_slug, team_slug)
    payload = {**team_data(team, league, _away_games(league, team)), "fetched_at": "2026-11-05T08:25:00+00:00"}
    return site.render_team(team=payload, base_url=BASE_URL)


def _note(html: str) -> str:
    found = NOTE.search(html)
    assert found, "an away-only page has the next-game note"
    return found.group(1)


@pytest.mark.parametrize(("league_slug", "team_slug"), SELLER_TEAMS)
def test_every_seller_table_team_names_its_seller_when_only_away_games_are_listed(league_slug, team_slug):
    seller = sellers.PRIMARY_SELLERS[(league_slug, team_slug)]
    note = _note(_page(league_slug, team_slug))
    assert "home game is listed by Ticketmaster right now." in note
    assert f"main ticket seller is {site.e(seller.name)}, {site.e(seller.contrast)}" in note
    assert "home games may not show up here or in your calendar" in note
    assert "tickets are unavailable" not in note and "on sale" not in note
    assert re.search(r'Check <a href="[^"]+">[^<]*(ticket page|page at)[^<]*</a> for home games\.', note)


@pytest.mark.parametrize(
    ("league_slug", "team_slug", "seller_name"),
    [("pwhl", "minnesota-frost", "SeatGeek"), ("pwhl", "vancouver-goldeneyes", "Ticket Leader")],
)
def test_minnesota_and_vancouver_name_their_seller(league_slug, team_slug, seller_name):
    note = _note(_page(league_slug, team_slug))
    assert f"main ticket seller is {seller_name}, not Ticketmaster" in note


def test_a_ticketmaster_team_page_is_byte_identical_to_what_main_rendered():
    # The golden was rendered by origin/main's site.py before this change.
    golden = (GOLDEN / "away_only_ticketmaster_boston_fleet.html").read_bytes()
    assert ("pwhl", "boston-fleet") not in sellers.PRIMARY_SELLERS
    assert _page("pwhl", "boston-fleet").encode() == golden
    assert "main ticket seller" not in _note(golden.decode())


def test_control_without_the_seller_table_entry_the_line_is_gone(monkeypatch: pytest.MonkeyPatch):
    key = ("pwhl", "minnesota-frost")
    assert "main ticket seller is SeatGeek" in _note(_page(*key))  # the line is there to be removed
    trimmed = {k: v for k, v in sellers.PRIMARY_SELLERS.items() if k != key}
    monkeypatch.setattr(sellers, "PRIMARY_SELLERS", trimmed)
    assert key not in sellers.PRIMARY_SELLERS  # the sabotage applied
    note = _note(_page(*key))
    assert note == "No Minnesota Frost home game is listed by Ticketmaster right now."
