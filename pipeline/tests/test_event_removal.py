"""Withholding one Ticketmaster event on request (ADR 0006).

The Ticketmaster terms require removing any Event Content within 24 hours of
the owner asking (docs/LICENSES-AND-ATTRIBUTION.md §2). An event named in
config.REMOVED_EVENTS is left out of every page, feed and data file, even
while Ticketmaster still lists it, and the publish guard reports its removal
as accepted instead of refusing the build.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx

from wsc_pipeline import build as build_module
from wsc_pipeline import config
from wsc_pipeline.normalize import normalize_event

from .conftest import REAL_FETCH_PREVIOUS_PUBLISH, make_raw_event
from .fixture_site import build_fixture_site
from .test_affiliate_links import _files
from .test_publish_guard import BASE_URL, FEVER, LIBERTY, _build, _five_fever_games, _liberty_games, _serve

REQUEST = config.EventRemoval("G2", date(2026, 10, 17), "Ticketmaster asked for this event to be removed.")


def _mentions(files: dict[str, bytes], text: str) -> list[str]:
    return [name for name, data in files.items() if text.encode() in data]


def test_the_committed_list_is_well_formed():
    ids = [r.event_id for r in config.REMOVED_EVENTS]
    assert len(ids) == len(set(ids)), "an event id is listed twice"
    for removal in config.REMOVED_EVENTS:
        assert removal.event_id.strip() == removal.event_id and removal.event_id, removal
        assert removal.reason.strip(), removal
        assert isinstance(removal.recorded, date), removal


def test_without_removed_events_drops_exactly_the_named_ids():
    games = [
        normalize_event(make_raw_event(event_id=e), league_slug="wnba", tracked_team_slug=FEVER, tracked_team_name="x")
        for e in ("G1", "G2", "G22", "g2")
    ]
    kept = build_module.without_removed_events([g for g in games if g is not None], (REQUEST,))
    assert [g.event_id for g in kept] == ["G1", "G22", "g2"]
    assert len(build_module.without_removed_events([g for g in games if g is not None], ())) == 4


def test_a_removed_event_is_on_no_page_feed_or_data_file(tmp_path: Path, monkeypatch):
    build_fixture_site(tmp_path / "before")
    before = _files(tmp_path / "before")
    assert len(_mentions(before, "FX-THORNS")) > 3  # the event really is published without the switch

    removal = config.EventRemoval("FX-THORNS", date(2026, 10, 17), "Ticketmaster asked for this event to be removed.")
    monkeypatch.setattr(config, "REMOVED_EVENTS", (removal,))
    build_fixture_site(tmp_path / "after")
    after = _files(tmp_path / "after")
    assert _mentions(after, "FX-THORNS") == []
    assert after.keys() == before.keys()  # the team's page and feed are still there, without the game
    # Every other game is untouched.
    assert len(_mentions(after, "FX-H2H")) == len(_mentions(before, "FX-H2H"))


def test_removing_a_published_event_is_accepted_by_the_publish_guard(tmp_path: Path, monkeypatch):
    """The whole path: build 1 publishes the event; it is then named in
    REMOVED_EVENTS while Ticketmaster still lists it; build 2 publishes
    without it, and the guard reports the removal instead of refusing."""
    live = tmp_path / "live"
    responses = {FEVER: _five_fever_games(), LIBERTY: _liberty_games()}
    _build(live, responses, monkeypatch, None)
    assert b"tm-G2@" in (live / "ics" / "wnba" / f"{FEVER}.ics").read_bytes()
    with httpx.Client(transport=httpx.MockTransport(_serve(live))) as client:
        previous = REAL_FETCH_PREVIOUS_PUBLISH(BASE_URL, client=client)

    monkeypatch.setattr(config, "REMOVED_EVENTS", (REQUEST,))
    coverage = _build(tmp_path / "next", responses, monkeypatch, previous)
    assert coverage.publish_guard is not None and not coverage.publish_guard.refused
    assert [r.split(" ")[:2] for r in coverage.publish_guard.accepted_removals] == [[f"wnba/{FEVER}:", "G2"]]
    files = _files(tmp_path / "next")
    assert _mentions(files, "tm-G2@") == [] and _mentions(files, '"G2"') == []
    assert b"tm-G1@" in files[f"ics/wnba/{FEVER}.ics"]
