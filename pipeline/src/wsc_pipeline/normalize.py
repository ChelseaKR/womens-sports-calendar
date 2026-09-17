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
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_MIN_MATCH_LEN = 4


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


def _normalize_for_match(s: str) -> str:
    return _NON_ALNUM.sub(" ", s.lower()).strip()


def _phrase_match(a: str, b: str) -> bool:
    """True if the shorter of (a, b), once lowercased and stripped of
    punctuation, is a contiguous substring of the longer one. Both sides
    must be at least _MIN_MATCH_LEN characters -- short fragments (a bare
    "FC", a single initial) are not trustworthy evidence of a match.

    This is deliberately a *phrase* match, not a word-overlap match: two
    team names that merely share a common word (a city, "FC", a mascot
    word reused by an unrelated franchise in another sport, e.g. NWSL's
    "Utah Royals" vs MLB's "Kansas City Royals") must NOT count as a
    match. Sharing one contiguous phrase is what lets "Mystics" stand in
    for "Washington Mystics" (a real Ticketmaster abbreviation seen in
    production) while still rejecting "Minnesota Timberwolves" as a stand-in
    for "Minnesota Frost" (a real Ticketmaster keyword-search false
    positive also seen in production).
    """
    na, nb = _normalize_for_match(a), _normalize_for_match(b)
    if len(na) < _MIN_MATCH_LEN or len(nb) < _MIN_MATCH_LEN:
        return False
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    return shorter in longer


def team_is_participant(team_name: str, raw_event: dict) -> bool:
    """Validates that a Discovery API keyword-search result actually names
    the searched team as a participant, instead of trusting the keyword
    match blindly.

    Why this exists: Discovery API's `keyword` parameter is a broad
    full-text search -- confirmed in production (2026-09-16) to match
    against venue names and other metadata, not just event/attraction
    names. A keyword search for NWSL's "Angel City" returned a WHL hockey
    game at "Angel Of The Winds Arena" and MLB Angels/Royals games at
    "Angel Stadium of Anaheim" -- none of which are Angel City FC. The
    existing classificationName="Sports" filter narrows the segment but
    does not restrict to the right sport, and does nothing at all against
    a same-sport, wrong-team collision (a Ticketmaster search for NWSL's
    "Bay FC" also returned real games between "Tampa Bay Sun FC" and other
    clubs). This checks what the event itself says -- its own name and
    attractions -- never the venue, never the city, so a keyword-search
    false positive can be dropped without ever entering the site's data.
    """
    embedded = raw_event.get("_embedded", {})
    attractions = embedded.get("attractions") or []
    name = raw_event.get("name", "")
    home, away = parse_teams(name, attractions)
    candidates = [c for c in (name, home, away) if c]
    candidates.extend(a.get("name") for a in attractions if a.get("name"))
    return any(_phrase_match(team_name, c) for c in candidates)


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
