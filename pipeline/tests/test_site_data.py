from __future__ import annotations

import json

from wsc_pipeline.config import League, Team
from wsc_pipeline.normalize import normalize_event
from wsc_pipeline.site_data import game_to_dict, league_data, site_summary, team_data
from .conftest import make_raw_event

TEAM = Team("indiana-fever", "Indiana Fever")
LEAGUE = League(
    slug="wnba", name="WNBA", country_codes=("US",), teams=(TEAM,),
    schedule_source_used=False, schedule_source_note="not used, see docs",
)


def _game(event_id, **kwargs):
    raw = make_raw_event(event_id=event_id, **kwargs)
    return normalize_event(raw, league_slug="wnba", tracked_team_slug="indiana-fever", tracked_team_name="Indiana Fever")


def test_no_price_is_published_even_when_ticketmaster_sent_one():
    """DECISIONS 0013: the site shows no prices, so the JSON it renders
    from carries none -- not even for an event Ticketmaster priced."""
    priced = _game("EVT-PRICE", price_ranges=[{"type": "standard", "currency": "USD", "min": 5.0, "max": 6.0}])
    unpriced = _game("EVT-NOPRICE", price_ranges=None)
    assert priced.price is not None  # the source did carry a price
    payload = league_data(LEAGUE, [priced, unpriced])
    serialized = json.dumps(payload)
    assert '"price"' not in serialized
    assert "5.0" not in serialized and "6.0" not in serialized


def test_buy_is_the_ticketmaster_event_url_when_no_primary_seller_is_known():
    d = game_to_dict(_game("EVT1", url="https://www.ticketmaster.com/event/EVT1"))
    assert d["buy"] == {"url": "https://www.ticketmaster.com/event/EVT1", "seller": "Ticketmaster", "home_team": ""}
    assert d["ticket_url"] == "https://www.ticketmaster.com/event/EVT1"


def test_buy_is_null_not_guessed_when_there_is_no_link():
    d = game_to_dict(_game("EVT1", url=None))
    assert "buy" in d and d["buy"] is None


def test_team_data_only_includes_that_teams_games():
    other_team_game = normalize_event(
        make_raw_event(event_id="EVT-OTHER"), league_slug="wnba", tracked_team_slug="new-york-liberty", tracked_team_name="New York Liberty"
    )
    this_team_game = _game("EVT-MINE")
    payload = team_data(TEAM, LEAGUE, [other_team_game, this_team_game])
    ids = {g["event_id"] for g in payload["games"]}
    assert ids == {"EVT-MINE"}


def test_league_data_carries_schedule_source_note_even_when_games_exist():
    """A league whose own schedule failed licensing must always show its
    note, regardless of whether Ticketmaster-sourced games are present --
    the note is about the *schedule source*, not about game availability."""
    game = _game("EVT1")
    payload = league_data(LEAGUE, [game])
    assert payload["schedule_source_used"] is False
    assert "not used" in payload["schedule_source_note"]
    assert len(payload["games"]) == 1


def test_site_summary_lists_leagues_not_included():
    summary = site_summary(
        [LEAGUE], {"wnba": []}, api_key_present=True,
        not_included=[{"name": "NCAA women's sports", "reason": "no unified feed"}],
    )
    assert summary["leagues_examined_not_included"][0]["name"] == "NCAA women's sports"


def test_site_summary_degraded_mode_flag():
    summary = site_summary([LEAGUE], {"wnba": []}, api_key_present=False, not_included=[])
    assert summary["api_key_present"] is False
