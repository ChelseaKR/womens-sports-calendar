from __future__ import annotations

from wsc_pipeline.normalize import display_start, normalize_event, parse_teams
from .conftest import make_raw_event


def test_parse_teams_vs_split():
    home, away = parse_teams("Indiana Fever vs New York Liberty", [])
    assert home == "Indiana Fever"
    assert away == "New York Liberty"


def test_parse_teams_at_split():
    home, away = parse_teams("Toronto Sceptres at Boston Fleet", [])
    assert home == "Toronto Sceptres"
    assert away == "Boston Fleet"


def test_parse_teams_falls_back_to_attractions_when_name_unparseable():
    attractions = [{"name": "Minnesota Frost"}, {"name": "Ottawa Charge"}]
    home, away = parse_teams("PWHL: Championship Night", attractions)
    assert home == "Minnesota Frost"
    assert away == "Ottawa Charge"


def test_parse_teams_returns_none_when_nothing_usable():
    home, away = parse_teams("Season Pass Package", [])
    assert home is None
    assert away is None


def test_normalize_event_with_price(event_with_price):
    game = normalize_event(
        event_with_price, league_slug="wnba", tracked_team_slug="indiana-fever", tracked_team_name="Indiana Fever"
    )
    assert game is not None
    assert game.price is not None
    assert game.price.currency == "USD"
    assert game.price.min == 25.0
    assert game.price.max == 150.0


def test_normalize_event_without_price_is_none_not_zero(event_without_price):
    """Absence discipline: a game with no Ticketmaster priceRanges must get
    price=None, never a fabricated 0/0 or an omitted-but-implied price."""
    game = normalize_event(
        event_without_price, league_slug="wnba", tracked_team_slug="indiana-fever", tracked_team_name="Indiana Fever"
    )
    assert game is not None
    assert game.price is None


def test_normalize_event_empty_price_ranges_list_is_none():
    raw = make_raw_event(event_id="EVT-EMPTY", price_ranges=[])
    game = normalize_event(raw, league_slug="wnba", tracked_team_slug="t", tracked_team_name="T")
    assert game is not None
    assert game.price is None


def test_normalize_event_price_range_missing_min_is_none():
    raw = make_raw_event(
        event_id="EVT-PARTIAL",
        price_ranges=[{"type": "standard", "currency": "USD", "max": 100.0}],
    )
    game = normalize_event(raw, league_slug="wnba", tracked_team_slug="t", tracked_team_name="T")
    assert game is not None
    assert game.price is None


def test_normalize_event_date_tbd_is_kept_but_flagged(event_date_tbd):
    game = normalize_event(
        event_date_tbd, league_slug="pwhl", tracked_team_slug="minnesota-frost", tracked_team_name="Minnesota Frost"
    )
    assert game is not None
    assert game.date_tbd is True
    assert game.start_utc is None
    assert display_start(game) == "Date TBD"


def test_normalize_event_with_no_date_at_all_is_dropped():
    """No dateTime and no localDate: nothing usable to schedule -- dropped,
    never fabricated as 'today' or any other placeholder."""
    raw = make_raw_event(event_id="EVT-NODATE", date_time=None, local_date=None, local_time=None)
    game = normalize_event(raw, league_slug="wnba", tracked_team_slug="t", tracked_team_name="T")
    assert game is None


def test_normalize_event_with_no_id_is_dropped():
    raw = make_raw_event(event_id="")
    raw["id"] = None
    game = normalize_event(raw, league_slug="wnba", tracked_team_slug="t", tracked_team_name="T")
    assert game is None


def test_normalize_event_time_tba_display():
    raw = make_raw_event(event_id="EVT-TIMETBA", local_time=None, time_tba=True)
    game = normalize_event(raw, league_slug="wnba", tracked_team_slug="t", tracked_team_name="T")
    assert game is not None
    assert "time TBA" in display_start(game)


def test_normalize_event_no_venue_fields_are_none_not_fabricated():
    raw = make_raw_event(event_id="EVT-NOVENUE", venue_name=None, venue_city=None, venue_state=None, timezone=None)
    game = normalize_event(raw, league_slug="wnba", tracked_team_slug="t", tracked_team_name="T")
    assert game is not None
    assert game.venue_name is None
    assert game.venue_city is None
    assert game.venue_state is None
