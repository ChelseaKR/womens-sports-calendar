"""Sponsor prefixes, "(Exhibition)" and "<event> at <venue>" are not team names (#23).

The two real fixtures below are the two events Ticketmaster listed for the
Illinois team on 2026-09-19 (data/ncaaw-big-ten.json on the live site, event
ids Z7r9jZ1AAvg1A and Z7r9jZ1AAvg1e), with their exact names. They came out as
home team "McBride Homes Braggin' Rights: Illinois Fighting Illini Womens
Basketball" and away team "UIS Prairie Stars Womens Basketball (Exhibition)".
The other two shapes come from the issue; they were not seen live.

What must not move: the game's Ticketmaster event id (so its UID), the
team's slug (so its page and feed URLs), and the full event name the calendar
shows as the event summary.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from icalendar import Calendar

from wsc_pipeline import build as build_module
from wsc_pipeline import site_data
from wsc_pipeline.config import league_by_slug
from wsc_pipeline.ics import make_uid
from wsc_pipeline.normalize import Game, normalize_event, parse_event_name, parse_matchup, team_is_participant
from wsc_pipeline.sellers import buy_link

from .conftest import make_raw_event
from .test_build import _FakeDiscoveryClient
from .test_team_identity import PUBLISHED_SLUGS

ILLINOIS = "Illinois Fighting Illini Womens Basketball"
ILLINOIS_SLUG = "illinois-fighting-illini-womens-basketball"
BRAGGIN = (
    "McBride Homes Braggin' Rights: Illinois Fighting Illini Womens Basketball vs Missouri Tigers Womens Basketball"
)
EXHIBITION = "Illinois Fighting Illini Womens Basketball vs UIS Prairie Stars Womens Basketball (Exhibition)"
TOURNAMENT = "Big Ten Women's Basketball Tournament at Target Center"
VENUE = "State Farm Center"


def _raw_braggin(**kwargs):
    return make_raw_event(
        event_id="Z7r9jZ1AAvg1A",
        name=BRAGGIN,
        venue_name=VENUE,
        venue_city="Champaign",
        venue_state="IL",
        timezone="America/Chicago",
        date_time=None,
        local_date="2026-12-10",
        local_time=None,
        time_tba=True,
        **kwargs,
    )


def _raw_exhibition(**kwargs):
    return make_raw_event(
        event_id="Z7r9jZ1AAvg1e",
        name=EXHIBITION,
        venue_name=VENUE,
        venue_city="Champaign",
        venue_state="IL",
        timezone="America/Chicago",
        date_time=None,
        local_date="2026-10-30",
        local_time=None,
        time_tba=True,
        **kwargs,
    )


def _game(raw) -> Game:
    game = normalize_event(
        raw, league_slug="ncaaw-big-ten", tracked_team_slug=ILLINOIS_SLUG, tracked_team_name=ILLINOIS
    )
    assert game is not None
    return game


# --- the two live shapes -------------------------------------------------------------------------------


def test_a_sponsor_prefix_is_an_event_title_and_not_part_of_the_home_team():
    game = _game(_raw_braggin())
    assert game.home_team == ILLINOIS
    assert game.away_team == "Missouri Tigers Womens Basketball"
    assert game.home_away_known is True
    assert game.event_title == "McBride Homes Braggin' Rights"
    assert game.game_type is None
    assert game.raw_event_name == BRAGGIN  # the full name is kept exactly


def test_a_trailing_exhibition_is_a_game_type_and_not_part_of_the_away_team():
    game = _game(_raw_exhibition())
    assert game.home_team == ILLINOIS
    assert game.away_team == "UIS Prairie Stars Womens Basketball"
    assert game.game_type == "Exhibition"
    assert game.event_title is None
    assert game.raw_event_name == EXHIBITION


def test_the_home_flag_and_the_participant_check_still_work_on_the_live_names():
    braggin, exhibition = _game(_raw_braggin()), _game(_raw_exhibition())
    team = next(t for t in league_by_slug("ncaaw-big-ten").teams if t.slug == ILLINOIS_SLUG)
    assert site_data.tracked_team_is_home(team, braggin) is True
    assert site_data.tracked_team_is_home(team, exhibition) is True
    assert team_is_participant(ILLINOIS, _raw_braggin())
    assert team_is_participant("Missouri Tigers Womens Basketball", _raw_braggin())
    assert team_is_participant(ILLINOIS, _raw_exhibition())


# --- the two shapes from the issue -----------------------------------------------------------------------


def test_a_name_of_the_form_event_at_venue_does_not_name_the_venue_as_the_home_team():
    home, away, known = parse_matchup(TOURNAMENT, [], venue_name="Target Center")
    assert (home, away, known) == (None, None, False)
    game = _game(make_raw_event(event_id="TRN1", name=TOURNAMENT, venue_name="Target Center"))
    assert game.home_team is None and game.away_team is None and game.home_away_known is False
    assert game.raw_event_name == TOURNAMENT
    # Nothing downstream can now treat the venue as a team or a home side.
    payload = site_data.game_to_dict(game)
    assert payload["home_team"] is None and payload["event_name"] == TOURNAMENT
    assert buy_link(game) is not None and buy_link(game)["seller"] == "Ticketmaster"


def test_an_event_at_venue_name_falls_back_to_two_attractions_with_the_order_unknown():
    home, away, known = parse_matchup(
        TOURNAMENT, [{"name": "Iowa Hawkeyes"}, {"name": "Ohio State Buckeyes"}], venue_name="Target Center"
    )
    assert (home, away, known) == ("Iowa Hawkeyes", "Ohio State Buckeyes", False)


def test_without_a_venue_name_the_old_reading_is_unchanged():
    """The issue's own call has no venue: nothing can say the text after "at"
    is one, so the result is what it always was."""
    assert parse_matchup(TOURNAMENT, []) == ("Target Center", "Big Ten Women's Basketball Tournament", True)


@pytest.mark.parametrize("venue", ["Gainbridge Fieldhouse", None, "Some Other Arena"])
def test_a_real_away_at_home_matchup_is_still_read_with_the_visitor_first(venue):
    assert parse_matchup("Chicago Sky at Indiana Fever", [], venue_name=venue) == ("Indiana Fever", "Chicago Sky", True)


def test_a_game_number_after_the_matchup_is_kept_out_of_the_team_name():
    matchup = parse_event_name("Las Vegas Aces vs. Seattle Storm - Game 2", [])
    assert (matchup.home, matchup.away, matchup.home_away_known) == ("Las Vegas Aces", "Seattle Storm", True)
    assert matchup.game_type == "Game 2"
    both = parse_event_name("Las Vegas Aces vs. Seattle Storm – Game 3 (If Necessary)", [])
    assert both.away == "Seattle Storm" and both.game_type == "Game 3 (If Necessary)"


# --- what is deliberately left alone ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, away",
    [
        ("Las Vegas Aces vs Seattle Storm (W)", "Seattle Storm (W)"),  # a team's own parenthetical
        ("Las Vegas Aces vs Seattle Storm (Women's)", "Seattle Storm (Women's)"),
        ("Las Vegas Aces vs Seattle Storm (Theme Night)", "Seattle Storm (Theme Night)"),  # not on the allowlist
        ("Las Vegas Aces vs Seattle Storm - Postponed", "Seattle Storm - Postponed"),
    ],
)
def test_only_recognized_game_types_come_off_a_team_name(name, away):
    matchup = parse_event_name(name, [])
    assert matchup.away == away and matchup.game_type is None


def test_a_colon_after_the_separator_is_not_a_sponsor_prefix():
    matchup = parse_event_name("Illinois vs Missouri: Braggin' Rights", [])
    assert (matchup.home, matchup.away, matchup.event_title) == ("Illinois", "Missouri: Braggin' Rights", None)


def test_a_name_with_no_separator_still_uses_the_attractions_or_nothing():
    assert parse_matchup("Washington Spirit Premium Experiences", []) == (None, None, False)
    assert parse_matchup("Fan Fest", [{"name": "A Team"}, {"name": "B Team"}]) == ("A Team", "B Team", False)


def test_the_two_argument_signature_still_works():
    assert parse_matchup("Seattle Storm vs Las Vegas Aces", []) == ("Seattle Storm", "Las Vegas Aces", True)


# --- published data: additive keys only ---------------------------------------------------------------------


def test_the_new_keys_are_published_only_for_a_game_that_has_them():
    plain = site_data.game_to_dict(_game(make_raw_event(event_id="P1", name="Indiana Fever vs New York Liberty")))
    assert "event_title" not in plain and "game_type" not in plain

    braggin = site_data.game_to_dict(_game(_raw_braggin()))
    assert braggin["event_title"] == "McBride Homes Braggin' Rights" and "game_type" not in braggin
    assert braggin["home_team"] == ILLINOIS and braggin["event_name"] == BRAGGIN

    exhibition = site_data.game_to_dict(_game(_raw_exhibition()))
    assert exhibition["game_type"] == "Exhibition" and "event_title" not in exhibition
    assert exhibition["away_team"] == "UIS Prairie Stars Womens Basketball"
    # No existing key was renamed or removed.
    for key in ("event_id", "event_name", "home_team", "away_team", "start_display", "in_calendar_feed", "buy"):
        assert key in braggin and key in exhibition


# --- the page ------------------------------------------------------------------------------------------------


def _build_illinois(tmp_path: Path, monkeypatch, events) -> Path:
    fake = _FakeDiscoveryClient({ILLINOIS_SLUG: events})
    monkeypatch.setattr(build_module, "DiscoveryClient", lambda api_key: fake)
    out = tmp_path / "dist"
    build_module.build(out_dir=out, base_url="https://nexthomegame.com", api_key="fake-key", affiliate_id=None)
    return out


def test_the_team_page_shows_the_label_and_the_title_beside_clean_team_names(tmp_path: Path, monkeypatch):
    out = _build_illinois(tmp_path, monkeypatch, [_raw_exhibition(), _raw_braggin()])
    page = (out / "ncaaw-big-ten" / ILLINOIS_SLUG / "index.html").read_text()

    assert f"{ILLINOIS} vs UIS Prairie Stars Womens Basketball" in page
    # The type is said once as plain text after the hero's matchup (asserted
    # below) and never inside a team name, a table cell, link text or the
    # meta description.
    assert page.count("(Exhibition)") == 1
    assert "Basketball (Exhibition) on" not in page
    assert "Basketball (Exhibition)</td>" not in page
    description = re.search(r'<meta name="description" content="([^"]*)"', page)
    assert description is not None and "Exhibition" not in description.group(1)
    assert '<span class="home-away game-type">Exhibition</span>' in page
    assert '<span class="event-title">McBride Homes Braggin&#x27; Rights</span>' in page
    assert f"{ILLINOIS} vs Missouri Tigers Womens Basketball" in page
    assert "Buy tickets for McBride" not in page  # the link text names the two teams only
    assert f"Buy tickets for {ILLINOIS} vs Missouri Tigers Womens Basketball on" in page
    # The next home game is the earlier one, the exhibition, and its type is said.
    assert f"{ILLINOIS} vs UIS Prairie Stars Womens Basketball (Exhibition)</p>" in page
    assert "Next home game: Fri, Oct 30, 2026 (time TBA) vs UIS Prairie Stars Womens Basketball." in page


def test_a_game_without_the_new_fields_renders_no_label(tmp_path: Path, monkeypatch):
    plain = make_raw_event(event_id="P1", name=f"{ILLINOIS} vs Purdue Boilermakers Womens Basketball")
    out = _build_illinois(tmp_path, monkeypatch, [plain])
    page = (out / "ncaaw-big-ten" / ILLINOIS_SLUG / "index.html").read_text()
    assert "game-type" not in page.split("</style>")[-1] and "event-title" not in page


# --- what must not move --------------------------------------------------------------------------------------


def test_the_team_slug_the_feed_path_and_the_uids_do_not_change(tmp_path: Path, monkeypatch):
    """Cleaning a team name in an event must never reach the slug (the page
    and feed URL people subscribe to) or the UID (what their calendar keys an
    event on). Both events are given a real start time here so they are in the
    feed."""
    events = [
        _raw_braggin(),
        _raw_exhibition(),
    ]
    for raw in events:
        raw["dates"]["start"].update(dateTime="2026-12-10T01:00:00Z", timeTBA=False, localTime="19:00:00")
    out = _build_illinois(tmp_path, monkeypatch, events)

    assert ILLINOIS_SLUG in PUBLISHED_SLUGS["ncaaw-big-ten"]
    feed = out / "ics" / "ncaaw-big-ten" / f"{ILLINOIS_SLUG}.ics"
    assert feed.is_file() and (out / "ncaaw-big-ten" / ILLINOIS_SLUG / "index.html").is_file()
    cal = Calendar.from_ical(feed.read_bytes())
    uids = {str(e["uid"]) for e in cal.walk("VEVENT")}
    assert uids == {
        "tm-Z7r9jZ1AAvg1A@womens-sports-calendar.invalid",
        "tm-Z7r9jZ1AAvg1e@womens-sports-calendar.invalid",
    }
    assert uids == {make_uid("Z7r9jZ1AAvg1A"), make_uid("Z7r9jZ1AAvg1e")}
    # The calendar still says the full event name, sponsor and label included.
    assert {str(e["summary"]) for e in cal.walk("VEVENT")} == {BRAGGIN, EXHIBITION}
    team_json = json.loads((out / "data" / "ncaaw-big-ten" / f"{ILLINOIS_SLUG}.json").read_text())
    assert team_json["team_slug"] == ILLINOIS_SLUG and team_json["team_name"] == ILLINOIS
