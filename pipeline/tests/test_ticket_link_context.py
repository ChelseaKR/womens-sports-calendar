"""A ticket link names the game's status and says "date TBD" plainly.

A screen reader's list of links reads each link alone, away from its row. A
games-table link to a cancelled game said "Tickets (AXS) for A vs B on Fri,
Sep 18, 2026, 7:00 PM PDT", with nothing of the "Cancelled" beside the date;
it now ends "(Cancelled)". A game with no date read "on Date TBD"; it now
reads ", date TBD". The visible word still starts the link (WCAG 2.5.3)."""

from __future__ import annotations

import re
from html import unescape

from wsc_pipeline import site
from wsc_pipeline.site_data import team_data

from .fixture_site import BASE_URL
from .test_next_game_status import MONTREAL, PWHL, _away, _home


def _links(html: str) -> list[str]:
    """Each games-table ticket link's accessible name."""
    return [unescape(re.sub(r"<[^>]+>", "", m)) for m in re.findall(r"<a [^>]*>(Tickets \(.*?)</a>", html, re.S)]


def _page(*games) -> str:
    return site.render_team(team=team_data(MONTREAL, PWHL, list(games)), base_url=BASE_URL)


def test_a_cancelled_games_link_says_so():
    names = _links(_page(_away("CX", 6, status="cancelled"), _home("OK", 10)))
    assert any(n.startswith("Tickets (") and n.endswith("(Cancelled)") for n in names), names
    assert sum("(Cancelled)" in n for n in names) == 1


def test_a_postponed_games_link_says_so():
    names = _links(_page(_home("PP", 6, status="postponed"), _home("OK", 10)))
    assert sum("(Postponed)" in n for n in names) == 1


def test_a_date_tbd_games_link_reads_date_tbd():
    tbd = _home("TBD", 6, date_tbd=True, date_time=None, local_time=None)
    html = _page(tbd, _home("OK", 10))
    names = _links(html)
    assert any(", date TBD" in n for n in names), names
    assert not any("on Date TBD" in n for n in names)


def test_the_hero_link_reads_date_tbd_when_the_only_home_game_has_no_date():
    tbd = _home("TBD", 6, date_tbd=True, date_time=None, local_time=None)
    html = unescape(_page(tbd))
    assert "Buy tickets for Montreal Victoire vs Toronto Sceptres, date TBD, from " in html
    assert "on Date TBD" not in html


def test_control_a_link_without_status_is_caught():
    """Sabotage: drop the status from the link name; the check fails."""
    names = [n.replace(" (Cancelled)", "") for n in _links(_page(_away("CX", 6, status="cancelled")))]
    assert sum("(Cancelled)" in n for n in names) == 0
