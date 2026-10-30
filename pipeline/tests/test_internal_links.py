"""Internal links: the home page links every team, a team page links its
league's other teams and the week-ahead page, and the "this week" strip says
only what the build fetched."""

from __future__ import annotations

import re
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest

from wsc_pipeline import build as build_module
from wsc_pipeline import config
from wsc_pipeline.site import SCHEDULE_PATH

from .fixture_site import BASE_URL, build_fixture_site

HREF = re.compile(r'<a (?:class="[^"]*" )?href="(/[^"#?]*)"')
TEAM_PATHS = {f"/{lg.slug}/{t.slug}/" for lg in config.LEAGUES for t in lg.teams}
LEAGUE_PATHS = {f"/{lg.slug}/" for lg in config.LEAGUES}


@pytest.fixture(scope="module")
def dist(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("links") / "dist"
    # 2026-09-18 08:30 UTC: the week the fixture's games fall in.
    build_fixture_site(out, now=datetime(2026, 9, 18, 8, 30, tzinfo=UTC))
    return out


def _pages(root: Path) -> dict[str, str]:
    out = {}
    for page in root.rglob("index.html"):
        rel = page.parent.relative_to(root).as_posix()
        if rel.startswith("_"):
            continue
        out["/" if rel == "." else f"/{rel}/"] = page.read_text()
    return out


def _inbound(pages: dict[str, str]) -> Counter[str]:
    """Distinct pages linking to each page (a page's links to itself and
    repeats on one page count once)."""
    counts: Counter[str] = Counter()
    for source, html in pages.items():
        for target in {m for m in HREF.findall(html)} - {source}:
            counts[target] += 1
    return counts


def _strip(html: str, section_class: str) -> str:
    stripped = re.sub(rf'<section class="{section_class}".*?</section>\n', "", html, flags=re.S)
    assert stripped != html, f"sabotage target not found: {section_class}"
    return stripped


# ---------------------------------------------------------------------------
# Reach
# ---------------------------------------------------------------------------


def test_the_home_page_links_every_team(dist: Path):
    home = _pages(dist)["/"]
    linked = set(HREF.findall(home))
    assert linked >= TEAM_PATHS
    assert len(TEAM_PATHS) == 67
    assert '<h3 id="teams-wnba">WNBA teams</h3>' in home


def test_every_team_page_has_many_ways_in(dist: Path):
    inbound = _inbound(_pages(dist))
    for path in TEAM_PATHS:
        # home, its league page, and every other team in its league.
        league = next(lg for lg in config.LEAGUES if path.startswith(f"/{lg.slug}/"))
        assert inbound[path] >= 2 + len(league.teams) - 1, path
        assert inbound[path] >= 7, path  # the smallest league (AUSL, 6 teams) still gives 7


def test_the_week_ahead_page_is_linked_from_every_team_and_league_page(dist: Path):
    pages = _pages(dist)
    for path in TEAM_PATHS | LEAGUE_PATHS | {"/"}:
        assert SCHEDULE_PATH in HREF.findall(pages[path]), path
    assert _inbound(pages)[SCHEDULE_PATH] >= 1 + len(LEAGUE_PATHS) + len(TEAM_PATHS)


def test_every_internal_link_resolves_to_a_built_page(dist: Path):
    pages = _pages(dist)
    for source, html in pages.items():
        for target in set(HREF.findall(html)):
            assert target in pages or (dist / target.lstrip("/")).exists(), (source, target)


def test_a_team_page_lists_its_leagues_other_teams_not_itself_or_other_leagues(dist: Path):
    html = _pages(dist)["/wnba/las-vegas-aces/"]
    block = html[html.index('<section class="more-teams"') :]
    block = block[: block.index("</section>")]
    assert "More WNBA team schedules" in block
    roster = block[block.index('<ul class="team-roster">') : block.index("</ul>")]
    hrefs = set(HREF.findall(roster))
    assert hrefs == {f"/wnba/{t.slug}/" for t in config.LEAGUES[0].teams} - {"/wnba/las-vegas-aces/"}
    assert len(hrefs) == 14
    # ...and leads back up to the league hub, in words, not only the breadcrumb.
    assert set(HREF.findall(block)) - hrefs == {"/wnba/"}
    assert "The full WNBA schedule, every team in one calendar</a>" in block


def test_every_team_page_links_its_league_hub_from_the_lede_and_the_team_list(dist: Path):
    pages = _pages(dist)
    for path in TEAM_PATHS:
        league = path.split("/")[1]
        html = pages[path]
        lede = html[html.index('<p class="lede">') :]
        lede = lede[: lede.index("</p>")]
        assert f'href="/{league}/"' in lede, path
        more = html[html.index('<section class="more-teams"') :]
        assert f'<p class="league-link"><a href="/{league}/">' in more[: more.index("</section>")], path


# ---------------------------------------------------------------------------
# The "this week" strip
# ---------------------------------------------------------------------------


def _strip_of(html: str) -> str:
    block = html[html.index('<section class="this-week"') :]
    return block[: block.index("</section>")]


def test_the_strip_lists_this_teams_games_in_the_schedule_window(dist: Path):
    strip = _strip_of(_pages(dist)["/wnba/las-vegas-aces/"])
    assert "Las Vegas Aces games listed from Friday, September 18 through Thursday, September 24:" in strip
    assert "Las Vegas Aces vs Seattle Storm" in strip  # Sep 19
    assert "Phoenix Mercury vs Las Vegas Aces" in strip or "Las Vegas Aces at Phoenix Mercury" in strip  # Sep 21
    assert "Sep 24, 2026 (time TBA)" in strip
    assert "Sep 17" not in strip  # before the window
    assert "Sep 25" not in strip and "Sep 26" not in strip  # after it
    assert "Date TBD" not in strip  # a game with no date is on no day
    assert f'<a href="{SCHEDULE_PATH}">' in strip


def test_a_fetched_team_with_no_game_in_the_window_says_exactly_that(dist: Path):
    strip = _strip_of(_pages(dist)["/nwsl/portland-thorns/"])  # its one game is Sep 26
    assert "No Portland Thorns game is listed from Friday, September 18 through Thursday, September 24." in strip
    assert "<li>" not in strip


def test_a_team_with_no_games_at_all_gets_the_same_honest_sentence(dist: Path):
    strip = _strip_of(_pages(dist)["/ausl/chicago-bandits/"])
    assert "No Chicago Bandits game is listed from" in strip


def test_a_build_that_fetched_nothing_makes_no_claim_about_the_week(tmp_path: Path):
    out = tmp_path / "dist"
    build_module.build(out_dir=out, base_url=BASE_URL, api_key=None, affiliate_id=None)
    strip = _strip_of(_pages(out)["/wnba/las-vegas-aces/"])
    assert "No Las Vegas Aces game is listed" not in strip and "<li>" not in strip
    assert f'<a href="{SCHEDULE_PATH}">The week ahead in every league, day by day</a>' in strip


# ---------------------------------------------------------------------------
# Controls: each sabotage is asserted to have applied
# ---------------------------------------------------------------------------


def _sabotaged(dist: Path, tmp_path: Path, page: str, section_class: str) -> dict[str, str]:
    root = tmp_path / "dist"
    shutil.copytree(dist, root)
    pages = _pages(root)
    pages[page] = _strip(pages[page], section_class)
    return pages


def test_control_without_the_sibling_blocks_team_pages_fall_back_to_two_links_in(dist: Path, tmp_path: Path):
    pages = _pages(dist)
    for path in TEAM_PATHS:
        pages[path] = _strip(pages[path], "more-teams")
    inbound = _inbound(pages)
    assert all(inbound[path] <= 2 for path in TEAM_PATHS)  # home + league page
    assert not all(inbound[path] >= 7 for path in TEAM_PATHS)


def test_control_without_the_home_teams_section_the_home_page_links_no_team(dist: Path, tmp_path: Path):
    pages = _sabotaged(dist, tmp_path, "/", "all-teams")
    assert not set(HREF.findall(pages["/"])) >= TEAM_PATHS
    assert not set(HREF.findall(pages["/"])) & TEAM_PATHS


def test_control_without_the_strip_a_team_page_does_not_link_the_week_ahead_page(dist: Path, tmp_path: Path):
    pages = _sabotaged(dist, tmp_path, "/wnba/las-vegas-aces/", "this-week")
    assert SCHEDULE_PATH not in HREF.findall(pages["/wnba/las-vegas-aces/"])
