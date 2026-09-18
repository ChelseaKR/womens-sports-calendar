from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from wsc_pipeline import build as build_module
from wsc_pipeline.config import LEAGUES
from wsc_pipeline.ticketmaster import TicketmasterFetchError

from .conftest import make_raw_event


def test_degraded_build_with_no_api_key_succeeds_and_says_so(tmp_path: Path):
    """'with no key, the build emits calendars without prices and says so,
    never errors into an empty site' -- verified end to end."""
    out_dir = tmp_path / "dist"
    coverage = build_module.build(
        out_dir=out_dir, base_url="https://calendar.chelseakr.com", api_key=None, affiliate_id=None
    )
    assert coverage.api_key_present is False
    assert (out_dir / "index.html").exists()
    index_html = (out_dir / "index.html").read_text()
    assert "<title>Next Home Game: " in index_html

    # Nothing was fetched, so no page may claim there are no games: the
    # index never says "0 upcoming games" and league/team pages say "not
    # fetched" instead of "no games listed".
    assert "schedule not fetched" in index_html
    assert "0 upcoming games" not in index_html
    for lg in LEAGUES:
        league_ics = out_dir / "ics" / f"{lg.slug}.ics"
        assert league_ics.exists()
        league_html = (out_dir / lg.slug / "index.html").read_text()
        assert "did not fetch a schedule from Ticketmaster" in league_html
        assert "No upcoming games found" not in league_html
        for team in lg.teams:
            assert (out_dir / "ics" / lg.slug / f"{team.slug}.ics").exists()
            team_html = (out_dir / lg.slug / team.slug / "index.html").read_text()
            assert "did not fetch a schedule from Ticketmaster" in team_html
            assert "are listed by\nTicketmaster right now" not in team_html
            assert "No upcoming games found" not in team_html

    coverage_txt = (out_dir / "COVERAGE.txt").read_text()
    assert "TICKETMASTER_API_KEY not configured" in coverage_txt

    site_json = json.loads((out_dir / "data" / "site.json").read_text())
    assert site_json["api_key_present"] is False
    assert all(lg["games_count"] is None for lg in site_json["leagues"])
    team_json = json.loads((out_dir / "data" / LEAGUES[0].slug / f"{LEAGUES[0].teams[0].slug}.json").read_text())
    assert team_json["fetched"] is False
    assert len(site_json["leagues_examined_not_included"]) == 4


def test_degraded_build_emits_valid_ics_with_zero_events(tmp_path: Path):
    from icalendar import Calendar

    out_dir = tmp_path / "dist"
    build_module.build(out_dir=out_dir, base_url="https://calendar.chelseakr.com", api_key=None, affiliate_id=None)
    raw = (out_dir / "ics" / "wnba.ics").read_bytes()
    cal = Calendar.from_ical(raw)  # raises if malformed
    assert cal.walk("VEVENT") == []
    # The empty calendar says why it is empty, rather than reading as "no games".
    assert "Not fetched" in str(cal.get("x-wr-caldesc"))


def test_failed_fetch_does_not_clobber_a_previous_good_build(tmp_path: Path, monkeypatch):
    """A failed fetch fails the build; a stale build is never published as
    current -- verified as: an existing good --out survives untouched when
    the next build's fetch fails."""
    out_dir = tmp_path / "dist"
    build_module.build(out_dir=out_dir, base_url="https://calendar.chelseakr.com", api_key=None, affiliate_id=None)
    good_index = (out_dir / "index.html").read_text()

    def boom(api_key: str):
        raise TicketmasterFetchError("simulated Discovery API outage")

    monkeypatch.setattr(build_module, "fetch_all_games", boom)

    with pytest.raises(TicketmasterFetchError):
        build_module.build(
            out_dir=out_dir, base_url="https://calendar.chelseakr.com", api_key="fake-key", affiliate_id=None
        )

    # out_dir must be exactly what the last successful build wrote.
    assert (out_dir / "index.html").read_text() == good_index
    # And the failed attempt must not have left a half-written tmp dir behind.
    assert not (out_dir.with_name(out_dir.name + ".tmp")).exists()


def test_main_returns_nonzero_on_fetch_failure(tmp_path: Path, monkeypatch, capsys):
    def boom(api_key: str):
        raise TicketmasterFetchError("simulated outage")

    monkeypatch.setattr(build_module, "fetch_all_games", boom)
    monkeypatch.setenv("TICKETMASTER_API_KEY", "fake-key")
    out_dir = tmp_path / "dist"
    rc = build_module.main(["--out", str(out_dir), "--base-url", "https://calendar.chelseakr.com"])
    assert rc != 0
    captured = capsys.readouterr()
    assert "BUILD FAILED" in captured.err


def test_require_api_key_refuses_a_degraded_build(tmp_path: Path, monkeypatch, capsys):
    """The deploy workflow passes --require-api-key: with no key it must
    fail and write nothing, so a missing secret can never publish empty
    calendars over every subscriber's real ones."""
    monkeypatch.delenv("TICKETMASTER_API_KEY", raising=False)
    out_dir = tmp_path / "dist"
    rc = build_module.main(["--out", str(out_dir), "--base-url", "https://nexthomegame.com", "--require-api-key"])
    assert rc == 1
    assert not out_dir.exists()
    assert "BUILD FAILED" in capsys.readouterr().err


def test_zero_games_across_every_team_is_a_failed_fetch(monkeypatch):
    """Every tracked team returning nothing at once is a broken query or
    API change, not an off-season; it must fail rather than publish empty
    calendars as fact."""
    fake_client = _FakeDiscoveryClient({})
    monkeypatch.setattr(build_module, "DiscoveryClient", lambda api_key: fake_client)
    with pytest.raises(TicketmasterFetchError, match="0 games found"):
        build_module.fetch_all_games("fake-key")


def test_possibly_incomplete_team_is_said_on_its_team_and_league_pages(tmp_path: Path, monkeypatch):
    league, team = LEAGUES[0], LEAGUES[0].teams[0]
    raw = make_raw_event(event_id="EVT-1", name=f"{team.name} vs Visiting Team")
    from wsc_pipeline.normalize import normalize_event

    game = normalize_event(raw, league_slug=league.slug, tracked_team_slug=team.slug, tracked_team_name=team.name)
    truncated = {lg.slug: set() for lg in LEAGUES}
    truncated[league.slug] = {team.slug}
    mismatched = {lg.slug: set() for lg in LEAGUES}
    monkeypatch.setattr(build_module, "fetch_all_games", lambda api_key: ([game], truncated, mismatched, 1, 100))

    out_dir = tmp_path / "dist"
    build_module.build(out_dir=out_dir, base_url="https://nexthomegame.com", api_key="fake-key", affiliate_id=None)

    team_html = (out_dir / league.slug / team.slug / "index.html").read_text()
    league_html = (out_dir / league.slug / "index.html").read_text()
    other_team_html = (out_dir / league.slug / league.teams[1].slug / "index.html").read_text()
    assert "may be missing later" in team_html
    assert "may be missing later" in league_html
    assert "may be missing later" not in other_team_html
    team_json = json.loads((out_dir / "data" / league.slug / f"{team.slug}.json").read_text())
    assert team_json["possibly_incomplete"] is True and team_json["fetched"] is True


def test_main_returns_zero_in_degraded_mode(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TICKETMASTER_API_KEY", raising=False)
    out_dir = tmp_path / "dist"
    rc = build_module.main(["--out", str(out_dir), "--base-url", "https://calendar.chelseakr.com"])
    assert rc == 0
    assert (out_dir / "index.html").exists()


def _png_size(path: Path) -> tuple[int, int]:
    """Width and height read straight from the PNG IHDR chunk -- no
    decoder dependency, and it proves the file really is a PNG at the
    size the HTML's og:image:width/height meta tags promise."""
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def test_favicon_and_social_card_assets_are_copied_into_the_build(tmp_path: Path):
    """The build must not just link to these files (site.py's meta/link
    tags) -- the bytes have to actually land in --out, or every og:image
    and favicon promise 404s for a real visitor."""
    out_dir = tmp_path / "dist"
    build_module.build(out_dir=out_dir, base_url="https://calendar.chelseakr.com", api_key=None, affiliate_id=None)

    assert (out_dir / "favicon.svg").read_text(encoding="utf-8").startswith("<svg")
    for name in (
        "favicon-32.png",
        "apple-touch-icon.png",
        "og-image.png",
        "og-image-wnba.png",
        "og-image-nwsl.png",
        "og-image-pwhl.png",
    ):
        assert (out_dir / name).is_file(), name

    # og:image:width/height in site.py both claim 1200x630 -- verify the
    # real files, not just the meta tags that promise them.
    for name in ("og-image.png", "og-image-wnba.png", "og-image-nwsl.png", "og-image-pwhl.png"):
        assert _png_size(out_dir / name) == (1200, 630), name


def test_build_fails_loudly_if_a_static_asset_is_missing(tmp_path: Path, monkeypatch):
    """A missing committed asset must fail the build, not silently ship a
    page whose og:image or favicon 404s."""
    monkeypatch.setattr(build_module, "ASSETS_DIR", tmp_path / "no-such-assets-dir")
    out_dir = tmp_path / "dist"
    with pytest.raises(FileNotFoundError):
        build_module.build(out_dir=out_dir, base_url="https://calendar.chelseakr.com", api_key=None, affiliate_id=None)


class _FakeDiscoveryClient:
    """Stands in for DiscoveryClient in fetch_all_games() tests: returns a
    per-team canned response instead of hitting the network, so
    fetch_all_games's own filtering logic (not the HTTP layer, already
    covered by test_ticketmaster_client.py) is what's under test."""

    def __init__(self, responses: dict[str, list[dict]]):
        from wsc_pipeline.ticketmaster import CrawlBudget

        self._responses = responses
        self.budget = CrawlBudget()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def search_team_events(self, team_slug: str, team_name: str, country_codes: tuple[str, ...]):
        return self._responses.get(team_slug, []), False


def test_fetch_all_games_drops_keyword_search_false_positives_and_reports_them(monkeypatch):
    """End-to-end regression for the 2026-09-16 live bug: a Discovery API
    response that mixes a real Angel City FC game with the unrelated WHL
    hockey game that actually shipped to production must, after
    fetch_all_games, produce only the real game -- and must surface the
    drop in the mismatched-team map so it's visible in the coverage report,
    not silently absorbed."""
    real_game = make_raw_event(
        event_id="EVT-REAL",
        name="Angel City FC vs Seattle Reign FC",
        venue_name="BMO Stadium",
        venue_city="Los Angeles",
        venue_state="CA",
    )
    hockey_leak = make_raw_event(
        event_id="EVT-HOCKEY",
        name="Everett Silvertips vs Tri-City Americans",
        venue_name="Angel Of The Winds Arena",
        venue_city="Everett",
        venue_state="WA",
    )
    fake_client = _FakeDiscoveryClient({"angel-city": [real_game, hockey_leak]})
    monkeypatch.setattr(build_module, "DiscoveryClient", lambda api_key: fake_client)

    games, _truncated, mismatched, _requests, _bytes = build_module.fetch_all_games("fake-key")

    angel_city_games = [g for g in games if g.tracked_team_slug == "angel-city"]
    assert [g.event_id for g in angel_city_games] == ["EVT-REAL"]
    assert "angel-city" in mismatched["nwsl"]

    # No other team's canned response was populated, so nothing else should
    # have produced a game or a mismatch -- confirms the fake only affected
    # the team under test.
    assert all(g.tracked_team_slug == "angel-city" for g in games)
    assert mismatched["nwsl"] == {"angel-city"}
    assert all(slugs == set() for lg_slug, slugs in mismatched.items() if lg_slug != "nwsl")


def test_head_to_head_game_is_listed_and_counted_once_per_league(tmp_path: Path, monkeypatch):
    """Regression for the live 2026-09-17 duplicate rows (58 WNBA rows for
    29 games): Atlanta Dream vs Connecticut Sun comes back from BOTH teams'
    keyword searches. The league page, league JSON, index count, coverage
    report, and league .ics must each carry it once; each team's own page
    and feed must still carry it."""
    from icalendar import Calendar

    head_to_head = make_raw_event(
        event_id="EVT-H2H",
        name="Atlanta Dream vs Connecticut Sun",
        venue_name="Gateway Center Arena",
        venue_city="College Park",
        venue_state="GA",
        timezone="America/New_York",
    )
    fake_client = _FakeDiscoveryClient({"atlanta-dream": [head_to_head], "connecticut-sun": [head_to_head]})
    monkeypatch.setattr(build_module, "DiscoveryClient", lambda api_key: fake_client)

    out_dir = tmp_path / "dist"
    coverage = build_module.build(
        out_dir=out_dir, base_url="https://nexthomegame.com", api_key="fake-key", affiliate_id=None
    )

    league_json = json.loads((out_dir / "data" / "wnba.json").read_text())
    assert [g["event_id"] for g in league_json["games"]] == ["EVT-H2H"]
    league_html = (out_dir / "wnba" / "index.html").read_text()
    assert league_html.count("Buy tickets for Atlanta Dream vs Connecticut Sun") == 1
    assert "1 upcoming game<" in (out_dir / "index.html").read_text()
    site_json = json.loads((out_dir / "data" / "site.json").read_text())
    assert next(lg for lg in site_json["leagues"] if lg["slug"] == "wnba")["games_count"] == 1
    wnba_cov = next(lc for lc in coverage.leagues if lc.league_slug == "wnba")
    assert wnba_cov.games_total == 1
    assert wnba_cov.teams_with_games == 2  # the game still counts for both teams
    league_cal = Calendar.from_ical((out_dir / "ics" / "wnba.ics").read_bytes())
    assert len(league_cal.walk("VEVENT")) == 1

    for team_slug in ("atlanta-dream", "connecticut-sun"):
        team_json = json.loads((out_dir / "data" / "wnba" / f"{team_slug}.json").read_text())
        assert [g["event_id"] for g in team_json["games"]] == ["EVT-H2H"]
        team_cal = Calendar.from_ical((out_dir / "ics" / "wnba" / f"{team_slug}.ics").read_bytes())
        assert len(team_cal.walk("VEVENT")) == 1


# Visitors cannot open anything in the private repo, so no published file
# may point them at one: no repo doc paths, no GitHub URL. (The .ics UID
# domain is an opaque, frozen id -- see ics.UID_DOMAIN -- and a degraded
# build emits no events, so it does not appear here.)
_PRIVATE_REPO_REFERENCE_RE = re.compile(
    r"(?<![\w-])docs/|DECISIONS|LICENSES-AND-ATTRIBUTION|\w\.md\b|github\.com|ChelseaKR"
)


def test_no_published_file_points_visitors_into_the_private_repo(tmp_path: Path):
    out_dir = tmp_path / "dist"
    build_module.build(out_dir=out_dir, base_url="https://nexthomegame.com", api_key=None, affiliate_id=None)
    checked = 0
    for path in out_dir.rglob("*"):
        if path.suffix not in {".html", ".json", ".txt", ".ics", ".xml", ".css"}:
            continue
        text = path.read_text(encoding="utf-8")
        match = _PRIVATE_REPO_REFERENCE_RE.search(text)
        assert match is None, f"{path.relative_to(out_dir)} contains {match.group(0)!r}"
        checked += 1
    assert checked > 100  # every page, JSON file, and feed, not a handful


def test_league_notes_and_exclusion_reasons_are_self_contained():
    """Checked at the source too, so a newly added league note or
    examined-not-included entry cannot reintroduce a repo reference."""
    from wsc_pipeline.config import LEAGUES_EXAMINED_NOT_INCLUDED

    texts = [lg.schedule_source_note for lg in LEAGUES]
    texts += [item["reason"] for item in LEAGUES_EXAMINED_NOT_INCLUDED]
    texts += [item["name"] for item in LEAGUES_EXAMINED_NOT_INCLUDED]
    for text in texts:
        match = _PRIVATE_REPO_REFERENCE_RE.search(text)
        assert match is None, f"{match.group(0)!r} in: {text[:80]}"


def test_api_user_agent_does_not_name_the_private_repo():
    from wsc_pipeline.ticketmaster import USER_AGENT

    assert "github.com" not in USER_AGENT
    assert "nexthomegame.com" in USER_AGENT


def test_a_branded_404_page_is_built_noindexed_and_kept_out_of_the_sitemap(tmp_path: Path):
    out_dir = tmp_path / "dist"
    build_module.build(out_dir=out_dir, base_url="https://nexthomegame.com", api_key=None, affiliate_id=None)
    not_found = (out_dir / "404.html").read_text()
    assert "<title>Page not found | Next Home Game</title>" in not_found
    assert '<meta name="robots" content="noindex">' in not_found
    assert 'rel="canonical"' not in not_found
    for lg in LEAGUES:
        assert f'href="/{lg.slug}/"' in not_found
    assert "404" not in (out_dir / "sitemap.xml").read_text()
    assert "noindex" not in (out_dir / "index.html").read_text()
