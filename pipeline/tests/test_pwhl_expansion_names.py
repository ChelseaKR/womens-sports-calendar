"""The four PWHL expansion teams under the names the league gave them.

On 2026-11-10 the PWHL named its expansion teams the Detroit Clutch, the
Hamilton Havoc, the San Jose Sea Lions and the Vegas Vanguards (the teams'
pages on thepwhl.com, read 2026-11-14). Ticketmaster renamed most of their
listings the next day. From the 2026-11-12 build on, every game listed under
a new name left the team's own page and feed: the 2026-11-14 build had 2
games on the Detroit page and 4 on San Jose's, while the PWHL calendar
listed 14 "Detroit Clutch" and 14 "San Jose Sea Lions" games, found by the
opponents' searches. Games between two renamed teams were in no calendar at
all (DECISIONS 0041).

Event names below are constructed in the shapes the live PWHL calendar
carried on 2026-11-14; none is claimed to be a live listing.
"""

from __future__ import annotations

import dataclasses

import pytest

from wsc_pipeline import build as build_module
from wsc_pipeline import config, site, site_data
from wsc_pipeline.normalize import normalize_event, team_is_participant_as_any
from wsc_pipeline.official_tickets import OFFICIAL_TEAM_TICKETS
from wsc_pipeline.site_data import team_data

from .conftest import make_raw_event

PWHL = config.league_by_slug("pwhl")
BASE_URL = "https://nexthomegame.com"

RENAMED = {
    # slug: (new name, former name, French name or None)
    "pwhl-detroit": ("Detroit Clutch", "PWHL Detroit", None),
    "pwhl-hamilton": ("Hamilton Havoc", "PWHL Hamilton", "Havoc de Hamilton"),
    "pwhl-san-jose": ("San Jose Sea Lions", "PWHL San Jose", "Sea Lions de San José"),
    "pwhl-las-vegas": ("Vegas Vanguards", "PWHL Las Vegas", "Vanguards de Vegas"),
}


def _team(slug: str) -> config.Team:
    return next(t for t in PWHL.teams if t.slug == slug)


def _accepts(team: config.Team, name: str) -> bool:
    return team_is_participant_as_any(team.match_names, {"name": name}, team.not_this_team)


@pytest.mark.parametrize("slug", sorted(RENAMED))
def test_each_team_keeps_its_slug_and_takes_its_new_name(slug: str):
    new, former, french = RENAMED[slug]
    team = _team(slug)
    assert team.slug == slug, "a published slug never changes (DECISIONS 0017)"
    assert team.name == new
    assert team.shown_name == new
    assert team.search_title_name == new
    expected = (new, former, french) if french else (new, former)
    assert team.all_names == expected
    assert team.former_slugs == ()


@pytest.mark.parametrize(
    ("slug", "name"),
    [
        ("pwhl-detroit", "Detroit Clutch vs. New York Sirens"),
        ("pwhl-detroit", "Ottawa Charge vs. Detroit Clutch"),
        ("pwhl-detroit", "Battle On Bay Street: Detroit Clutch at Toronto Sceptres"),
        ("pwhl-detroit", "PWHL Las Vegas vs. PWHL Detroit"),
        ("pwhl-hamilton", "Hamilton Havoc vs. Ottawa Charge"),
        ("pwhl-hamilton", "La Victoire De Montréal vs Havoc de Hamilton"),
        ("pwhl-hamilton", "Toronto Sceptres vs. PWHL Hamilton"),
        ("pwhl-san-jose", "San Jose Sea Lions vs. Minnesota Frost"),
        ("pwhl-san-jose", "La Victoire De Montréal vs Sea Lions de San José"),
        ("pwhl-san-jose", "PWHL Hamilton vs. PWHL San Jose"),
        ("pwhl-las-vegas", "Vegas Vanguards vs. Boston Fleet"),
        ("pwhl-las-vegas", "La Victoire De Montréal V Vanguards de Vegas"),
        ("pwhl-las-vegas", "PWHL Las Vegas vs. Minnesota Frost"),
    ],
)
def test_every_name_ticketmaster_uses_is_recognized(slug: str, name: str):
    assert _accepts(_team(slug), name)


@pytest.mark.parametrize(
    ("slug", "name"),
    [
        ("pwhl-detroit", "Detroit Red Wings vs. Toronto Maple Leafs"),
        ("pwhl-hamilton", "Hamilton Tiger-Cats vs. Toronto Argonauts"),
        ("pwhl-san-jose", "San Jose Sharks vs. Vegas Golden Knights"),
        ("pwhl-las-vegas", "Vegas Golden Knights vs. San Jose Sharks"),
        ("pwhl-san-jose", "Ottawa Charge vs. Toronto Sceptres"),
    ],
)
def test_the_new_names_loosen_nothing_else(slug: str, name: str):
    """A city's other teams are still not these teams."""
    assert not _accepts(_team(slug), name)


@pytest.mark.parametrize(
    ("slug", "name", "home"),
    [
        ("pwhl-detroit", "Detroit Clutch vs. New York Sirens", True),
        ("pwhl-detroit", "Ottawa Charge vs. Detroit Clutch", False),
        ("pwhl-san-jose", "San Jose Sea Lions vs. Minnesota Frost", True),
        ("pwhl-san-jose", "La Victoire De Montréal vs Sea Lions de San José", False),
        ("pwhl-hamilton", "La Victoire De Montréal vs Havoc de Hamilton", False),
        ("pwhl-las-vegas", "Vegas Vanguards vs. Boston Fleet", True),
    ],
)
def test_the_home_flag_reads_the_new_names(slug: str, name: str, home: bool):
    team = _team(slug)
    game = normalize_event(
        make_raw_event(event_id="EVT-X", name=name),
        league_slug="pwhl",
        tracked_team_slug=team.slug,
        tracked_team_name=team.name,
    )
    assert game is not None
    assert site_data.tracked_team_is_home(team, game) is home


class _KeywordClient:
    """A DiscoveryClient stand-in that answers by keyword and records every
    search, so the test sees which names are searched."""

    def __init__(self, by_keyword: dict[str, list[dict]]):
        from wsc_pipeline.ticketmaster import CrawlBudget

        self._by_keyword = by_keyword
        self.searched: list[tuple[str, str]] = []
        self.budget = CrawlBudget()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def search_team_events(self, team_slug: str, team_name: str, country_codes: tuple[str, ...]):
        self.searched.append((team_slug, team_name))
        return self._by_keyword.get(team_name, []), False


CLUTCH_HOME = make_raw_event(event_id="EVT-CLUTCH-HOME", name="Detroit Clutch vs. New York Sirens")
CLUTCH_V_SEA_LIONS = make_raw_event(event_id="EVT-CLUTCH-SJ", name="Detroit Clutch vs. San Jose Sea Lions")
SEA_LIONS_HOME = make_raw_event(event_id="EVT-SJ-HOME", name="San Jose Sea Lions vs. Minnesota Frost")
OLD_NAME_AWAY = make_raw_event(event_id="EVT-OLD", name="PWHL Las Vegas vs. PWHL Detroit")


def _fetch(monkeypatch: pytest.MonkeyPatch, client: _KeywordClient):
    monkeypatch.setattr(build_module, "DiscoveryClient", lambda api_key: client)
    games, _truncated, _mismatched, _requests, _bytes = build_module.fetch_all_games("fake-key")
    return games


def _kept(games, slug: str) -> list[str]:
    return sorted(g.event_id for g in games if g.league_slug == "pwhl" and g.tracked_team_slug == slug)


def test_each_new_old_and_french_name_is_searched(monkeypatch: pytest.MonkeyPatch):
    client = _KeywordClient({})
    # No game at all is a failed fetch; one unrelated game keeps it a build.
    client._by_keyword["Boston Fleet"] = [make_raw_event(event_id="EVT-B", name="Boston Fleet vs. Ottawa Charge")]
    _fetch(monkeypatch, client)
    for slug, (new, former, french) in RENAMED.items():
        searched = [name for s, name in client.searched if s == slug]
        assert searched == [n for n in (new, former, french) if n], slug


def test_the_renamed_teams_games_reach_their_own_pages_and_feeds(monkeypatch: pytest.MonkeyPatch):
    """End to end through fetch_all_games: a home game under the new name, a
    game between two renamed teams and a game still under the old name are
    each kept for every renamed team they name."""
    client = _KeywordClient(
        {
            "Detroit Clutch": [CLUTCH_HOME, CLUTCH_V_SEA_LIONS],
            "PWHL Detroit": [OLD_NAME_AWAY],
            "San Jose Sea Lions": [SEA_LIONS_HOME],
        }
    )
    games = _fetch(monkeypatch, client)
    assert _kept(games, "pwhl-detroit") == ["EVT-CLUTCH-HOME", "EVT-CLUTCH-SJ", "EVT-OLD"]
    assert _kept(games, "pwhl-san-jose") == ["EVT-CLUTCH-SJ", "EVT-SJ-HOME"]
    assert _kept(games, "pwhl-las-vegas") == ["EVT-OLD"]
    assert _kept(games, "new-york-sirens") == ["EVT-CLUTCH-HOME"]


def test_without_the_new_names_the_games_are_lost(monkeypatch: pytest.MonkeyPatch):
    """Negative control: the registry as it was before this change (the
    "PWHL <city>" keyword alone) keeps only the old-name game, the 2026-11-14
    live state."""
    old_teams = tuple(
        dataclasses.replace(t, name=RENAMED[t.slug][1], search_names=(), history_note=None) if t.slug in RENAMED else t
        for t in PWHL.teams
    )
    old_pwhl = dataclasses.replace(PWHL, teams=old_teams)
    leagues = tuple(old_pwhl if lg.slug == "pwhl" else lg for lg in config.LEAGUES)
    monkeypatch.setattr(config, "LEAGUES", leagues)
    client = _KeywordClient(
        {
            "Detroit Clutch": [CLUTCH_HOME, CLUTCH_V_SEA_LIONS],
            "PWHL Detroit": [OLD_NAME_AWAY],
            "San Jose Sea Lions": [SEA_LIONS_HOME],
            "New York Sirens": [CLUTCH_HOME],
        }
    )
    games = _fetch(monkeypatch, client)
    assert _kept(games, "pwhl-detroit") == ["EVT-OLD"]
    assert _kept(games, "pwhl-san-jose") == []
    assert _kept(games, "new-york-sirens") == ["EVT-CLUTCH-HOME"]


@pytest.mark.parametrize("slug", sorted(RENAMED))
def test_the_team_page_carries_the_new_name_and_says_what_it_was(slug: str):
    new, former, _french = RENAMED[slug]
    team = _team(slug)
    home = make_raw_event(
        event_id=f"EVT-{slug}",
        name=f"{new} vs. Ottawa Charge",
        date_time="2026-12-13T19:00:00Z",
        local_date="2026-12-13",
        local_time="14:00:00",
        timezone="America/Toronto",
    )
    game = normalize_event(home, league_slug="pwhl", tracked_team_slug=team.slug, tracked_team_name=team.name)
    assert game is not None
    payload = {**team_data(team, PWHL, [game]), "fetched_at": "2026-11-14T08:21:54+00:00"}
    html = site.render_team(team=payload, base_url=BASE_URL)
    assert f"<title>{new} schedule 2026" in html
    assert (
        f'<p class="team-history">{former} is now the {new}. The league announced the name on November 10, 2026.</p>'
        in html
    )
    assert f'href="webcal://nexthomegame.com/ics/pwhl/{slug}.ics"' in html


@pytest.mark.parametrize("slug", sorted(RENAMED))
def test_the_official_ticket_link_is_the_new_address(slug: str):
    url = OFFICIAL_TEAM_TICKETS[("pwhl", slug)].url
    path = {
        "pwhl-detroit": "detroit-clutch",
        "pwhl-hamilton": "hamilton-havoc",
        "pwhl-san-jose": "san-jose-sea-lions",
        "pwhl-las-vegas": "vegas-vanguards",
    }[slug]
    assert url == f"https://www.thepwhl.com/en/teams/{path}/tickets"
