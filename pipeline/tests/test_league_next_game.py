"""In-season league pages answer first (DECISIONS 0040): the league page's
opening sentence and meta description give the next game Ticketmaster lists,
with its matchup, venue, date and local time, and say nothing about a next
game when none with a date is listed or the build did not look. College
teams are linked and named by the name a fan searches ("Purdue women's
basketball"), not the Ticketmaster keyword ("Purdue Boilermakers Womens
Basketball"), in the league roster, the "more teams" list and the
no-home-game note. Titles are not touched (DECISIONS 0038 holds them).

Each control breaks one rule and asserts both that the sabotage applied and
that the check catches it."""

from __future__ import annotations

import re
from html import unescape
from typing import Any

import pytest

from wsc_pipeline import config, site
from wsc_pipeline.normalize import normalize_event
from wsc_pipeline.site_data import league_data, team_data

from .conftest import make_raw_event
from .fixture_site import BASE_URL

DESCRIPTION_MAX = 155
PWHL = next(lg for lg in config.LEAGUES if lg.slug == "pwhl")
SEC = next(lg for lg in config.LEAGUES if lg.slug == "ncaaw-sec")
BIG_TEN = next(lg for lg in config.LEAGUES if lg.slug == "ncaaw-big-ten")
COLLEGE = [lg for lg in config.LEAGUES if lg.slug.startswith("ncaaw-")]
# Ticketmaster's spellings ("Womens Basketball", "Women's Basketball",
# "Womans Basketball", "Women Basketball"), not the searched "women's basketball".
TICKETMASTER_SUFFIX = re.compile(r"Wom[ae]n(?:'?s)? Basketball")


def _team(league: config.League, slug: str) -> config.Team:
    return next(t for t in league.teams if t.slug == slug)


def _game(league: config.League, team: config.Team, event_id: str, name: str, **kw: Any):
    raw = make_raw_event(event_id=event_id, name=name, url=f"https://www.ticketmaster.com/event/{event_id}", **kw)
    game = normalize_event(raw, league_slug=league.slug, tracked_team_slug=team.slug, tracked_team_name=team.name)
    assert game is not None
    return game


def _pwhl_games():
    # The 2026-27 opener as the league's schedule lists it (thepwhl.com,
    # read 2026-11-09): Saturday, December 5, 7:00 p.m. ET, Place Bell.
    montreal = _team(PWHL, "montreal-victoire")
    return [
        _game(
            PWHL,
            montreal,
            "P2",
            "Montreal Victoire vs Toronto Sceptres",
            date_time="2027-01-10T00:00:00Z",
            local_date="2027-01-09",
            local_time="19:00:00",
            venue_name="Place Bell",
            venue_city="Laval",
            venue_state="QC",
            timezone="America/Toronto",
        ),
        _game(
            PWHL,
            montreal,
            "P1",
            "Montreal Victoire vs PWHL Hamilton",
            date_time="2026-12-06T00:00:00Z",
            local_date="2026-12-05",
            local_time="19:00:00",
            venue_name="Place Bell",
            venue_city="Laval",
            venue_state="QC",
            timezone="America/Toronto",
        ),
    ]


def _sec_games():
    vandy = _team(SEC, "vanderbilt-commodores-womens-basketball")
    return [
        _game(
            SEC,
            vandy,
            "S1",
            "Vanderbilt Commodores Womens Basketball vs. Morehead State Eagles Womens Basketball",
            date_time=None,
            local_date="2026-11-09",
            local_time=None,
            time_tba=True,
            venue_name="Vanderbilt Memorial Gym",
            venue_city="Nashville",
            venue_state="TN",
            timezone="America/Chicago",
        )
    ]


def _league_page(league: config.League, games: list[Any], **extra: Any) -> str:
    return site.render_league(league={**league_data(league, games), **extra}, base_url=BASE_URL)


def _lede(html: str) -> str:
    m = re.search(r'<p class="lede">(.*?)</p>', html, re.S)
    assert m is not None
    return unescape(re.sub(r"<[^>]+>", "", m.group(1))).replace("\n", " ")


def _description(html: str) -> str:
    m = re.search(r'<meta name="description" content="([^"]*)"', html)
    assert m is not None
    return unescape(m.group(1))


def _roster_names(html: str) -> list[str]:
    return [unescape(n) for n in re.findall(r'<li><a href="/ncaaw-[^/"]+/[^/"]+/">([^<]+)</a></li>', html)]


def next_game_claims(html: str) -> list[str]:
    """The next-game claims a league page makes, from its lede and its
    description. An empty list means it makes none."""
    found = []
    if re.search(r"The next .+ game Ticketmaster lists is", _lede(html)):
        found.append("lede")
    if "Next game:" in _description(html):
        found.append("description")
    return found


def keyword_names(html: str) -> list[str]:
    """College team names shown as the Ticketmaster keyword, in the roster
    links and the lede's next-game sentence (the sentence after it names the
    league itself, "NCAA Women's Basketball (SEC)")."""
    next_game = _lede(html).split("Every ")[0]
    return [n for n in [*_roster_names(html), next_game] if TICKETMASTER_SUFFIX.search(n)]


def test_a_league_page_leads_with_the_next_listed_game():
    html = _league_page(PWHL, _pwhl_games())
    lede = _lede(html)
    assert lede.startswith(
        "The next PWHL game Ticketmaster lists is Montreal Victoire vs PWHL Hamilton at Place Bell in Laval, QC, "
        "on Saturday, December 5, 2026, at 7:00 PM EST. Every PWHL game Ticketmaster lists"
    )
    assert '<time datetime="2026-12-05T19:00:00-05:00">' in html
    description = _description(html)
    assert description.startswith("PWHL 2026-27 schedule. Next game: Sat, Dec 5, 2026, 7:00 PM EST,")
    assert "Montreal Victoire vs PWHL Hamilton" in description
    assert len(description) <= DESCRIPTION_MAX


def test_a_college_league_page_names_both_schools_without_the_keyword_suffix():
    html = _league_page(SEC, _sec_games())
    lede = _lede(html)
    # The time is TBA on Ticketmaster: the sentence says so, never a time.
    assert lede.startswith(
        "The next SEC women's basketball game Ticketmaster lists is Vanderbilt vs Morehead State Eagles at "
        "Vanderbilt Memorial Gym in Nashville, TN, on Monday, November 9, 2026, start time not announced yet."
    )
    description = _description(html)
    assert "Next game: Mon, Nov 9, 2026 (time TBA), Vanderbilt vs Morehead State Eagles." in description
    assert 120 <= len(description) <= DESCRIPTION_MAX
    assert keyword_names(html) == []


@pytest.mark.parametrize(
    "games, extra",
    [
        ([], {}),  # checked, nothing listed
        (_pwhl_games(), {"fetched": False}),  # not checked this build
    ],
    ids=["none_listed", "not_fetched"],
)
def test_no_next_game_claim_without_a_listed_dated_game(games: list[Any], extra: dict[str, Any]):
    html = _league_page(PWHL, games, **extra)
    assert next_game_claims(html) == []


def test_a_date_tbd_game_is_never_the_next_game():
    team = _team(PWHL, "boston-fleet")
    tbd = _game(
        PWHL, team, "T1", "Boston Fleet vs Ottawa Charge", date_tbd=True, date_time=None, local_date="2026-12-01"
    )
    html = _league_page(PWHL, [tbd])
    assert next_game_claims(html) == []


@pytest.mark.parametrize("league", [lg for lg in config.LEAGUES if lg.teams], ids=lambda lg: lg.slug)
def test_every_league_description_fits_with_a_long_next_game(league: config.League):
    team = league.teams[0]
    long_game = _game(
        league,
        team,
        "L1",
        f"{team.name} vs Minnesota Golden Gophers Womens Basketball",
        date_time="2026-12-06T00:00:00Z",
        local_date="2026-12-05",
        timezone="America/Toronto",
    )
    html = _league_page(league, [long_game])
    assert len(_description(html)) <= DESCRIPTION_MAX
    assert "lede" in next_game_claims(html)


@pytest.mark.parametrize("league", COLLEGE, ids=lambda lg: lg.slug)
def test_college_rosters_link_each_team_by_its_searched_name(league: config.League):
    html = _league_page(league, [])
    names = _roster_names(html)
    assert names == [t.search_title_name for t in league.teams]
    assert all(n.endswith(" women's basketball") for n in names)
    assert keyword_names(html) == []


def test_pro_rosters_keep_the_team_name():
    html = _league_page(PWHL, [])
    for team in PWHL.teams:
        assert f">{team.shown_name}</a></li>" in html


def test_a_college_team_page_names_its_neighbors_and_itself_by_the_searched_name():
    purdue = _team(BIG_TEN, "purdue-boilermakers-womens-basketball")
    penn_state = _team(BIG_TEN, "penn-state-nittany-lions-womens-basketball")
    away = _game(
        BIG_TEN,
        purdue,
        "A1",
        f"{penn_state.name} vs {purdue.name}",
        date_time="2026-12-30T00:00:00Z",
        local_date="2026-12-29",
        venue_name="Bryce Jordan Center",
        venue_city="University Park",
        venue_state="PA",
        timezone="America/New_York",
    )
    html = site.render_team(team={**team_data(purdue, BIG_TEN, [away]), "fetched_at": None}, base_url=BASE_URL)
    html = unescape(html)
    more = html[html.index('class="more-teams"') :]
    assert ">Iowa women's basketball</a>" in more
    assert "Womens Basketball</a>" not in more
    # Purdue sells through Paciolan (sellers.PRIMARY_SELLERS): the note names
    # the team as the lede does.
    assert "No Purdue women's basketball home game is listed by Ticketmaster right now." in html
    assert "No Purdue Boilermakers Womens Basketball home game" not in html


def test_an_empty_college_page_names_the_team_by_its_searched_name():
    purdue = _team(BIG_TEN, "purdue-boilermakers-womens-basketball")
    html = site.render_team(team={**team_data(purdue, BIG_TEN, []), "fetched_at": None}, base_url=BASE_URL)
    assert "No Purdue women's basketball games are listed by Ticketmaster right now." in unescape(html)


# ---------------------------------------------------------------- controls


def test_control_a_next_game_claim_without_a_dated_game_is_caught(monkeypatch: pytest.MonkeyPatch):
    def any_game(league: Any) -> Any:
        return league["games"][0] if league["games"] else None

    monkeypatch.setattr(site, "_next_league_game", any_game)
    team = _team(PWHL, "boston-fleet")
    tbd = _game(
        PWHL, team, "T1", "Boston Fleet vs Ottawa Charge", date_tbd=True, date_time=None, local_date="2026-12-01"
    )
    html = _league_page(PWHL, [tbd])
    assert "Date TBD" in _description(html) or "date TBD" in _description(html)  # the sabotage applied
    assert "description" in next_game_claims(html)  # and the check catches it


def test_control_the_old_not_fetched_rule_is_caught(monkeypatch: pytest.MonkeyPatch):
    def ignores_fetched(league: Any) -> Any:
        return next((g for g in league["games"] if g.get("start_local_date")), None)

    monkeypatch.setattr(site, "_next_league_game", ignores_fetched)
    html = _league_page(PWHL, _pwhl_games(), fetched=False)
    assert next_game_claims(html) == ["lede", "description"]  # caught


def test_control_the_keyword_roster_names_are_caught(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(site, "title_name_for", lambda league_slug, shown: shown)
    monkeypatch.setattr(site, "_opponent_label", lambda league_slug, opponent: opponent)
    html = _league_page(SEC, _sec_games())
    assert "Alabama Crimson Tide Womens Basketball</a>" in html  # the sabotage applied
    assert keyword_names(html) != []  # and the check catches it
