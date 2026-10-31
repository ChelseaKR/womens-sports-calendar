"""A league page that lists no game, and a team page that lists no game and
has no verified official ticket page, is noindex and out of the sitemap, and
comes back the day a game is listed. A team page that lists no game but links
its team's official ticket page stays indexable and in the sitemap
(DECISIONS 0020). Every empty page still says plainly that nothing is listed
(absence is never rendered as a value), and a build that fetched nothing
treats no page as empty: not checked is not "no games"."""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from wsc_pipeline import build as build_module
from wsc_pipeline import config, official_tickets, sitemap, validate_seo

from .conftest import make_raw_event
from .fixture_site import BASE_URL, RAW_EVENTS_BY_TEAM, build_fixture_site

LOC_RE = re.compile(r"<loc>([^<]+)</loc>")
NOINDEX = '<meta name="robots" content="noindex">'
CANONICAL = '<link rel="canonical"'
# In the fixture: games on these league and team pages only.
LISTED = {"/wnba/", "/nwsl/", "/pwhl/", "/wnba/las-vegas-aces/", "/wnba/seattle-storm/"}
LISTED |= {"/nwsl/portland-thorns/", "/pwhl/toronto-sceptres/"}
# Empty and kept out: the two empty league pages, and Rutgers, the one team
# with no verified official ticket page (official_tickets.py).
RUTGERS = "/ncaaw-big-ten/rutgers-scarlet-knights-womens-basketball/"
EMPTY = ("/ausl/", "/ncaaw-big-ten/", RUTGERS)
# Empty but indexable: each links its team's official ticket page.
EMPTY_WITH_TICKETS = ("/wnba/chicago-sky/", "/nwsl/angel-city/", "/ausl/chicago-bandits/")
ALL_TEAMS = sum(len(lg.teams) for lg in config.LEAGUES)
# Indexable in the fixture: home, privacy, accessibility, schedule, the 3
# leagues that list a game, and every team page but Rutgers's.
INDEXABLE = 4 + 3 + ALL_TEAMS - 1
OFFICIAL_SECTION = '<section class="official-tickets"'


@pytest.fixture(scope="module")
def dist(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("noindex") / "dist"
    build_fixture_site(out, now=datetime(2026, 9, 18, 8, 30, tzinfo=UTC))
    return out


def _page(root: Path, path: str) -> str:
    return (root / path.strip("/") / "index.html").read_text()


def _listed_paths(root: Path) -> set[str]:
    text = (root / "sitemap.xml").read_text()
    return {loc[len(BASE_URL) :] for loc in LOC_RE.findall(text)}


def _copy(src: Path, dst: Path) -> Path:
    shutil.copytree(src, dst)
    return dst


def test_pages_with_games_are_indexable_and_listed(dist: Path):
    listed = _listed_paths(dist)
    for path in LISTED:
        html = _page(dist, path)
        assert NOINDEX not in html, path
        assert CANONICAL in html, path
        assert path in listed, path


def test_the_fixture_has_the_cases_the_rule_separates():
    """The tests below mean something only if the fixture holds both kinds of
    empty team page."""
    assert official_tickets.team_page("ncaaw-big-ten", RUTGERS.split("/")[2]) is None
    for path in EMPTY_WITH_TICKETS:
        league, team = path.strip("/").split("/")
        assert official_tickets.team_page(league, team) is not None, path
        assert RAW_EVENTS_BY_TEAM.get(team, []) == [], path


def test_pages_with_no_games_are_noindex_and_not_in_the_sitemap(dist: Path):
    listed = _listed_paths(dist)
    for path in EMPTY:
        html = _page(dist, path)
        assert NOINDEX in html, path
        assert CANONICAL not in html, path  # a noindex page is not declared the canonical of anything
        assert path not in listed, path
    # Every page the build wrote under a league is either listed or noindex:
    # nothing is left out of the sitemap while still indexable.
    for page in dist.rglob("index.html"):
        path = "/" + page.parent.relative_to(dist).as_posix() + "/"
        if path.count("/") >= 3 or path in {"/wnba/", "/nwsl/", "/pwhl/", "/ausl/", "/ncaaw-big-ten/"}:
            assert (path in listed) != (NOINDEX in page.read_text()), path
    assert len(listed) == INDEXABLE


def test_an_empty_team_page_with_an_official_ticket_link_is_indexable_and_listed(dist: Path):
    listed = _listed_paths(dist)
    for path in EMPTY_WITH_TICKETS:
        html = _page(dist, path)
        assert NOINDEX not in html, path
        assert CANONICAL in html, path
        assert OFFICIAL_SECTION in html, path
        assert path in listed, path
    # Rutgers lists nothing and has no official link: still kept out.
    assert OFFICIAL_SECTION not in _page(dist, RUTGERS)


def test_an_indexed_empty_page_reads_honestly(dist: Path):
    """Indexed or not, an empty page says no game is listed, and claims none:
    no season, no "home games" or "tickets" in the title, no SportsEvent."""
    for path in EMPTY_WITH_TICKETS:
        html = _page(dist, path)
        assert "No upcoming games found from Ticketmaster right now." in html, path
        assert "No games are listed right now" in html, path  # the meta description
        assert '"SportsEvent"' not in html, path
        assert "next-game--empty" in html, path
        title = re.search(r"<title>([^<]*)</title>", html)
        assert title is not None
        assert title.group(1).endswith(" schedule"), title.group(1)
        assert "Buy tickets" not in html.split('<footer class="site-footer">')[0], path


def test_an_empty_page_still_says_nothing_is_listed(dist: Path):
    html = _page(dist, "/wnba/chicago-sky/")
    assert "No Chicago Sky games are listed by" in html
    assert "No upcoming games found from Ticketmaster right now." in html
    assert "Listings as of" in html  # the read date is still stated
    league = _page(dist, "/ausl/")
    assert "No upcoming games found from Ticketmaster right now." in league
    assert "<h1>AUSL schedule</h1>" in league  # no season is claimed


def test_the_manifest_still_tracks_empty_pages_so_their_return_is_dated(dist: Path):
    state = sitemap.parse_state(json.loads((dist / sitemap.STATE_PATH).read_text()))
    assert state is not None
    for path in EMPTY:
        assert path in state, path


def test_a_noindex_empty_page_passes_the_validator(dist: Path):
    pages, _ = validate_seo.validate_dist(dist)
    assert pages == INDEXABLE


def test_a_page_returns_to_the_sitemap_when_a_game_is_listed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    slug = RUTGERS.strip("/").split("/")[1]
    assert RAW_EVENTS_BY_TEAM.get(slug, []) == []  # the control below means something only if it starts empty
    game = make_raw_event(
        event_id="FX-RU",
        name="Rutgers Scarlet Knights Womens Basketball vs. Iowa Hawkeyes Womens Basketball",
        date_time="2026-11-21T00:00:00Z",
        local_date="2026-11-20",
        local_time="19:00:00",
        venue_name="Jersey Mike's Arena",
        venue_city="Piscataway",
        venue_state="NJ",
        venue_street="83 Rockafeller Rd",
        venue_postal_code="08854",
        venue_country="US",
        timezone="America/New_York",
        url="https://www.ticketmaster.com/event/FX-RU",
    )
    monkeypatch.setitem(RAW_EVENTS_BY_TEAM, slug, [game])
    out = tmp_path / "dist"
    build_fixture_site(out)
    assert NOINDEX not in _page(out, RUTGERS)
    assert RUTGERS in _listed_paths(out)
    assert validate_seo.validate_dist(out)


def test_a_build_that_fetched_nothing_marks_no_page_noindex(tmp_path: Path):
    out = tmp_path / "dist"
    build_module.build(out_dir=out, base_url=BASE_URL, api_key=None, affiliate_id=None)
    listed = _listed_paths(out)
    assert len(listed) == 4 + len(config.LEAGUES) + ALL_TEAMS  # nothing was checked, so nothing is "empty"
    for path in ("/wnba/", "/wnba/chicago-sky/", "/ausl/"):
        assert NOINDEX not in _page(out, path)
        assert path in listed
    assert validate_seo.validate_dist(out)


# ---------------------------------------------------------------------------
# Controls: each sabotage is asserted to have applied, then the validator must fail
# ---------------------------------------------------------------------------


def test_control_an_empty_page_that_is_not_noindex_fails(dist: Path, tmp_path: Path):
    out = _copy(dist, tmp_path / "dist")
    page = out / RUTGERS.strip("/") / "index.html"
    text = page.read_text()
    assert NOINDEX in text
    page.write_text(text.replace(NOINDEX + "\n", "", 1))
    assert NOINDEX not in page.read_text()  # the sabotage applied
    with pytest.raises(validate_seo.SeoError, match="built, not listed"):
        validate_seo.validate_dist(out)


def test_control_a_page_with_games_that_is_noindex_fails(dist: Path, tmp_path: Path):
    out = _copy(dist, tmp_path / "dist")
    page = out / "wnba/las-vegas-aces/index.html"
    text = page.read_text()
    assert NOINDEX not in text
    page.write_text(text.replace('<meta name="description"', NOINDEX + '\n<meta name="description"', 1))
    assert NOINDEX in page.read_text()
    with pytest.raises(validate_seo.SeoError, match="noindex page is listed in the sitemap"):
        validate_seo.validate_dist(out)


def test_control_an_empty_page_listed_in_the_sitemap_fails(dist: Path, tmp_path: Path):
    out = _copy(dist, tmp_path / "dist")
    sm = out / "sitemap.xml"
    text = sm.read_text()
    assert RUTGERS not in text
    sm.write_text(text.replace("</urlset>", f"  <url><loc>{BASE_URL}{RUTGERS}</loc></url>\n</urlset>"))
    assert RUTGERS in sm.read_text()
    with pytest.raises(validate_seo.SeoError, match="disagree"):
        validate_seo.validate_dist(out)


def test_control_the_rule_is_what_drops_the_page(dist: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """With the rule switched off the same build lists and indexes every page,
    so the omissions above are the rule's doing and nothing else's."""
    # site.py and build.py both call site_data.kept_out_of_search, which reads
    # nothing_listed from site_data: one switch turns the rule off everywhere.
    monkeypatch.setattr("wsc_pipeline.site_data.nothing_listed", lambda payload: False)
    out = tmp_path / "dist"
    build_fixture_site(out)
    assert RUTGERS in _listed_paths(out)
    assert NOINDEX not in _page(out, RUTGERS)
    assert "/ausl/" in _listed_paths(out)
    assert len(_listed_paths(out)) == 4 + len(config.LEAGUES) + ALL_TEAMS


def test_control_an_empty_team_page_with_a_ticket_link_made_noindex_fails(dist: Path, tmp_path: Path):
    """The old rule (every empty page out) applied to a page with an official
    ticket link, in both the page and the sitemap so they agree: the
    validator still refuses it."""
    out = _copy(dist, tmp_path / "dist")
    page = out / "wnba/chicago-sky/index.html"
    text = page.read_text()
    assert NOINDEX not in text
    page.write_text(text.replace('<meta name="description"', NOINDEX + '\n<meta name="description"', 1))
    assert NOINDEX in page.read_text()
    sm = out / "sitemap.xml"
    entry = re.search(rf"<url><loc>{re.escape(BASE_URL)}/wnba/chicago-sky/</loc>.*?</url>\n?", sm.read_text())
    assert entry is not None
    sm.write_text(sm.read_text().replace(entry.group(0), ""))
    assert "/wnba/chicago-sky/" not in sm.read_text()  # both halves of the sabotage applied
    with pytest.raises(validate_seo.SeoError, match="links the team's official ticket page"):
        validate_seo.validate_dist(out)


def test_control_an_empty_league_page_indexed_and_listed_fails(dist: Path, tmp_path: Path):
    """An empty league page put back in the index, consistently in the page
    and the sitemap, fails: only a team page's official ticket link earns an
    empty page its place (the decision covers team pages)."""
    out = _copy(dist, tmp_path / "dist")
    page = out / "ausl/index.html"
    text = page.read_text()
    assert NOINDEX in text
    assert OFFICIAL_SECTION in text  # the league has an official link; it does not count
    canonical = f'<link rel="canonical" href="{BASE_URL}/ausl/">'
    page.write_text(text.replace(NOINDEX, canonical, 1))
    assert NOINDEX not in page.read_text()
    sm = out / "sitemap.xml"
    sm.write_text(sm.read_text().replace("</urlset>", f"  <url><loc>{BASE_URL}/ausl/</loc></url>\n</urlset>"))
    assert "/ausl/" in _listed_paths(out)
    with pytest.raises(validate_seo.SeoError, match="must be noindex"):
        validate_seo.validate_dist(out)


def test_control_rutgers_given_a_ticket_link_is_indexed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The ticket link is what keeps an empty team page indexed: give Rutgers
    one and its page joins the sitemap; the validator agrees."""
    slug = RUTGERS.strip("/").split("/")[1]
    fake = official_tickets.OfficialTicketPage("https://example.org/tickets", "test only")
    monkeypatch.setitem(official_tickets.OFFICIAL_TEAM_TICKETS, ("ncaaw-big-ten", slug), fake)
    assert official_tickets.team_page("ncaaw-big-ten", slug) is fake  # the sabotage applied
    out = tmp_path / "dist"
    build_fixture_site(out)
    assert RUTGERS in _listed_paths(out)
    assert NOINDEX not in _page(out, RUTGERS)
    assert validate_seo.validate_dist(out)
