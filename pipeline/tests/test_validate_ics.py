"""wsc_pipeline.validate_ics against real build output, including negative
controls that corrupt a built feed and must be caught."""

from __future__ import annotations

from pathlib import Path

import pytest
from icalendar import Calendar

from wsc_pipeline import build as build_module
from wsc_pipeline import validate_ics
from wsc_pipeline.config import LEAGUES
from wsc_pipeline.normalize import normalize_event

from .conftest import make_raw_event

WNBA = LEAGUES[0]
TEAM_A, TEAM_B = WNBA.teams[0], WNBA.teams[1]
N_FEEDS = len(LEAGUES) + sum(len(lg.teams) for lg in LEAGUES)


def _built(tmp_path: Path, monkeypatch, *, with_games: bool) -> Path:
    out_dir = tmp_path / "dist"
    if not with_games:
        build_module.build(out_dir=out_dir, base_url="https://nexthomegame.com", api_key=None, affiliate_id=None)
        return out_dir

    def game(event_id: str, team, **kw):
        raw = make_raw_event(event_id=event_id, name=f"{team.name} vs Visiting Team", **kw)
        return normalize_event(raw, league_slug=WNBA.slug, tracked_team_slug=team.slug, tracked_team_name=team.name)

    games = [
        game("EVT-A1", TEAM_A, price_ranges=[{"type": "standard", "currency": "USD", "min": 20.0, "max": 90.0}]),
        game("EVT-A2", TEAM_A, date_time="2026-06-20T23:00:00Z", local_date="2026-06-20"),
        game("EVT-B1", TEAM_B, date_time="2026-06-22T23:00:00Z", local_date="2026-06-22"),
        # date TBD: shown on the page, correctly absent from the feed
        game("EVT-TBD", TEAM_B, date_time=None, local_date="2026-08-01", local_time=None, date_tbd=True),
    ]
    empty = {lg.slug: set() for lg in LEAGUES}
    monkeypatch.setattr(build_module, "fetch_all_games", lambda api_key: (games, empty, empty, 1, 1))
    build_module.build(out_dir=out_dir, base_url="https://nexthomegame.com", api_key="fake-key", affiliate_id=None)
    return out_dir


def test_degraded_build_feeds_validate(tmp_path: Path, monkeypatch):
    dist = _built(tmp_path, monkeypatch, with_games=False)
    assert validate_ics.validate_dist(dist) == (N_FEEDS, 0)


def test_populated_build_feeds_validate_and_match_their_pages(tmp_path: Path, monkeypatch):
    dist = _built(tmp_path, monkeypatch, with_games=True)
    feeds, league_events = validate_ics.validate_dist(dist)
    assert feeds == N_FEEDS
    assert league_events == 3  # EVT-A1, EVT-A2, EVT-B1; the TBD game is page-only
    assert validate_ics.main([str(dist)]) == 0


def test_missing_team_feed_fails(tmp_path: Path, monkeypatch):
    dist = _built(tmp_path, monkeypatch, with_games=False)
    victim = dist / "ics" / WNBA.slug / f"{TEAM_B.slug}.ics"
    victim.unlink()
    assert not victim.exists()
    with pytest.raises(validate_ics.FeedError, match="missing"):
        validate_ics.validate_dist(dist)
    assert validate_ics.main([str(dist)]) == 1


def test_feed_that_drops_a_game_its_page_lists_fails(tmp_path: Path, monkeypatch):
    dist = _built(tmp_path, monkeypatch, with_games=True)
    feed = dist / "ics" / WNBA.slug / f"{TEAM_A.slug}.ics"
    cal = Calendar.from_ical(feed.read_bytes())
    before = len(cal.walk("VEVENT"))
    cal.subcomponents = [
        c for c in cal.subcomponents if str(c.get("uid", "")) != "tm-EVT-A2@womens-sports-calendar.invalid"
    ]
    feed.write_bytes(cal.to_ical())
    assert len(Calendar.from_ical(feed.read_bytes()).walk("VEVENT")) == before - 1  # the sabotage landed
    with pytest.raises(validate_ics.FeedError, match="disagree"):
        validate_ics.validate_dist(dist)


def test_duplicate_uid_in_a_feed_fails(tmp_path: Path, monkeypatch):
    dist = _built(tmp_path, monkeypatch, with_games=True)
    feed = dist / "ics" / f"{WNBA.slug}.ics"
    cal = Calendar.from_ical(feed.read_bytes())
    first_event = cal.walk("VEVENT")[0]
    cal.add_component(first_event)
    feed.write_bytes(cal.to_ical())
    with pytest.raises(validate_ics.FeedError, match="duplicate UIDs"):
        validate_ics.validate_dist(dist)


def test_unparseable_feed_fails(tmp_path: Path, monkeypatch):
    dist = _built(tmp_path, monkeypatch, with_games=False)
    (dist / "ics" / f"{WNBA.slug}.ics").write_text("<html>not a calendar</html>", encoding="utf-8")
    with pytest.raises(validate_ics.FeedError):
        validate_ics.validate_dist(dist)
