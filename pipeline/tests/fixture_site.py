"""A whole site built from canned Ticketmaster responses: every shape a real
nightly build can meet, run through the real fetch filter, normalizer, page
renderer, feeds, structured data and sitemap.

CI has no Ticketmaster key, so `make verify`'s own build is always the
degraded, no-games one: its pages carry no events, no next-game hero and no
fetch time. A check that only ever sees that build cannot fail on any of
them -- the 2026-09-18 nightly deploy failed validate-html on a fetch time
that no CI build had ever printed. scripts/build_fixture_site.py writes this
site to dist-fixture/ so `make validate-fixture-site` runs the same HTML,
feed and structured-data validators on populated pages, and the tests below
reuse it.

Dates are fixed in 2026-09 so nothing here depends on today's date.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from wsc_pipeline import build as build_module
from wsc_pipeline import sitemap
from wsc_pipeline.ticketmaster import CrawlBudget

from .conftest import make_raw_event

BASE_URL = "https://nexthomegame.com"

_ACES_ARENA = {
    "venue_name": "Michelob Ultra Arena",
    "venue_city": "Las Vegas",
    "venue_state": "NV",
    "venue_street": "3950 S Las Vegas Blvd",
    "venue_postal_code": "89119",
    "venue_country": "US",
    "timezone": "America/Los_Angeles",
}
_STORM_ARENA = {
    "venue_name": "Climate Pledge Arena",
    "venue_city": "Seattle",
    "venue_state": "WA",
    "venue_street": "334 1st Ave N",
    "venue_postal_code": "98109",
    "venue_country": "US",
    "timezone": "America/Los_Angeles",
}

# The Aces/Storm game comes back from both teams' searches, as it does live.
_HEAD_TO_HEAD = make_raw_event(
    event_id="FX-H2H",
    name="Las Vegas Aces vs Seattle Storm",
    date_time="2026-09-20T01:00:00Z",
    local_date="2026-09-19",
    local_time="18:00:00",
    url="https://www.ticketmaster.com/event/FX-H2H",
    **_ACES_ARENA,
)

RAW_EVENTS_BY_TEAM: dict[str, list[dict[str, Any]]] = {
    "las-vegas-aces": [
        # An away game first: the "next home game" hero must skip it.
        make_raw_event(
            event_id="FX-AWAY",
            name="Seattle Storm vs Las Vegas Aces",
            date_time="2026-09-18T02:00:00Z",
            local_date="2026-09-17",
            local_time="19:00:00",
            url="https://www.ticketmaster.com/event/FX-AWAY",
            **_STORM_ARENA,
        ),
        # A cancelled home game: marked cancelled on the page and in the
        # structured data, and never the "next home game".
        make_raw_event(
            event_id="FX-CANCELLED",
            name="Las Vegas Aces vs Los Angeles Sparks",
            date_time="2026-09-19T02:00:00Z",
            local_date="2026-09-18",
            local_time="19:00:00",
            status="cancelled",
            url="https://www.ticketmaster.com/event/FX-CANCELLED",
            **_ACES_ARENA,
        ),
        _HEAD_TO_HEAD,
        # "Away at Home": the Mercury are at home.
        make_raw_event(
            event_id="FX-AT",
            name="Las Vegas Aces at Phoenix Mercury",
            date_time="2026-09-22T02:00:00Z",
            local_date="2026-09-21",
            local_time="19:00:00",
            venue_name="PHX Arena",
            venue_city="Phoenix",
            venue_state="AZ",
            venue_country="US",
            timezone="America/Phoenix",
            url="https://www.ticketmaster.com/event/FX-AT",
        ),
        # Date known, time TBA: listed, not in the feed, no SportsEvent.
        make_raw_event(
            event_id="FX-TIME-TBA",
            name="Las Vegas Aces vs Atlanta Dream",
            date_time=None,
            local_date="2026-09-24",
            local_time=None,
            time_tba=True,
            url="https://www.ticketmaster.com/event/FX-TIME-TBA",
            **_ACES_ARENA,
        ),
        # Date TBD: listed as "Date TBD", nothing else claimed.
        make_raw_event(
            event_id="FX-DATE-TBD",
            name="Las Vegas Aces vs Dallas Wings",
            date_time=None,
            local_date="2026-10-01",
            local_time=None,
            date_tbd=True,
            url="https://www.ticketmaster.com/event/FX-DATE-TBD",
            **_ACES_ARENA,
        ),
        # Not a two-team game: in the feed as a listing, never a SportsEvent.
        make_raw_event(
            event_id="FX-PACKAGE",
            name="Las Vegas Aces Premium Experiences",
            date_time="2026-09-26T02:00:00Z",
            local_date="2026-09-25",
            local_time="19:00:00",
            url="https://www.ticketmaster.com/event/FX-PACKAGE",
            **_ACES_ARENA,
        ),
        # Two teams from the attraction list only: which one is at home is
        # unknown, so no home/away label and no SportsEvent.
        make_raw_event(
            event_id="FX-ATTRACTIONS",
            name="WNBA Playoffs Round 1 Game 3",
            attractions=["Las Vegas Aces", "Phoenix Mercury"],
            date_time="2026-09-27T02:00:00Z",
            local_date="2026-09-26",
            local_time="19:00:00",
            url="https://www.ticketmaster.com/event/FX-ATTRACTIONS",
            **_ACES_ARENA,
        ),
    ],
    "seattle-storm": [_HEAD_TO_HEAD],
    "portland-thorns": [
        make_raw_event(
            event_id="FX-THORNS",
            name="Portland Thorns FC vs Seattle Reign FC",
            date_time="2026-09-27T02:00:00Z",
            local_date="2026-09-26",
            local_time="19:00:00",
            venue_name="Providence Park",
            venue_city="Portland",
            venue_state="OR",
            venue_street="1844 SW Morrison St",
            venue_postal_code="97205",
            venue_country="US",
            timezone="America/Los_Angeles",
            url="https://www.ticketmaster.com/event/FX-THORNS",
        )
    ],
    "toronto-sceptres": [
        make_raw_event(
            event_id="FX-SCEPTRES",
            name="Toronto Sceptres vs Ottawa Charge",
            date_time="2026-11-21T20:00:00Z",
            local_date="2026-11-21",
            local_time="15:00:00",
            venue_name="Coca-Cola Coliseum",
            venue_city="Toronto",
            venue_state="ON",
            venue_street="45 Manitoba Dr",
            venue_postal_code="M6K 3C3",
            venue_country="CA",
            timezone="America/Toronto",
            url="https://www.ticketmaster.ca/event/FX-SCEPTRES",
        )
    ],
}

# When the fixture's "previous live site" says its pages last changed.
PREVIOUS_CHANGED_AT = "2026-09-10T08:30:00+00:00"
# Pages whose lastmod the second fixture build must carry over (unchanged
# fingerprint), set to this build's fetch time (changed fingerprint), or set
# to it because the previous site did not have the page at all.
UNCHANGED_PAGE = "/pwhl/"
CHANGED_PAGE = "/wnba/"
NEW_PAGE = "/nwsl/portland-thorns/"


class FakeDiscoveryClient:
    """DiscoveryClient's interface, answering from RAW_EVENTS_BY_TEAM."""

    def __init__(self, api_key: str) -> None:
        self.budget = CrawlBudget()

    def __enter__(self) -> FakeDiscoveryClient:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def search_team_events(
        self, team_slug: str, team_name: str, country_codes: tuple[str, ...]
    ) -> tuple[list[dict[str, Any]], bool]:
        self.budget.requests_made += 1
        return RAW_EVENTS_BY_TEAM.get(team_slug, []), False


def build_fixture_site(
    out_dir: Path,
    *,
    previous_state: dict[str, sitemap.PageState] | None = None,
    ga4_id: str | None = None,
) -> None:
    """Builds the fixture site into out_dir through build.build(), with the
    Discovery client swapped for FakeDiscoveryClient for the duration."""
    real_client = build_module.DiscoveryClient
    build_module.DiscoveryClient = FakeDiscoveryClient
    try:
        build_module.build(
            out_dir=out_dir,
            base_url=BASE_URL,
            api_key="fixture-key",
            affiliate_id=None,
            ga4_id=ga4_id,
            previous_state=previous_state,
        )
    finally:
        build_module.DiscoveryClient = real_client


def previous_state_for(first: dict[str, sitemap.PageState]) -> dict[str, sitemap.PageState]:
    """A "previous live manifest" derived from a first fixture build's own
    manifest: UNCHANGED_PAGE keeps its fingerprint with a known date,
    CHANGED_PAGE had different content, NEW_PAGE did not exist, and every
    other page is unchanged with an unknown date."""
    previous = dict(first)
    previous[UNCHANGED_PAGE] = sitemap.PageState(first[UNCHANGED_PAGE].fingerprint, PREVIOUS_CHANGED_AT)
    previous[CHANGED_PAGE] = sitemap.PageState("sha256:older-content", PREVIOUS_CHANGED_AT)
    del previous[NEW_PAGE]
    return previous


def build_fixture_site_with_history(out_dir: Path, *, ga4_id: str | None = None) -> None:
    """Two fixture builds: the first with no history, the second against a
    previous manifest derived from the first (previous_state_for)."""
    first_dir = out_dir.with_name(out_dir.name + "-first")
    build_fixture_site(first_dir, ga4_id=ga4_id)
    first = sitemap.parse_state(json.loads((first_dir / sitemap.STATE_PATH).read_text(encoding="utf-8")))
    shutil.rmtree(first_dir)
    assert first is not None
    build_fixture_site(out_dir, previous_state=previous_state_for(first), ga4_id=ga4_id)
