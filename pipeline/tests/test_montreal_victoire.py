"""The Montreal Victoire's games reach its own page and feed.

The live build of 2026-11-04 listed 23 Victoire games in the PWHL calendar
(each found by the opponent's search) and 1 on the Victoire's own page and
feed. Ticketmaster names the team "Montréal Victoire", and in French, "La
Victoire De Montréal", for its home games; the participant check turned the
"é" into a space, so the keyword "Montreal Victoire" matched neither, and
the page said no Victoire home game was listed.

Event names below are constructed in the shapes the live PWHL calendar
carried on 2026-11-04; none is claimed to be a live listing.
"""

from __future__ import annotations

import pytest

from wsc_pipeline import build as build_module
from wsc_pipeline import normalize, site_data
from wsc_pipeline.config import league_by_slug
from wsc_pipeline.normalize import normalize_event, team_is_participant_as_any

from .conftest import make_raw_event
from .test_build import _FakeDiscoveryClient

PWHL = league_by_slug("pwhl")
VICTOIRE = next(t for t in PWHL.teams if t.slug == "montreal-victoire")

ACCENTED = "Montréal Victoire vs. Ottawa Charge"
FRENCH = "La Victoire De Montréal v PWHL Hamilton"
AWAY = "Boston Fleet vs. Montréal Victoire"


def _accepts(name: str) -> bool:
    return team_is_participant_as_any(VICTOIRE.match_names, {"name": name}, VICTOIRE.not_this_team)


@pytest.mark.parametrize(
    "name",
    [
        ACCENTED,
        FRENCH,
        AWAY,
        "La Victoire De Montréal V Pwhl San Jose",
        "PWHL Las Vegas vs. Montreal Victoire",
    ],
)
def test_the_victoire_is_recognized_in_every_name_ticketmaster_uses(name: str):
    assert _accepts(name)


def test_without_the_accent_fold_the_accented_name_matches_nothing(monkeypatch: pytest.MonkeyPatch):
    """Negative control: the match above is the fold's doing."""
    monkeypatch.setattr(normalize, "_fold_accents", lambda s: s)
    assert not _accepts(ACCENTED)
    assert not _accepts(AWAY)


def test_the_fold_loosens_nothing_but_the_accent():
    """Another Montreal team, or a game the Victoire are not in, is still not
    the Victoire's."""
    assert not _accepts("Canadiens de Montréal vs Sénateurs d'Ottawa")
    assert not _accepts("Laval Rocket vs Belleville Senators")
    assert not _accepts("Ottawa Charge vs. Toronto Sceptres")


def test_the_french_name_is_searched_once_more_and_counted():
    assert VICTOIRE.name == "Montreal Victoire"
    assert VICTOIRE.all_names == ("Montreal Victoire", "Victoire de Montréal")
    assert VICTOIRE.shown_name == "Montreal Victoire"


@pytest.mark.parametrize(("name", "home"), [(ACCENTED, True), (FRENCH, True), (AWAY, False)])
def test_the_home_flag_reads_the_accented_and_french_names(name: str, home: bool):
    game = normalize_event(
        make_raw_event(event_id="EVT-MTL", name=name, venue_name="Place Bell", venue_city="Laval"),
        league_slug="pwhl",
        tracked_team_slug=VICTOIRE.slug,
        tracked_team_name=VICTOIRE.name,
    )
    assert game is not None
    assert site_data.tracked_team_is_home(VICTOIRE, game) is home


def test_fetch_keeps_the_victoire_games_its_own_search_returns(monkeypatch: pytest.MonkeyPatch):
    """End to end through fetch_all_games: every Victoire game its search
    returns is kept for the Victoire, and only the unrelated one is counted
    as a mismatch."""
    events = [
        make_raw_event(event_id="EVT-A", name=ACCENTED),
        make_raw_event(event_id="EVT-F", name=FRENCH),
        make_raw_event(event_id="EVT-W", name=AWAY),
        make_raw_event(event_id="EVT-X", name="Laval Rocket vs Belleville Senators"),
    ]
    fake_client = _FakeDiscoveryClient({VICTOIRE.slug: events})
    monkeypatch.setattr(build_module, "DiscoveryClient", lambda api_key: fake_client)

    games, _truncated, mismatched, _requests, _bytes = build_module.fetch_all_games("fake-key")

    kept = sorted(g.event_id for g in games if g.tracked_team_slug == VICTOIRE.slug)
    assert kept == ["EVT-A", "EVT-F", "EVT-W"]
    assert mismatched["pwhl"] == {VICTOIRE.slug}
