"""A league page's "Next home game for each team" list, behind
site_data.LEAGUE_NEXT_HOME_LIST (off until its wording is approved).

Off, the league payload has no `next_home_by_team` and the page has no list,
so pages and sitemap lastmod are as before. On, every team is listed A to Z,
linked to its page, with the game its own page leads with (team_data's
next_home_event_id), or "no home game listed by Ticketmaster". A build that
fetched nothing gets no list: not checked is never "none listed"."""

from __future__ import annotations

import re
from html import unescape

from wsc_pipeline import site, site_data
from wsc_pipeline.site_data import league_data, team_data

from .fixture_site import BASE_URL
from .test_next_game_status import MONTREAL, PWHL, _home


def _games():
    return [_home("PP", 6, status="postponed"), _home("OK", 10, opponent="Ottawa Charge")]


def _list(html: str) -> list[str]:
    if 'class="league-next-home"' not in html:
        return []
    start = html.index('class="league-next-home"')
    block = html[start : html.index("</section>", start)]
    return [
        unescape(re.sub(r"<[^>]+>", "", li)).replace("\n", " ") for li in re.findall(r"<li>(.*?)</li>", block, re.S)
    ]


def test_off_by_default_and_the_payload_is_unchanged():
    assert site_data.LEAGUE_NEXT_HOME_LIST is False
    payload = league_data(PWHL, _games())
    assert "next_home_by_team" not in payload
    assert payload == league_data(PWHL, _games(), next_home_list=False)
    assert _list(site.render_league(league=payload, base_url=BASE_URL)) == []


def test_on_lists_every_team_a_to_z_with_its_pages_next_home_game():
    payload = league_data(PWHL, _games(), next_home_list=True)
    html = site.render_league(league=payload, base_url=BASE_URL)
    rows = _list(html)
    assert len(rows) == len(PWHL.teams)
    names = [r.split(":")[0] for r in rows]
    assert names == sorted(names, key=str.casefold)
    montreal = next(r for r in rows if r.startswith("Montreal Victoire:"))
    assert montreal == "Montreal Victoire: Wed, Dec 9, 2026, 7:00 PM EST vs Ottawa Charge"
    assert (
        payload["next_home_by_team"]["montreal-victoire"] == team_data(MONTREAL, PWHL, _games())["next_home_event_id"]
    )
    others = [r for r in rows if not r.startswith("Montreal Victoire:")]
    assert all(r.endswith(": no home game listed by Ticketmaster") for r in others)
    assert '<a href="/pwhl/montreal-victoire/">Montreal Victoire</a>' in html
    assert html.count('id="league-next-home-heading"') == 1


def test_the_module_flag_turns_it_on(monkeypatch):
    monkeypatch.setattr(site_data, "LEAGUE_NEXT_HOME_LIST", True)
    assert "next_home_by_team" in league_data(PWHL, _games())


def test_a_build_that_fetched_nothing_gets_no_list():
    payload = league_data(PWHL, [], fetched=False, next_home_list=True)
    assert "next_home_by_team" not in payload
    assert _list(site.render_league(league=payload, base_url=BASE_URL)) == []


def test_control_a_list_naming_the_wrong_game_is_caught():
    """Sabotage: point Montreal at the postponed game; the row check fails."""
    payload = league_data(PWHL, _games(), next_home_list=True)
    payload["next_home_by_team"]["montreal-victoire"] = "PP"
    rows = _list(site.render_league(league=payload, base_url=BASE_URL))
    montreal = next(r for r in rows if r.startswith("Montreal Victoire:"))
    assert montreal != "Montreal Victoire: Wed, Dec 9, 2026, 7:00 PM EST vs Ottawa Charge"
    assert "Postponed" in montreal
