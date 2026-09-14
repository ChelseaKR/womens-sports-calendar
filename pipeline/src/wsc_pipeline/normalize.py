"""Turn raw Ticketmaster Discovery API event dicts into normalized Game
records. Ticketmaster is the sole data source (docs/DECISIONS.md 0006), so
"normalize" here means: parse teams out of the event name/attractions,
extract venue/start time/TZID, and extract a price range *only* when
Ticketmaster actually published one. Never guess a price; never invent a
broadcaster (no licensed source carries one). See
docs/absence-rendered-as-a-value discipline: a missing field is None, and
callers must render that as an explicit "not available", never as 0, "TBD"
treated as real, or an omitted-but-implied value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, date
from zoneinfo import ZoneInfo

_VS_SPLIT = re.compile(r"\s+(?:vs\.?|v\.?|at|@)\s+", re.IGNORECASE)


@dataclass(frozen=True)
class PriceRange:
    currency: str
    min: float
    max: float


@dataclass(frozen=True)
class Game:
    event_id: str
    league_slug: str
    tracked_team_slug: str
    tracked_team_name: str
    home_team: str | None
    away_team: str | None
    venue_name: str | None
    venue_city: str | None
    venue_state: str | None
    start_utc: datetime | None
    start_local_date: date | None
    start_local_time: str | None
    tzid: str | None
    date_tbd: bool
    time_tba: bool
    price: PriceRange | None
    ticket_url: str | None
    raw_event_name: str


def parse_teams(event_name: str, attractions: list[dict]) -> tuple[str | None, str | None]:
    """Best-effort home/away split. Ticketmaster convention (confirmed
    against a real PWHL sample in research) is "Home Team vs. Away Team" in
    the event name; _embedded.attractions, when present with exactly two
    entries, is used as a cross-check and fallback in that order."""
    home: str | None = None
    away: str | None = None
    parts = _VS_SPLIT.split(event_name, maxsplit=1)
    if len(parts) == 2:
        home, away = parts[0].strip() or None, parts[1].strip() or None
    if (home is None or away is None) and len(attractions) == 2:
        names = [a.get("name") for a in attractions if a.get("name")]
        if len(names) == 2:
            home, away = names[0], names[1]
    return home, away


def _parse_price(price_ranges: list[dict] | None) -> PriceRange | None:
    if not price_ranges:
        return None
    # Prefer the "standard" type range; Discovery API's own schema names
    # this as the common case. Never fabricate a range from an empty list.
    chosen = None
    for entry in price_ranges:
        if entry.get("type") == "standard":
            chosen = entry
            break
    if chosen is None:
        chosen = price_ranges[0]
    if chosen.get("min") is None or chosen.get("max") is None:
        return None
    return PriceRange(
        currency=chosen.get("currency", "USD"),
        min=float(chosen["min"]),
        max=float(chosen["max"]),
    )


def normalize_event(
    raw: dict,
    *,
    league_slug: str,
    tracked_team_slug: str,
    tracked_team_name: str,
) -> Game | None:
    """Returns None (and the caller drops the event) only when the event has
    no usable id or no usable date -- never fabricates either."""
    event_id = raw.get("id")
    if not event_id:
        return None

    dates = raw.get("dates", {})
    start = dates.get("start", {})
    date_tbd = bool(start.get("dateTBD", False))
    time_tba = bool(start.get("timeTBA", False))

    venue = {}
    embedded = raw.get("_embedded", {})
    venues = embedded.get("venues") or []
    if venues:
        venue = venues[0]

    tzid = venue.get("timezone") or dates.get("timezone")

    start_utc: datetime | None = None
    raw_dt = start.get("dateTime")
    if raw_dt:
        try:
            start_utc = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
        except ValueError:
            start_utc = None

    start_local_date: date | None = None
    raw_local_date = start.get("localDate")
    if raw_local_date:
        try:
            start_local_date = date.fromisoformat(raw_local_date)
        except ValueError:
            start_local_date = None

    if start_utc is None and start_local_date is None:
        # No usable date at all -- absence discipline: drop rather than
        # emit a game with a fabricated time.
        return None

    attractions = embedded.get("attractions") or []
    home, away = parse_teams(raw.get("name", ""), attractions)

    address = venue.get("address", {})
    city = venue.get("city", {})
    state = venue.get("state", {})

    return Game(
        event_id=event_id,
        league_slug=league_slug,
        tracked_team_slug=tracked_team_slug,
        tracked_team_name=tracked_team_name,
        home_team=home,
        away_team=away,
        venue_name=venue.get("name"),
        venue_city=city.get("name"),
        venue_state=(state.get("stateCode") or state.get("name")),
        start_utc=start_utc,
        start_local_date=start_local_date,
        start_local_time=start.get("localTime"),
        tzid=tzid,
        date_tbd=date_tbd,
        time_tba=time_tba,
        price=_parse_price(raw.get("priceRanges")),
        ticket_url=raw.get("url"),
        raw_event_name=raw.get("name", ""),
    )


def display_start(game: Game) -> str:
    """A single honest human-readable string for the start time -- never
    silently swaps a TBD game's absence for a fabricated time."""
    if game.date_tbd or game.start_local_date is None:
        return "Date TBD"
    date_str = game.start_local_date.isoformat()
    if game.time_tba or not game.start_local_time:
        return f"{date_str} (time TBA)"
    return f"{date_str} {game.start_local_time}" + (f" {game.tzid}" if game.tzid else "")


def zone_for(tzid: str | None) -> ZoneInfo | None:
    if not tzid:
        return None
    try:
        return ZoneInfo(tzid)
    except Exception:
        return None
