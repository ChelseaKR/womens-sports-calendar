"""Titles and descriptions in the shape Search Console shows fans typing
(DECISIONS 0037): "<team> schedule 2027" for an empty WNBA page, a title that
names only what the page has, and a description of 120 to 155 characters.

The claims checked here are the ones a search result can make falsely:
"home game(s)" without a listed home game, "tickets" or "ticket links"
without a listed game, and "official ticket page" without the page's own
"Get tickets" link. Each control breaks one rule and asserts both that the
sabotage applied and that the check catches it."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from wsc_pipeline import build as build_module
from wsc_pipeline import config, site
from wsc_pipeline.official_tickets import OFFICIAL_SECTION_CLASS
from wsc_pipeline.site_data import team_data

from .fixture_site import BASE_URL, build_fixture_site
from .test_titles_descriptions import _away_games, _game, _head, _home_games

TITLE_MAX = 60
DESCRIPTION_MIN = 120
DESCRIPTION_MAX = 155
ALL_TEAMS = [(lg, t) for lg in config.LEAGUES for t in lg.teams]
OFF_SEASON = "2026-11-06T08:25:00+00:00"  # after the WNBA finals: empty WNBA pages await 2027

# The negations an empty or away-only description may use; anything else
# with "home" in it is a claim.
HOME_NEGATIONS = ("No home game is listed yet", "No home game is listed", "so home games may not show up here")


def _odd_suffix(league, team):
    # Ticketmaster's own misspelling, seen on the Ohio State page 2026-11-06.
    return [
        _game(
            league,
            team,
            "S1",
            f"{team.name} vs Mercyhurst Lakers Womans Basketball",
            date_time="2026-11-20T01:00:00Z",
            local_date="2026-11-19",
        )
    ]


def _short_home(league, team):
    return [
        _game(
            league,
            team,
            "S2",
            f"{team.name} vs Utah State Aggies",
            date_time="2026-11-20T01:00:00Z",
            local_date="2026-11-19",
        )
    ]


SCENARIOS: dict[str, tuple[Callable[[Any, Any], list[Any]], dict[str, Any]]] = {
    "home_long": (_home_games, {}),
    "home_short": (_short_home, {}),
    "home_odd_suffix": (_odd_suffix, {}),
    "away_only": (_away_games, {}),
    "none_fetched": (lambda lg, t: [], {}),
    "none_off_season": (lambda lg, t: [], {"fetched_at": OFF_SEASON}),
    "not_fetched": (lambda lg, t: [], {"fetched": False}),
}


def _render(league, team, scenario: str) -> tuple[str, str, str, dict[str, Any]]:
    games_for, extra = SCENARIOS[scenario]
    fetched = extra.get("fetched", True)
    payload = {**team_data(team, league, games_for(league, team), fetched=fetched), "fetched_at": None}
    payload.update({k: v for k, v in extra.items() if k != "fetched"})
    html = site.render_team(team=payload, base_url=BASE_URL)
    return (*_head(html), html, payload)


def false_claims(title: str, description: str, html: str, payload: dict[str, Any]) -> list[str]:
    """Every claim in the title or description the page does not back."""
    problems = []
    fetched = payload.get("fetched", True)
    home_listed = bool(fetched and payload.get("next_home_event_id"))
    listed = bool(payload["games"])
    if not home_listed:
        if re.search(r"home game", title, re.I):
            problems.append(f"title claims a home game: {title}")
        rest = description
        for negation in HOME_NEGATIONS:
            rest = rest.replace(negation, "")
        if re.search(r"\bhome\b", rest, re.I):
            problems.append(f"description claims a home game: {description}")
    if not listed:
        # The seller's own name ("SI Tickets") is not a claim.
        text = re.sub(r"main ticket seller is [^,.]+", "", title + " " + description)
        if re.search(r"\btickets\b|ticket links", text, re.I):
            problems.append(f"tickets claimed with no game listed: {title} / {description}")
        if re.search(r"\b20\d\d\b", title) and "has not listed" not in description:
            problems.append(f"a season named with no game and no 'not listed yet': {title}")
    if "official ticket page" in title and f'class="{OFFICIAL_SECTION_CLASS}"' not in html:
        problems.append(f"title names an official ticket page the page does not show: {title}")
    return problems


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_every_team_title_and_description_fit_and_claim_only_what_the_page_has(scenario: str):
    for league, team in ALL_TEAMS:
        title, description, html, payload = _render(league, team, scenario)
        assert len(title) <= TITLE_MAX, title
        assert DESCRIPTION_MIN <= len(description) <= DESCRIPTION_MAX, (len(description), description)
        assert false_claims(title, description, html, payload) == [], (league.slug, team.slug)


# Policy pages are not search targets; their one-line summaries stay short.
POLICY_PAGES = {"accessibility", "privacy", "terms"}


@pytest.mark.parametrize("fetched", [True, False])
def test_every_indexed_schedule_page_of_a_build_has_a_full_description(tmp_path: Path, fetched: bool):
    out = tmp_path / "dist"
    if fetched:
        build_fixture_site(out, now=datetime(2026, 9, 18, 8, 30, tzinfo=UTC))
    else:
        build_module.build(out_dir=out, base_url=BASE_URL, api_key=None, affiliate_id=None)
    checked = 0
    for page in sorted(out.rglob("index.html")):
        html = page.read_text()
        if page.parent.name.startswith("_") or page.parent.name in POLICY_PAGES or "noindex" in html:
            continue
        title, description = _head(html)
        assert len(title) <= TITLE_MAX, (page, title)
        assert DESCRIPTION_MIN <= len(description) <= DESCRIPTION_MAX, (page, len(description), description)
        checked += 1
    assert checked > 10


def test_an_empty_off_season_wnba_page_reads_as_typed():
    """'phoenix mercury schedule 2027' (18 impressions) outnumbered 'phoenix
    mercury 2027 schedule' (7), 2026-10-09 to 11-06."""
    wnba = config.league_by_slug("wnba")
    mercury = next(t for t in wnba.teams if t.slug == "phoenix-mercury")
    title, description, _, _ = _render(wnba, mercury, "none_off_season")
    assert title.lower().startswith("phoenix mercury schedule 2027")
    assert description.startswith("Phoenix Mercury schedule 2027. Ticketmaster has not listed the 2027 games yet")


def test_an_empty_page_names_the_official_ticket_page_only_when_it_has_one():
    named = unnamed = 0
    for league, team in ALL_TEAMS:
        title, _, html, _ = _render(league, team, "none_fetched")
        shows = f'class="{OFFICIAL_SECTION_CLASS}"' in html
        if "official ticket page" in title:
            named += 1
            assert shows, title
        elif shows:
            unnamed += 1  # a page with the link whose name was too long to fit it
    big_ten = config.league_by_slug("ncaaw-big-ten")
    rutgers = next(t for t in big_ten.teams if t.slug == "rutgers-scarlet-knights-womens-basketball")
    title, _, html, _ = _render(big_ten, rutgers, "none_fetched")
    assert f'class="{OFFICIAL_SECTION_CLASS}"' not in html  # no verified official page
    assert "official ticket page" not in title
    assert title == "Rutgers women's basketball schedule: add it to your calendar"
    assert named > 20


def test_ticketmaster_suffix_spellings_are_all_dropped_from_the_opponent():
    for raw in (
        "Mercyhurst Lakers Womans Basketball",
        "South Florida Bulls Women's Basketball",
        "Rutgers Scarlet Knights Womens Basketball",
        "Rutgers Scarlet Knights Women’s Basketball",
    ):
        assert not re.search(r"basketball", site._opponent_label("ncaaw-big-ten", raw), re.I), raw


# ---------------------------------------------------------------------------
# Controls: each sabotage is asserted to have applied, then to be caught
# ---------------------------------------------------------------------------


def test_control_a_forced_home_game_claim_is_caught(monkeypatch: pytest.MonkeyPatch):
    nwsl = config.league_by_slug("nwsl")
    team = nwsl.teams[0]
    real = site._team_title

    def lying(*args: Any, **kw: Any) -> str:
        kw["home_listed"] = True
        return real(*args, **kw)

    monkeypatch.setattr(site, "_team_title", lying)
    title, description, html, payload = _render(nwsl, team, "away_only")
    assert "home game" in title  # the sabotage applied
    assert payload["next_home_event_id"] is None
    assert any("title claims a home game" in p for p in false_claims(title, description, html, payload))


def test_control_a_title_naming_a_link_the_page_lost_is_caught(monkeypatch: pytest.MonkeyPatch):
    """If the "Get tickets" section stopped rendering while the title still
    named it, the check must see the mismatch."""
    wnba = config.league_by_slug("wnba")
    lynx = next(t for t in wnba.teams if t.slug == "minnesota-lynx")
    monkeypatch.setattr(site, "_official_tickets_block", lambda page, *, subject, owner: "")
    title, description, html, payload = _render(wnba, lynx, "none_fetched")
    assert "official ticket page" in title  # the title still names it
    assert f'class="{OFFICIAL_SECTION_CLASS}"' not in html  # the sabotage applied
    assert any("official ticket page" in p for p in false_claims(title, description, html, payload))


def test_control_the_old_every_home_and_away_wording_is_caught(monkeypatch: pytest.MonkeyPatch):
    nwsl = config.league_by_slug("nwsl")
    team = nwsl.teams[0]
    title, description, html, payload = _render(nwsl, team, "away_only")
    old = description.replace("listed games with dates", "every home and away game with dates")
    assert old != description  # the sabotage applied
    assert any("description claims a home game" in p for p in false_claims(title, old, html, payload))


def test_control_the_floor_fails_with_the_old_opponent_label(monkeypatch: pytest.MonkeyPatch):
    """Without the suffix fix the Ohio State page of 2026-11-06 fell to 115
    characters; the floor check must see that."""
    big_ten = config.league_by_slug("ncaaw-big-ten")
    ohio = next(t for t in big_ten.teams if t.slug == "ohio-state-buckeyes-womens-basketball")
    fixed = _render(big_ten, ohio, "home_odd_suffix")[1]
    monkeypatch.setattr(site, "_opponent_label", lambda league_slug, opponent: opponent)
    broken = _render(big_ten, ohio, "home_odd_suffix")[1]
    assert "Womans Basketball" in broken and "Womans Basketball" not in fixed  # the sabotage applied
    assert DESCRIPTION_MIN <= len(fixed) <= DESCRIPTION_MAX
    assert not DESCRIPTION_MIN <= len(broken) <= DESCRIPTION_MAX, (len(broken), broken)
