"""Shared fixtures. Sample Discovery API event shapes reflect the fields
confirmed against Ticketmaster's own Discovery API v2 reference
(developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/,
read 2026-09-13): dates.start.{dateTime,localDate,localTime,dateTBD,timeTBA},
priceRanges[].{type,currency,min,max}, _embedded.venues[0].{name,city,state,
timezone}, _embedded.attractions[].name, and top-level id/name/url.
"""

from __future__ import annotations

import pytest


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
