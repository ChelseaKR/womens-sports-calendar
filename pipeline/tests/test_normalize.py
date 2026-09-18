from __future__ import annotations

from wsc_pipeline.normalize import display_start, normalize_event, parse_matchup, parse_teams, team_is_participant

from .conftest import make_raw_event


def test_parse_teams_vs_split():
    home, away = parse_teams("Indiana Fever vs New York Liberty", [])
    assert home == "Indiana Fever"
    assert away == "New York Liberty"


def test_parse_teams_at_split_names_the_visitor_first():
    """ "A at B" is the sports convention for A visiting B: the home team is
    the second one. (This test used to assert the reverse, which put every
    such game on the wrong side of "home" -- and the home team's seller
    link -- and would have made the structured data's homeTeam wrong.)"""
    home, away = parse_teams("Toronto Sceptres at Boston Fleet", [])
    assert home == "Boston Fleet"
    assert away == "Toronto Sceptres"
    assert parse_teams("Toronto Sceptres @ Boston Fleet", []) == ("Boston Fleet", "Toronto Sceptres")


def test_parse_matchup_says_when_home_and_away_are_known():
    assert parse_matchup("Indiana Fever vs New York Liberty", []) == ("Indiana Fever", "New York Liberty", True)
    assert parse_matchup("Toronto Sceptres at Boston Fleet", []) == ("Boston Fleet", "Toronto Sceptres", True)
    # From the attraction list, the pair is right but not which is at home.
    attractions = [{"name": "Minnesota Frost"}, {"name": "Ottawa Charge"}]
    assert parse_matchup("PWHL: Championship Night", attractions) == ("Minnesota Frost", "Ottawa Charge", False)
    assert parse_matchup("Season Pass Package", []) == (None, None, False)


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


# -- team_is_participant: regression coverage for the 2026-09-16 live-site
# bug where an NWSL "Angel City" Discovery API keyword search returned an
# unrelated WHL hockey game ("Everett Silvertips vs Tri-City Americans")
# played at "Angel Of The Winds Arena" -- the keyword matched the venue
# name, not any actual participant. All fixture shapes below (event name,
# venue name, home/away split) mirror the real nexthomegame.com production
# data pulled from https://nexthomegame.com/data/nwsl/angel-city.json on
# 2026-09-16, and the second/third cases were also confirmed live in that
# same production pull -- these are not hypothetical inputs.


def test_team_is_participant_rejects_wrong_sport_same_venue_keyword_match():
    """The exact reported bug: keyword search for NWSL's "Angel City"
    returns a WHL hockey game at "Angel Of The Winds Arena" -- the venue
    name contains "Angel", the teams playing do not."""
    raw = make_raw_event(
        event_id="EVT-HOCKEY",
        name="Everett Silvertips vs Tri-City Americans",
        venue_name="Angel Of The Winds Arena",
        venue_city="Everett",
        venue_state="WA",
    )
    assert team_is_participant("Angel City", raw) is False


def test_team_is_participant_rejects_wrong_sport_same_city_keyword_match():
    """Same production pull: keyword search for "Angel City" also returned
    real MLB Angels/Royals games (the Angels' own name contains "Angel")."""
    raw = make_raw_event(
        event_id="EVT-MLB",
        name="Los Angeles Angels vs Kansas City Royals",
        venue_name="Angel Stadium of Anaheim",
        venue_city="Anaheim",
        venue_state="CA",
    )
    assert team_is_participant("Angel City", raw) is False


def test_team_is_participant_rejects_same_sport_wrong_team():
    """classificationName=Sports alone can't catch this: a keyword search
    for NWSL's "Bay FC" also returned a real soccer match between two
    entirely different clubs that both happen to have "Bay" in their name."""
    raw = make_raw_event(
        event_id="EVT-OTHERSOCCER",
        name="Tampa Bay Sun FC vs DC Power FC",
        venue_name="Suncoast Credit Union Field",
        venue_city="Tampa",
        venue_state="FL",
    )
    assert team_is_participant("Bay FC", raw) is False


def test_team_is_participant_accepts_real_match():
    raw = make_raw_event(
        event_id="EVT-REAL",
        name="Angel City FC vs Seattle Reign FC",
        venue_name="BMO Stadium",
        venue_city="Los Angeles",
        venue_state="CA",
    )
    assert team_is_participant("Angel City", raw) is True
    assert team_is_participant("Seattle Reign", raw) is True


def test_team_is_participant_accepts_ticketmaster_home_team_abbreviation():
    """Real production shape: Ticketmaster lists a home game as just
    "Mystics vs Connecticut Sun ..." -- must not be rejected for dropping
    the city name, or a real Washington Mystics home game disappears."""
    raw = make_raw_event(
        event_id="EVT-ABBREV",
        name="Mystics vs Connecticut Sun (Windbreaker Giveaway - First 1,500 Fans)",
        venue_name="CareFirst Arena",
        venue_city="Washington",
        venue_state="DC",
    )
    assert team_is_participant("Washington Mystics", raw) is True


def test_team_is_participant_uses_attractions_when_name_is_unparseable():
    raw = make_raw_event(
        event_id="EVT-ATTR",
        name="PWHL: Championship Night",
        attractions=["Minnesota Frost", "Ottawa Charge"],
    )
    assert team_is_participant("Minnesota Frost", raw) is True


def test_team_is_participant_rejects_shared_city_different_league():
    """A same-city collision that is not the reported bug but is the same
    class: keyword search for PWHL's "Minnesota Frost" returning a real
    NBA game merely because both mention "Minnesota"."""
    raw = make_raw_event(
        event_id="EVT-NBA",
        name="San Antonio Spurs vs Minnesota Timberwolves",
        venue_name="Frost Bank Center",
        venue_city="San Antonio",
        venue_state="TX",
    )
    assert team_is_participant("Minnesota Frost", raw) is False


# -- Monterey Bay FC (USL Championship, men's) on NWSL Bay FC's page: seen
# live 2026-09-17, six games. Event names below are the live ones.


def _bay_fc():
    from wsc_pipeline.config import LEAGUES

    return next(t for lg in LEAGUES for t in lg.teams if t.slug == "bay-fc")


def test_monterey_bay_fc_games_are_not_bay_fc_games():
    bay_fc = _bay_fc()
    assert bay_fc.not_this_team == ("Monterey Bay FC",)
    for name in (
        "Monterey Bay FC vs Lexington SC",
        "Orange County SC vs Monterey Bay FC- Hispanic Heritage Night",
        "New Mexico United vs Monterey Bay FC",
        "Monterey Bay FC vs Las Vegas Lights FC",
    ):
        raw = make_raw_event(name=name)
        assert team_is_participant(bay_fc.name, raw, bay_fc.not_this_team) is False, name
        # and without the exclusion, the phrase check alone lets it through
        assert team_is_participant(bay_fc.name, raw) is True, name


def test_real_bay_fc_games_still_match_with_the_exclusion():
    bay_fc = _bay_fc()
    for name in (
        "Bay FC vs Racing Louisville FC",
        "Angel City FC vs Bay FC",
        "Bay FC vs Monterey Bay FC",  # a real meeting of the two still belongs to Bay FC
    ):
        assert team_is_participant(bay_fc.name, make_raw_event(name=name), bay_fc.not_this_team) is True, name
