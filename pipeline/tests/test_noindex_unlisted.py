"""A league or team page that lists no game is noindex and out of the
sitemap, and comes back the day a game is listed. It still says plainly that
nothing is listed (absence is never rendered as a value), and a build that
fetched nothing treats no page as empty: not checked is not "no games"."""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from wsc_pipeline import build as build_module
from wsc_pipeline import sitemap, validate_seo

from .conftest import make_raw_event
from .fixture_site import BASE_URL, RAW_EVENTS_BY_TEAM, build_fixture_site

LOC_RE = re.compile(r"<loc>([^<]+)</loc>")
NOINDEX = '<meta name="robots" content="noindex">'
CANONICAL = '<link rel="canonical"'
# In the fixture: games on these league and team pages only.
LISTED = {"/wnba/", "/nwsl/", "/pwhl/", "/wnba/las-vegas-aces/", "/wnba/seattle-storm/"}
LISTED |= {"/nwsl/portland-thorns/", "/pwhl/toronto-sceptres/"}
EMPTY = ("/ausl/", "/ncaaw-big-ten/", "/wnba/chicago-sky/", "/nwsl/angel-city/")


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
    assert len(listed) == 4 + len(LISTED)  # home, privacy, accessibility, schedule + the listed ones


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
    assert pages == 4 + len(LISTED)


def test_a_page_returns_to_the_sitemap_when_a_game_is_listed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    sky = RAW_EVENTS_BY_TEAM.get("chicago-sky", [])
    assert sky == []  # the control below means something only if it starts empty
    game = make_raw_event(
        event_id="FX-SKY",
        name="Chicago Sky vs Dallas Wings",
        date_time="2026-09-25T00:00:00Z",
        local_date="2026-09-24",
        local_time="19:00:00",
        venue_name="Wintrust Arena",
        venue_city="Chicago",
        venue_state="IL",
        venue_street="200 E Cermak Rd",
        venue_postal_code="60616",
        venue_country="US",
        timezone="America/Chicago",
        url="https://www.ticketmaster.com/event/FX-SKY",
    )
    monkeypatch.setitem(RAW_EVENTS_BY_TEAM, "chicago-sky", [game])
    out = tmp_path / "dist"
    build_fixture_site(out)
    assert NOINDEX not in _page(out, "/wnba/chicago-sky/")
    assert "/wnba/chicago-sky/" in _listed_paths(out)
    assert validate_seo.validate_dist(out)


def test_a_build_that_fetched_nothing_marks_no_page_noindex(tmp_path: Path):
    out = tmp_path / "dist"
    build_module.build(out_dir=out, base_url=BASE_URL, api_key=None, affiliate_id=None)
    listed = _listed_paths(out)
    assert len(listed) == 4 + 72  # every page: nothing was checked, so nothing is "empty"
    for path in ("/wnba/", "/wnba/chicago-sky/", "/ausl/"):
        assert NOINDEX not in _page(out, path)
        assert path in listed
    assert validate_seo.validate_dist(out)


# ---------------------------------------------------------------------------
# Controls: each sabotage is asserted to have applied, then the validator must fail
# ---------------------------------------------------------------------------


def test_control_an_empty_page_that_is_not_noindex_fails(dist: Path, tmp_path: Path):
    out = _copy(dist, tmp_path / "dist")
    page = out / "wnba/chicago-sky/index.html"
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
    assert "/wnba/chicago-sky/" not in text
    sm.write_text(text.replace("</urlset>", f"  <url><loc>{BASE_URL}/wnba/chicago-sky/</loc></url>\n</urlset>"))
    assert "/wnba/chicago-sky/" in sm.read_text()
    with pytest.raises(validate_seo.SeoError, match="disagree"):
        validate_seo.validate_dist(out)


def test_control_the_rule_is_what_drops_the_page(dist: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """With the rule switched off the same build lists and indexes every page,
    so the omissions above are the rule's doing and nothing else's."""
    monkeypatch.setattr("wsc_pipeline.site_data.nothing_listed", lambda payload: False)
    monkeypatch.setattr("wsc_pipeline.site.nothing_listed", lambda payload: False)
    monkeypatch.setattr(build_module.site_data, "nothing_listed", lambda payload: False)
    out = tmp_path / "dist"
    build_fixture_site(out)
    assert "/wnba/chicago-sky/" in _listed_paths(out)
    assert NOINDEX not in _page(out, "/wnba/chicago-sky/")
    assert len(_listed_paths(out)) == 4 + 72
