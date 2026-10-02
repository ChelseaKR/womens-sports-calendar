"""Shared fixtures. Sample Discovery API event shapes reflect the fields
confirmed against Ticketmaster's own Discovery API v2 reference
(developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/,
read 2026-09-13): dates.start.{dateTime,localDate,localTime,dateTBD,timeTBA},
priceRanges[].{type,currency,min,max}, _embedded.venues[0].{name,city,state,
timezone}, _embedded.attractions[].name, and top-level id/name/url.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wsc_pipeline import sitemap

# A build's fetch time, pinned: what tests hand the calendar builders as
# `dtstamp` (ics.build_calendar never reads the clock). Before the games in
# the fixtures, so a DTSTAMP after it would be a game's own start time.
BUILD_TIME = datetime(2026, 6, 1, 8, 30, 0, tzinfo=UTC)

# The real reader of the live site's data/lastmod.json, kept before the
# autouse fixture below replaces it, for the tests that exercise it against
# a mock transport.
REAL_FETCH_PREVIOUS_STATE = sitemap.fetch_previous_state


@pytest.fixture(autouse=True)
def _no_live_site_reads(monkeypatch):
    """No test reads the live nexthomegame.com: build.main() fetches the
    previous lastmod manifest whenever an API key is set, and several tests
    set a fake one."""
    monkeypatch.setattr(sitemap, "fetch_previous_state", lambda base_url, **kwargs: None)


def make_raw_event(
    *,
    event_id: str = "EVT1",
    name: str = "Indiana Fever vs New York Liberty",
    date_time: str | None = "2026-06-15T23:00:00Z",
    local_date: str | None = "2026-06-15",
    local_time: str | None = "19:00:00",
    date_tbd: bool = False,
    time_tba: bool = False,
    price_ranges: list[dict] | None = None,
    venue_name: str | None = "Gainbridge Fieldhouse",
    venue_city: str | None = "Indianapolis",
    venue_state: str | None = "IN",
    timezone: str | None = "America/Indiana/Indianapolis",
    attractions: list[str] | None = None,
    url: str | None = "https://www.ticketmaster.com/event/EVT1",
    venue_street: str | None = None,
    venue_postal_code: str | None = None,
    venue_country: str | None = None,
    status: str | None = None,
) -> dict:
    raw: dict = {
        "id": event_id,
        "name": name,
        "url": url,
        "dates": {
            "start": {
                "dateTime": date_time,
                "localDate": local_date,
                "localTime": local_time,
                "dateTBD": date_tbd,
                "timeTBA": time_tba,
            },
            "timezone": timezone,
        },
        "_embedded": {},
    }
    if status is not None:
        raw["dates"]["status"] = {"code": status}
    if price_ranges is not None:
        raw["priceRanges"] = price_ranges
    venues = []
    if venue_name or venue_city or venue_state or timezone:
        venues.append(
            {
                "name": venue_name,
                "city": {"name": venue_city} if venue_city else {},
                "state": {"stateCode": venue_state} if venue_state else {},
                "timezone": timezone,
            }
        )
    if venues:
        if venue_street:
            venues[0]["address"] = {"line1": venue_street}
        if venue_postal_code:
            venues[0]["postalCode"] = venue_postal_code
        if venue_country:
            venues[0]["country"] = {"countryCode": venue_country}
        raw["_embedded"]["venues"] = venues
    if attractions:
        raw["_embedded"]["attractions"] = [{"name": a} for a in attractions]
    return raw


STANDARD_PRICE = [{"type": "standard", "currency": "USD", "min": 25.0, "max": 150.0}]


@pytest.fixture
def event_with_price():
    return make_raw_event(event_id="EVT-PRICE", price_ranges=STANDARD_PRICE)


@pytest.fixture
def event_without_price():
    return make_raw_event(event_id="EVT-NOPRICE", price_ranges=None)


@pytest.fixture
def event_date_tbd():
    # Realistic TM shape: a placeholder local date is published, but no
    # exact instant yet -- dateTBD=True, dateTime absent. This must be
    # dropped from the .ics (no exact instant to schedule) but still shown
    # on the site as "Date TBD", never silently disappeared.
    return make_raw_event(
        event_id="EVT-TBD",
        date_time=None,
        local_date="2026-08-01",
        local_time=None,
        date_tbd=True,
    )
