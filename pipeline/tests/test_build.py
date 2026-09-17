from __future__ import annotations

import json
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
    assert "womens-sports-calendar" in index_html

    for lg in LEAGUES:
        league_ics = out_dir / "ics" / f"{lg.slug}.ics"
        assert league_ics.exists()
        league_html = (out_dir / lg.slug / "index.html").read_text()
        assert "No upcoming games found" in league_html
        for team in lg.teams:
            assert (out_dir / "ics" / lg.slug / f"{team.slug}.ics").exists()
            assert (out_dir / lg.slug / team.slug / "index.html").exists()

    coverage_txt = (out_dir / "COVERAGE.txt").read_text()
    assert "TICKETMASTER_API_KEY not configured" in coverage_txt

    site_json = json.loads((out_dir / "data" / "site.json").read_text())
    assert site_json["api_key_present"] is False
    assert len(site_json["leagues_examined_not_included"]) == 5


def test_degraded_build_emits_valid_ics_with_zero_events(tmp_path: Path):
    from icalendar import Calendar

    out_dir = tmp_path / "dist"
    build_module.build(out_dir=out_dir, base_url="https://calendar.chelseakr.com", api_key=None, affiliate_id=None)
    raw = (out_dir / "ics" / "wnba.ics").read_bytes()
    cal = Calendar.from_ical(raw)  # raises if malformed
    assert cal.walk("VEVENT") == []


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
        build_module.build(out_dir=out_dir, base_url="https://calendar.chelseakr.com", api_key="fake-key", affiliate_id=None)

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
    for name in ("favicon-32.png", "apple-touch-icon.png", "og-image.png", "og-image-wnba.png", "og-image-nwsl.png", "og-image-pwhl.png"):
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
