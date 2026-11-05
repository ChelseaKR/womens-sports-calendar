"""Another sport's word in a listing's name (DECISIONS 0031).

The real case is Texas's next home game on nexthomegame.com on 2026-11-05:
Ticketmaster event Z7r9jZ1AAZSFK, "Texas Longhorns Womens Basketball vs
Northern Colorado Bears Football", Sat Nov 7 2026 at 7:00 PM CT at Moody
Center ATX, Austin, TX (copied from the live page). texaslonghorns.com's
2026-27 women's basketball schedule lists that game as Texas vs Northern
Colorado, Saturday, November 7, 7:00 PM CT, Moody Center: a women's
basketball game whose opponent Ticketmaster labeled with the football
team's name. The page said the game was "against Northern Colorado Bears
Football".

The Tennessee case from the same check, the "Season Tickets" row dated Sep
21 under Upcoming games, is test_listings.py's SEASON_TICKETS and is built
here too, so both live errors are checked in one built site.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from icalendar import Calendar

from wsc_pipeline import build as build_module
from wsc_pipeline import listings, validate_ics
from wsc_pipeline.config import LEAGUES, league_by_slug
from wsc_pipeline.normalize import Game, normalize_event

from .conftest import make_raw_event
from .test_listings import SEASON_TICKETS, TENNESSEE

TEXAS = "texas-longhorns-womens-basketball"
_MOODY = {
    "venue_name": "Moody Center ATX",
    "venue_city": "Austin",
    "venue_state": "TX",
    "timezone": "America/Chicago",
}
NORTHERN_COLORADO = make_raw_event(
    event_id="Z7r9jZ1AAZSFK",
    name="Texas Longhorns Womens Basketball vs Northern Colorado Bears Football",
    date_time="2026-11-08T01:00:00Z",
    local_date="2026-11-07",
    local_time="19:00:00",
    url="https://www.ticketmaster.com/event/Z7r9jZ1AAZSFK",
    **_MOODY,
)
# Texas's next listing on the same live page, unchanged by any rule here.
SOUTH_DAKOTA_STATE = make_raw_event(
    event_id="TX-SDSU",
    name="Texas Longhorns Womens Basketball vs South Dakota State Jackrabbits Womens Basketball",
    date_time=None,
    local_date="2026-11-11",
    local_time=None,
    time_tba=True,
    url="https://www.ticketmaster.com/event/TX-SDSU",
    **_MOODY,
)

FETCHED_AT = datetime(2026, 11, 5, 8, 25, tzinfo=UTC)


def _game(league_slug: str, team_slug: str, raw: dict) -> Game:
    league = league_by_slug(league_slug)
    team = next(t for t in league.teams if t.slug == team_slug)
    game = normalize_event(raw, league_slug=league_slug, tracked_team_slug=team_slug, tracked_team_name=team.name)
    assert game is not None
    return game


def test_the_mislabeled_opponent_is_kept_without_the_other_sports_word():
    game = _game("ncaaw-sec", TEXAS, NORTHERN_COLORADO)
    kept, dropped = listings.only_games([game])
    assert [g.event_id for g in kept] == ["Z7r9jZ1AAZSFK"]  # a real game still lists
    assert dropped == []

    fixed, relabeled = listings.fix_opponent_sport(kept)
    (g,) = fixed
    assert g.event_id == "Z7r9jZ1AAZSFK"  # same event, so the same calendar UID
    assert g.home_team == "Texas Longhorns Womens Basketball"
    assert g.away_team == "Northern Colorado Bears"
    assert g.raw_event_name == "Texas Longhorns Womens Basketball vs Northern Colorado Bears"
    assert g.start_utc == game.start_utc and g.venue_name == game.venue_name
    assert [r.describe() for r in relabeled] == [
        f"{TEXAS}: Z7r9jZ1AAZSFK (Texas Longhorns Womens Basketball vs Northern Colorado Bears Football): "
        "opponent shown as 'Northern Colorado Bears'"
    ]


def test_a_real_game_is_returned_unchanged():
    game = _game("ncaaw-sec", TEXAS, SOUTH_DAKOTA_STATE)
    fixed, relabeled = listings.fix_opponent_sport([game])
    assert fixed == [game] and relabeled == []
    assert listings._non_game_reason(game) is None


@pytest.mark.parametrize(
    "name",
    [
        # Football on the tracked team's own side, or on both sides.
        "Texas Longhorns Football vs Northern Colorado Bears Football",
        "Northern Colorado Bears Womens Basketball vs Texas Longhorns Football",
        "Texas Longhorns Football vs Northern Colorado Bears Womens Basketball",
        # The tracked side never says it is basketball, so nothing shows
        # whose game it is.
        "Texas Longhorns vs Northern Colorado Bears Football",
        # No matchup: an event of another sport.
        "Texas Longhorns Football Spring Game",
        "Texas Longhorns Volleyball vs Northern Colorado Bears Volleyball",
        "Texas Longhorns Womens Basketball vs Northern Colorado Bears Baseball - Football Day",
    ],
)
def test_another_sports_event_never_reaches_a_womens_page(name: str):
    game = _game("ncaaw-sec", TEXAS, make_raw_event(name=name, **_MOODY))
    assert listings._non_game_reason(game) == "names another sport"
    kept, dropped = listings.only_games([game])
    assert kept == [] and [d.reason for d in dropped] == ["names another sport"]


@pytest.mark.parametrize(
    "name",
    [
        "Texas Longhorns Womens Basketball vs Northern Colorado Bears Mens Basketball",
        "Texas Longhorns Men's Basketball vs Northern Colorado Bears Football",
    ],
)
def test_a_mens_game_is_still_dropped_first(name: str):
    game = _game("ncaaw-sec", TEXAS, make_raw_event(name=name, **_MOODY))
    assert listings._non_game_reason(game) == "names a men's team"


def test_a_ticket_product_is_still_not_a_game():
    game = _game("ncaaw-sec", TEXAS, make_raw_event(name="Texas Longhorns Women's Basketball Season Tickets", **_MOODY))
    assert listings._non_game_reason(game) == "a ticket product, not a game"


@pytest.mark.parametrize(
    ("league_slug", "team_slug", "name"),
    [
        # A soccer league's "football" is its own sport.
        ("nwsl", "angel-city", "Angel City Football Club vs San Diego Wave FC"),
        ("nwsl", "bay-fc", "Bay FC vs Portland Thorns FC"),
        ("wnba", "las-vegas-aces", "Las Vegas Aces vs Seattle Storm"),
        ("ncaaw-sec", TEXAS, "Texas Longhorns Womens Basketball vs Harvard Crimson Womens Basketball"),
    ],
)
def test_real_games_in_other_leagues_are_kept(league_slug: str, team_slug: str, name: str):
    game = _game(league_slug, team_slug, make_raw_event(name=name))
    assert listings._non_game_reason(game) is None
    assert listings.fix_opponent_sport([game]) == ([game], [])


def test_a_basketball_word_is_another_sport_in_a_soccer_league():
    game = _game("nwsl", "angel-city", make_raw_event(name="Angel City vs Los Angeles Sparks Basketball"))
    assert listings._non_game_reason(game) == "names another sport"


def _build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    games = [
        _game("ncaaw-sec", TEXAS, NORTHERN_COLORADO),
        _game("ncaaw-sec", TEXAS, SOUTH_DAKOTA_STATE),
        _game("ncaaw-sec", TENNESSEE, SEASON_TICKETS),
    ]
    empty = {lg.slug: set() for lg in LEAGUES}
    monkeypatch.setattr(
        build_module, "fetch_all_games", lambda api_key: (games, empty, {k: set() for k in empty}, 3, 300)
    )
    out_dir = tmp_path / "dist"
    build_module.build(
        out_dir=out_dir, base_url="https://nexthomegame.com", api_key="fake-key", affiliate_id=None, now=FETCHED_AT
    )
    return out_dir


def _summaries(out_dir: Path, path: str) -> dict[str, str]:
    cal = Calendar.from_ical((out_dir / "ics" / path).read_bytes())
    return {str(ev["uid"]): str(ev["summary"]) for ev in cal.walk("VEVENT")}


def test_the_built_pages_name_the_real_opponent_and_list_no_ticket_product(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    out_dir = _build(tmp_path, monkeypatch)

    texas_html = (out_dir / "ncaaw-sec" / TEXAS / "index.html").read_text()
    assert "Football" not in texas_html
    assert "against Northern Colorado Bears at Moody Center ATX" in texas_html
    assert "Texas Longhorns Womens Basketball vs South Dakota State Jackrabbits Womens Basketball" in texas_html
    assert _summaries(out_dir, f"ncaaw-sec/{TEXAS}.ics") == {
        "tm-Z7r9jZ1AAZSFK@womens-sports-calendar.invalid": "Texas Longhorns Womens Basketball vs Northern Colorado Bears",
        "tm-TX-SDSU@womens-sports-calendar.invalid": (
            "Texas Longhorns Womens Basketball vs South Dakota State Jackrabbits Womens Basketball (time TBA)"
        ),
    }
    league_feed = (out_dir / "ics" / "ncaaw-sec.ics").read_text()
    assert "Football" not in league_feed

    tennessee_html = (out_dir / "ncaaw-sec" / TENNESSEE / "index.html").read_text()
    assert "Season Tickets" not in tennessee_html
    assert "Sep 21" not in tennessee_html
    assert _summaries(out_dir, f"ncaaw-sec/{TENNESSEE}.ics") == {}

    report = (out_dir / "COVERAGE.txt").read_text()
    assert "1 listing(s) named the opponent with another sport's word" in report
    assert "Z7r9jZ1AAZSFK" in report and "G5viZ_KhLQpM1" in report

    validate_ics.validate_dist(out_dir)


def test_negative_control_without_the_fix_the_page_says_football(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The sabotage must change the output: with fix_opponent_sport a no-op,
    the built page names "Northern Colorado Bears Football" again, so the
    test above is what holds it off the page."""
    monkeypatch.setattr(build_module.listings, "fix_opponent_sport", lambda games: (list(games), []))
    out_dir = _build(tmp_path, monkeypatch)
    texas_html = (out_dir / "ncaaw-sec" / TEXAS / "index.html").read_text()
    assert "against Northern Colorado Bears Football" in texas_html
