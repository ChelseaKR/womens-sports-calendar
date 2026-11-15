"""A cancelled or postponed game is not "the next game".

Before 2026-11-15 a team page skipped only a cancelled home game when it
picked its next home game, so a postponed one, still listed at the date it
was moved from (ics.FEED_STATUS), led the hero, the lede and the search
description. A league page skipped neither: its lede and description could
name a cancelled game as the next one. And a team with no home game listed
led its "Next game, away" box with a cancelled game. Now each skips both,
and a postponed home game leads only when it is the only one listed, so the
page names it with its status rather than saying none is listed.

Each control breaks the rule and asserts the check catches it."""

from __future__ import annotations

import re
from html import unescape
from typing import Any

from wsc_pipeline import site
from wsc_pipeline.site_data import NOT_NEXT_STATUSES, league_data, next_home_game, team_data

from .fixture_site import BASE_URL
from .test_league_next_game import PWHL, _game, _team

MONTREAL = _team(PWHL, "montreal-victoire")
TORONTO = _team(PWHL, "toronto-sceptres")


def _home(event_id: str, day: int, opponent: str = "Toronto Sceptres", **kw: Any):
    fields: dict[str, Any] = {
        "date_time": f"2026-12-{day:02d}T00:00:00Z",
        "local_date": f"2026-12-{day - 1:02d}",
        "local_time": "19:00:00",
        "venue_name": "Place Bell",
        "venue_city": "Laval",
        "venue_state": "QC",
        "timezone": "America/Toronto",
    }
    return _game(PWHL, MONTREAL, event_id, f"Montreal Victoire vs {opponent}", **{**fields, **kw})


def _away(event_id: str, day: int, **kw: Any):
    return _game(
        PWHL,
        MONTREAL,
        event_id,
        "Toronto Sceptres vs Montreal Victoire",
        date_time=f"2026-12-{day:02d}T00:00:00Z",
        local_date=f"2026-12-{day - 1:02d}",
        local_time="19:00:00",
        venue_name="Coca-Cola Coliseum",
        venue_city="Toronto",
        venue_state="ON",
        timezone="America/Toronto",
        **kw,
    )


def _lede(html: str) -> str:
    m = re.search(r'<p class="lede">(.*?)</p>', html, re.S)
    assert m is not None
    return unescape(re.sub(r"<[^>]+>", "", m.group(1))).replace("\n", " ")


def _description(html: str) -> str:
    m = re.search(r'<meta name="description" content="([^"]*)"', html)
    assert m is not None
    return unescape(m.group(1))


def _hero(html: str) -> str:
    start = html.index('<section class="next-game')
    return unescape(html[start : html.index("</section>", start)])


def test_a_postponed_home_game_does_not_lead_when_a_later_one_is_listed():
    games = [_home("PP", 6, status="postponed"), _home("OK", 10, opponent="Ottawa Charge")]
    team = team_data(MONTREAL, PWHL, games)
    assert team["next_home_event_id"] == "OK"
    html = site.render_team(team=team, base_url=BASE_URL)
    assert "Ottawa Charge" in _lede(html).split(".")[0]
    assert "Dec 9" in _description(html)


def test_a_postponed_home_game_still_leads_when_it_is_the_only_one():
    team = team_data(MONTREAL, PWHL, [_home("PP", 6, status="postponed")])
    assert team["next_home_event_id"] == "PP"
    assert "Ticketmaster lists it as postponed." in _lede(site.render_team(team=team, base_url=BASE_URL))


def test_a_cancelled_home_game_never_leads():
    assert team_data(MONTREAL, PWHL, [_home("CX", 6, status="cancelled")])["next_home_event_id"] is None


def test_a_rescheduled_home_game_still_leads():
    games = [_home("RS", 6, status="rescheduled"), _home("OK", 10)]
    assert team_data(MONTREAL, PWHL, games)["next_home_event_id"] == "RS"


def test_control_the_old_rule_picks_the_postponed_game():
    """Sabotage: Postponed is treated as going ahead. The check above fails."""
    games = [_home("PP", 6, status="postponed"), _home("OK", 10)]
    dicts = team_data(MONTREAL, PWHL, games)["games"]
    old = next(d for d in dicts if d["tracked_team_is_home"] is True and d["status"] != "Cancelled")
    assert old["event_id"] == "PP"
    new = next_home_game(dicts)
    assert new is not None and new["event_id"] == "OK"
    assert "Postponed" in NOT_NEXT_STATUSES


def test_the_league_page_skips_a_cancelled_and_a_postponed_game():
    games = [
        _home("CX", 6, status="cancelled"),
        _home("PP", 7, status="postponed"),
        _home("OK", 10, opponent="Ottawa Charge"),
    ]
    html = site.render_league(league=league_data(PWHL, games), base_url=BASE_URL)
    first = _lede(html).split(". ")[0]
    assert "Ottawa Charge" in first and "Toronto" not in first
    assert "cancelled" not in _lede(html) and "postponed" not in _lede(html)
    assert "Dec 9" in _description(html)


def test_the_league_page_names_no_next_game_when_every_game_is_off():
    games = [_home("CX", 6, status="cancelled"), _home("PP", 7, status="postponed")]
    html = site.render_league(league=league_data(PWHL, games), base_url=BASE_URL)
    assert "game Ticketmaster lists is" not in _lede(html)
    assert "Next game:" not in _description(html)


def test_the_away_box_skips_a_cancelled_game():
    """No home game listed: the box leads with the next away game that is on."""
    games = [_away("CX", 6, status="cancelled"), _away("OK", 10)]
    hero = _hero(site.render_team(team=team_data(MONTREAL, PWHL, games), base_url=BASE_URL))
    assert "Next game, away" in hero
    assert "Dec 9" in hero and "Dec 5" not in hero


def test_the_away_box_shows_a_cancelled_game_when_it_is_the_only_one():
    hero = _hero(
        site.render_team(team=team_data(MONTREAL, PWHL, [_away("CX", 6, status="cancelled")]), base_url=BASE_URL)
    )
    assert "Dec 5" in hero and "Cancelled" in hero
