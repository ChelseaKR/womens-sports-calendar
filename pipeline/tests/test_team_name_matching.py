"""College teams' games reach their own pages and feeds, under every name
Ticketmaster uses for them.

The live build of 2026-11-05 listed 43 college games in the Big Ten and SEC
calendars that were missing from 14 teams' own pages and feeds. Each was
found only by the opponent's search, and was filed only under the team whose
search returned it. Ticketmaster names a school differently at each host
venue, so the school's own names (its keyword "Penn State Nittany Lions
Womens Basketball" and its title name "Penn State women's basketball") were
not phrases of the event's side. Penn State and Oregon showed no home game
at all.

Every event name below is copied from the live league feeds of 2026-11-05
(nexthomegame.com/ics/ncaaw-big-ten.ics and ncaaw-sec.ics).
"""

from __future__ import annotations

import pytest

from wsc_pipeline import build as build_module
from wsc_pipeline import config, normalize, site_data
from wsc_pipeline.config import league_by_slug
from wsc_pipeline.normalize import event_names_team, normalize_event, side_names_college_team

from .conftest import make_raw_event
from .test_build import _FakeDiscoveryClient

BIG_TEN = league_by_slug("ncaaw-big-ten")
SEC = league_by_slug("ncaaw-sec")


def _team(league: config.League, school: str) -> config.Team:
    return next(t for t in league.teams if t.school == school)


PENN_STATE = _team(BIG_TEN, "Penn State")
OREGON = _team(BIG_TEN, "Oregon")
RUTGERS = _team(BIG_TEN, "Rutgers")


@pytest.mark.parametrize(
    ("league", "school", "side"),
    [
        (BIG_TEN, "Penn State", "Penn State Lady Lion Basketball"),
        (BIG_TEN, "Oregon", "Oregon Women's Basketball"),
        (BIG_TEN, "Oregon", "Oregon Ducks Women's Basketball"),
        (BIG_TEN, "Minnesota", "Minnesota Gophers Womens Basketball"),
        (BIG_TEN, "Michigan State", "Michigan State University Spartans Womens Basketball"),
        (BIG_TEN, "Illinois", "University of Illinois Fighting Illini Womans Basketball"),
        (BIG_TEN, "Indiana", "Indiana University Womens Basketball"),
        (BIG_TEN, "Purdue", "Purdue University Womens Basketball"),
        (BIG_TEN, "Maryland", "Univ of Maryland Terrapins Womens Basketball"),
        (BIG_TEN, "Wisconsin", "University of Wisconsin Badgers Womens Basketball"),
        (SEC, "Tennessee", "Tennessee Vols Womens Basketball"),
        (SEC, "LSU", "LSU Women's Basketball"),
        (SEC, "Auburn", "Auburn University Lady Tigers Basketball"),
        (SEC, "Mississippi State", "Mississippi State University Bulldogs Womens Basketball"),
        (SEC, "Arkansas", "Arkansas Razorback Womens Basketball"),
        (SEC, "Texas", "University of Texas Women's Basketball"),
        (SEC, "Texas A&M", "Texas A & M Aggies Womens Basketball"),
        (SEC, "Vanderbilt", "Vanderbilt University Women's Basketball"),
        (SEC, "South Carolina", "University of South Carolina Gamecocks Women's Basketball"),
    ],
)
def test_every_live_spelling_of_a_school_is_that_school(league, school, side):
    team = _team(league, school)
    assert side_names_college_team(team.school, team.mascots, side)


@pytest.mark.parametrize(
    ("league", "school", "side"),
    [
        # Another school whose name starts with this one's (all live names).
        (SEC, "Texas", "Texas A&M Aggies Womens Basketball"),
        (SEC, "Texas", "Texas Tech Red Raiders Womens Basketball"),
        (SEC, "Texas", "Texas Southern Tigers Womens Basketball"),
        (BIG_TEN, "Michigan", "Michigan State University Spartans Womens Basketball"),
        (BIG_TEN, "Indiana", "Indiana State Sycamores Womens Basketball"),
        (BIG_TEN, "Washington", "George Washington Womens Basketball"),
        (BIG_TEN, "Nebraska", "Nebraska Omaha Mavericks Womens Basketball"),
        (BIG_TEN, "Maryland", "Maryland Eastern Shore Hawks Womens Basketball"),
        (SEC, "Tennessee", "Tennessee State Tigers Womens Basketball"),
        (SEC, "Alabama", "Alabama A&M Bulldogs Womens Basketball"),
        (SEC, "Oklahoma", "Oklahoma State Cowgirls Womens Basketball"),
        (SEC, "LSU", "LSU New Orleans Privateers Womens Basketball"),
        # Not the women's basketball team: a men's team, and another sport
        # (Ticketmaster's mislabel of Purdue at Washington stays off the page
        # rather than be guessed into it).
        (BIG_TEN, "Penn State", "Penn State Nittany Lions Basketball"),
        (BIG_TEN, "Penn State", "Penn State Nittany Lions Mens Basketball"),
        (BIG_TEN, "Purdue", "Purdue Boilermakers Women's Volleyball"),
        # A bare school name is not enough for this rule.
        (BIG_TEN, "Oregon", "Oregon"),
    ],
)
def test_other_schools_mens_teams_and_other_sports_are_not_the_school(league, school, side):
    team = _team(league, school)
    assert not side_names_college_team(team.school, team.mascots, side)


def test_every_college_team_knows_its_school_and_mascot():
    for league in (BIG_TEN, SEC):
        for team in league.teams:
            assert team.school and team.mascots
            assert team.name == f"{team.school} {team.mascots[0]} Womens Basketball"
            assert team.title_name == f"{team.school} women's basketball"


def test_penn_state_and_oregon_also_search_the_name_their_home_games_use():
    assert PENN_STATE.search_names == ("Penn State Lady Lion Basketball",)
    assert OREGON.search_names == ("Oregon Women's Basketball",)


def _fetch(responses: dict[str, list[dict]], monkeypatch) -> list[normalize.Game]:
    fake_client = _FakeDiscoveryClient(responses)
    monkeypatch.setattr(build_module, "DiscoveryClient", lambda api_key: fake_client)
    games, _truncated, _mismatched, _requests, _bytes = build_module.fetch_all_games("fake-key")
    return games


def _on(games: list[normalize.Game], league: config.League, team: config.Team) -> list[normalize.Game]:
    return [g for g in games if g.league_slug == league.slug and g.tracked_team_slug == team.slug]


PSU_HOME = make_raw_event(event_id="PSU-RUT", name="Penn State Lady Lion Basketball vs. Rutgers")
NU_AT_HOME = make_raw_event(
    event_id="NU-PSU", name="Northwestern Wildcats Women's Basketball vs. Penn State Lady Lion Basketball"
)


def test_a_game_only_the_opponents_search_found_reaches_the_teams_page_with_home_and_away(monkeypatch):
    """Rutgers' search returns the Penn State home game; it is on both pages,
    a home game for Penn State and an away game for Rutgers."""
    games = _fetch({RUTGERS.slug: [PSU_HOME], "northwestern-wildcats-womens-basketball": [NU_AT_HOME]}, monkeypatch)
    psu = {g.event_id: g for g in _on(games, BIG_TEN, PENN_STATE)}
    assert set(psu) == {"PSU-RUT", "NU-PSU"}
    assert site_data.tracked_team_is_home(PENN_STATE, psu["PSU-RUT"]) is True
    assert site_data.tracked_team_is_home(PENN_STATE, psu["NU-PSU"]) is False
    [rutgers_game] = _on(games, BIG_TEN, RUTGERS)
    assert site_data.tracked_team_is_home(RUTGERS, rutgers_game) is False


def test_a_bare_opponent_name_from_another_league_is_not_a_pro_team(monkeypatch):
    """ "Penn State Lady Lion Basketball vs. Indiana" names Indiana by school
    alone. In the Big Ten that is the Hoosiers; it is never the WNBA's
    Indiana Fever, nor a Washington pro team for "vs. Washington"."""
    vs_indiana = make_raw_event(event_id="PSU-IND", name="Penn State Lady Lion Basketball vs. Indiana")
    vs_washington = make_raw_event(event_id="PSU-UW", name="Penn State Lady Lion Basketball vs. Washington")
    games = _fetch({PENN_STATE.slug: [vs_indiana, vs_washington]}, monkeypatch)
    assert {(g.league_slug, g.tracked_team_slug, g.event_id) for g in games} == {
        ("ncaaw-big-ten", PENN_STATE.slug, "PSU-IND"),
        ("ncaaw-big-ten", PENN_STATE.slug, "PSU-UW"),
        ("ncaaw-big-ten", "indiana-hoosiers-womens-basketball", "PSU-IND"),
        ("ncaaw-big-ten", "washington-huskies-womens-basketball", "PSU-UW"),
    }


def test_a_school_from_another_conference_is_found_by_its_own_name(monkeypatch):
    """Vanderbilt (SEC) at Iowa (Big Ten), found only by Iowa's search."""
    raw = make_raw_event(event_id="IOWA-VU", name="Iowa Hawkeyes v Vanderbilt University Women's Basketball")
    games = _fetch({"iowa-hawkeyes-womens-basketball": [raw]}, monkeypatch)
    vanderbilt = _team(SEC, "Vanderbilt")
    [game] = _on(games, SEC, vanderbilt)
    assert site_data.tracked_team_is_home(vanderbilt, game) is False


def test_a_mens_game_and_another_school_stay_off_the_page(monkeypatch):
    mens = make_raw_event(event_id="MENS", name="Penn State Nittany Lions Mens Basketball vs. Rutgers")
    george_washington = make_raw_event(
        event_id="GW", name="Northwestern Wildcats Women's Basketball vs. George Washington Womens Basketball"
    )
    games = _fetch({RUTGERS.slug: [mens], "northwestern-wildcats-womens-basketball": [george_washington]}, monkeypatch)
    assert _on(games, BIG_TEN, PENN_STATE) == []
    assert _on(games, BIG_TEN, _team(BIG_TEN, "Washington")) == []


MINNESOTA_AWAY = make_raw_event(
    event_id="UMD-MINN", name="Maryland Terrapins Womens Basketball vs. Minnesota Gophers Womens Basketball"
)


def test_negative_control_without_the_college_rule_the_game_stays_off_the_page(monkeypatch):
    """The Minnesota game Maryland's search found is on Minnesota's page;
    sabotage the college rule (always no) and it is not, as on the live site,
    so the rule is what puts it there."""
    minnesota = _team(BIG_TEN, "Minnesota")
    maryland = _team(BIG_TEN, "Maryland")
    assert [g.event_id for g in _on(_fetch({maryland.slug: [MINNESOTA_AWAY]}, monkeypatch), BIG_TEN, minnesota)] == [
        "UMD-MINN"
    ]
    monkeypatch.setattr(normalize, "side_names_college_team", lambda *_args: False)
    assert not event_names_team(minnesota, MINNESOTA_AWAY)
    assert _on(_fetch({maryland.slug: [MINNESOTA_AWAY]}, monkeypatch), BIG_TEN, minnesota) == []


def test_normalized_game_keeps_the_ticketmaster_name():
    game = normalize_event(PSU_HOME, league_slug=BIG_TEN.slug, tracked_team_slug=PENN_STATE.slug, tracked_team_name="x")
    assert game is not None and game.home_team == "Penn State Lady Lion Basketball"
