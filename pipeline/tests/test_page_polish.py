"""The 2026-11-14 page polish, on the built fixture site and rendered pages:
team lists in A-Z order, the lede's "as of" date in the freshness note's
zone, one "Date TBD" per row, a ticket button that keeps its outline in
forced colors, and games tables that stack on a phone with their table
roles kept. The browser half of the phone check (no box scrolls sideways at
320 CSS px) is scripts/a11y_browser_checks.mjs, run by `make a11y`."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from wsc_pipeline import config, site
from wsc_pipeline.site_data import league_data, team_data

from .fixture_site import build_fixture_site


@pytest.fixture(scope="module")
def fixture_dist(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("polish") / "dist"
    build_fixture_site(out)
    return out


def _names(list_html: str) -> list[str]:
    return [site_text(m) for m in re.findall(r"<li><a [^>]*>(.*?)</a></li>", list_html)]


def site_text(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html).replace("&#x27;", "'").replace("&amp;", "&")


def _is_az(names: list[str]) -> bool:
    """A to Z by the name a fan looks for: a college list compares the school
    ("Michigan" before "Michigan State"), not the suffix every entry shares."""
    return names == sorted(names, key=lambda n: n.casefold().removesuffix(" women's basketball").split())


# --- team lists in A-Z order ---------------------------------------------------------------------------------------


def test_control_the_registry_order_is_not_alphabetical():
    # Without this, the A-Z checks below could pass on a registry that
    # happened to be sorted already.
    wnba = config.league_by_slug("wnba")
    assert not _is_az([t.name for t in wnba.teams])


@pytest.mark.parametrize("league", config.LEAGUES, ids=lambda lg: lg.slug)
def test_every_team_list_is_in_a_to_z_order(fixture_dist: Path, league: config.League):
    home = (fixture_dist / "index.html").read_text(encoding="utf-8")
    roster = re.search(rf'<ul class="team-roster" aria-labelledby="teams-{league.slug}">(.*?)</ul>', home, re.S)
    assert roster, f"the home page lists no {league.slug} teams"
    home_names = _names(roster.group(1))

    league_page = (fixture_dist / league.slug / "index.html").read_text(encoding="utf-8")
    league_roster = re.search(r"team schedules</h2>\s*<ul class=\"team-roster\">(.*?)</ul>", league_page, re.S)
    assert league_roster
    league_names = _names(league_roster.group(1))

    first = league.teams[0]
    team_page = (fixture_dist / league.slug / first.slug / "index.html").read_text(encoding="utf-8")
    more = re.search(r'<section class="more-teams".*?<ul class="team-roster">(.*?)</ul>', team_page, re.S)
    assert more
    more_names = _names(more.group(1))

    assert len(home_names) == len(league_names) == len(league.teams)
    assert len(more_names) == len(league.teams) - 1
    for names in (home_names, league_names, more_names):
        assert _is_az(names), names


@pytest.mark.parametrize(
    ("first", "then"),
    [
        ("Michigan women's basketball", "Michigan State women's basketball"),
        ("Texas women's basketball", "Texas A&M women's basketball"),
    ],
)
def test_a_school_comes_before_the_longer_name_that_starts_with_it(fixture_dist: Path, first: str, then: str):
    home = site_text((fixture_dist / "index.html").read_text(encoding="utf-8"))
    assert home.index(f"{first}\n") < home.index(f"{then}\n")


def test_lists_with_no_shared_ending_sort_on_the_whole_name():
    pairs = [("b", "Seattle Storm"), ("a", "Las Vegas Aces"), ("c", "Atlanta Dream")]
    assert [name for _, name in site._alphabetical(pairs)] == ["Atlanta Dream", "Las Vegas Aces", "Seattle Storm"]
    assert site._alphabetical([("x", "Solo Team")]) == [("x", "Solo Team")]


def test_the_page_data_keeps_the_registry_order():
    # Display order only: what the league page is rendered from is unchanged.
    wnba = config.league_by_slug("wnba")
    assert league_data(wnba, [])["teams"] == [t.slug for t in wnba.teams]


# --- the lede's "as of" date ----------------------------------------------------------------------------------------


def _empty_team_page(fetched_at: str) -> str:
    league = config.league_by_slug("wnba")
    team = next(t for t in league.teams if t.slug == "toronto-tempo")
    payload = {**team_data(team, league, []), "fetched_at": fetched_at}
    return site.render_team(team=payload, base_url="https://example.test")


def test_an_evening_build_says_as_of_the_same_day_as_its_freshness_note():
    # 04:19 UTC on Nov 15 is 8:19 PM Pacific on Nov 14; the lede said Nov 15.
    html = _empty_team_page("2026-11-15T04:19:45+00:00")
    assert 'as of <time datetime="2026-11-14">Saturday, November 14, 2026</time>' in html
    assert "Listings as of" in html and "Saturday, Nov. 14, 2026, 8:19 PM PT" in html
    assert "November 15" not in html


def test_the_nightly_build_date_is_unchanged():
    # 08:13 UTC, when pages.yml runs, is the same calendar day in Pacific time.
    html = _empty_team_page("2026-11-05T08:13:00+00:00")
    assert 'as of <time datetime="2026-11-05">Thursday, November 5, 2026</time>' in html


# --- one "Date TBD" per row -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("date_tbd", [True, False])
def test_a_game_not_in_the_feed_says_so_once(date_tbd: bool):
    game = {"in_calendar_feed": False, "date_tbd": date_tbd, "start_local_date": None if date_tbd else "2026-12-01"}
    assert site._feed_note(game) == " (not yet in the calendar feed)"
    assert site._feed_note({**game, "in_calendar_feed": True}) == ""


def test_no_page_says_date_tbd_twice(fixture_dist: Path):
    pages = list(fixture_dist.rglob("*.html"))
    assert any("Date TBD" in p.read_text(encoding="utf-8") for p in pages)  # the fixture has a date-TBD game
    for page in pages:
        assert "(date TBD &mdash;" not in page.read_text(encoding="utf-8"), page


# --- forced colors ----------------------------------------------------------------------------------------------


def _media_block(css: str, query: str) -> str:
    start = css.index(f"@media {query} {{")
    depth, i = 0, start
    for i in range(css.index("{", start), len(css)):
        depth += {"{": 1, "}": -1}.get(css[i], 0)
        if depth == 0:
            break
    return css[start : i + 1]


def test_forced_colors_keeps_the_ticket_button_and_date_chip_outlined():
    block = _media_block(site.STYLE_CSS, "(forced-colors: active)")
    assert re.search(r"a\.next-game-cta[^{]*\{[^}]*border: 2px solid LinkText", block)
    assert re.search(r"\.next-game-date \{[^}]*border: 2px solid CanvasText", block)
    # The "no ticket link" line shares the class but is not a link: no button outline.
    assert ".next-game-cta--unavailable" not in block and re.search(r"(?<![a\w-])\.next-game-cta\b", block) is None


# --- games tables on a phone -----------------------------------------------------------------------------------------


def test_games_tables_stack_below_the_width_they_need():
    block = _media_block(site.STYLE_CSS, "(max-width: 45rem)")
    assert "table.games-table { min-width: 0; }" in block
    assert re.search(r"table\.games-table tr, table\.games-table td \{ display: block; \}", block)
    assert "table.games-table thead" in block and "clip: rect(0 0 0 0)" in block
    # The breakpoint covers every width at which the table would scroll: its
    # min-width plus main's side padding (1.25rem each side) and the wrapper's border.
    min_width = float(re.search(r"table\.games-table \{[^}]*min-width: ([\d.]+)rem", site.STYLE_CSS).group(1))
    assert min_width + 2 * 1.25 < 45


def test_every_games_table_keeps_its_table_roles(fixture_dist: Path):
    tables = 0
    for page in fixture_dist.rglob("*.html"):
        html = page.read_text(encoding="utf-8")
        for table in re.findall(r'<table class="games-table"[^>]*>.*?</table>', html, re.S):
            tables += 1
            assert table.startswith('<table class="games-table" role="table">'), page
            assert table.count("<thead") == table.count('<thead role="rowgroup">') == 1
            assert table.count("<tbody") == table.count('<tbody role="rowgroup">') == 1
            assert table.count("<tr") == table.count('<tr role="row">') >= 2
            assert table.count("<td") == table.count('<td role="cell">')
            assert len(re.findall(r"<th[ >]", table)) == table.count('<th scope="col" role="columnheader">') >= 4
    assert tables > 0
