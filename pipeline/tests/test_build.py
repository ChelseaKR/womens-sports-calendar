from __future__ import annotations

import json
from pathlib import Path

import pytest

from wsc_pipeline import build as build_module
from wsc_pipeline.config import LEAGUES
from wsc_pipeline.ticketmaster import TicketmasterFetchError


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
    assert len(site_json["leagues_examined_not_included"]) == 4


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
