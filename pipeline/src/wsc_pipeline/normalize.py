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
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

# "Home vs Away" (Ticketmaster's convention) or "Away at Home" / "Away @
# Home" (the sports convention for "at": the first team is the visitor).
_VS_SPLIT = re.compile(r"\s+(vs\.?|v\.?|at|@)\s+", re.IGNORECASE)
_AWAY_FIRST_SEPARATORS = frozenset({"at", "@"})
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
    # True only when home_team/away_team came from the event name's own
    # separator ("Home vs Away", "Away at Home"). Parsed from the two
    # _embedded.attractions instead, the pair is right but which of them is
    # at home is not known: nothing may then call either one the home team
    # (structured_data.py, site_data.py's home-game flag).
    home_away_known: bool = False
    # Ticketmaster's venue street address, postcode and country code, used
    # only as the structured-data address. None when Ticketmaster sent none.
    venue_street: str | None = None
    venue_postal_code: str | None = None
    venue_country: str | None = None
    # Ticketmaster's dates.status.code ("onsale", "offsale", "cancelled",
    # "postponed", "rescheduled"), lowercased; None when it sent none.
    status_code: str | None = None


def parse_matchup(event_name: str, attractions: list[dict[str, Any]]) -> tuple[str | None, str | None, bool]:
    """(home, away, home_away_known). Ticketmaster's convention (confirmed
    against a real PWHL sample in research, and by every WNBA listing on
    the live site: "Seattle Storm vs Las Vegas Aces" is played in Seattle)
    is "Home Team vs. Away Team" in the event name. "Away at Home" and
    "Away @ Home" name the visitor first. When the name has no separator,
    exactly two _embedded.attractions give the pair, in an order that says
    nothing about who is at home, so home_away_known is False."""
    match = _VS_SPLIT.search(event_name)
    if match:
        first, second = event_name[: match.start()].strip() or None, event_name[match.end() :].strip() or None
        if first and second:
            if match.group(1).lower() in _AWAY_FIRST_SEPARATORS:
                return second, first, True
            return first, second, True
    if len(attractions) == 2:
        names = [a.get("name") for a in attractions if a.get("name")]
        if len(names) == 2:
            return names[0], names[1], False
    return None, None, False


def parse_teams(event_name: str, attractions: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """(home, away) from parse_matchup, without the order flag."""
    home, away, _known = parse_matchup(event_name, attractions)
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


def _without_phrases(text: str, phrases: tuple[str, ...]) -> str:
    """text, normalized for matching, with every whole-word occurrence of
    each phrase removed."""
    out = _normalize_for_match(text)
    for phrase in phrases:
        norm = _normalize_for_match(phrase)
        if norm:
            out = re.sub(rf"(?<![a-z0-9]){re.escape(norm)}(?![a-z0-9])", " ", out)
    return out


def team_is_participant(team_name: str, raw_event: dict[str, Any], not_this_team: tuple[str, ...] = ()) -> bool:
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

    `not_this_team` names other teams whose names contain team_name (config
    KEYWORD_COLLISIONS, e.g. "Monterey Bay FC" for "Bay FC"); they are
    removed from each candidate before matching, so their games no longer
    match while a real game against them ("Bay FC vs Monterey Bay FC")
    still does.
    """
    embedded = raw_event.get("_embedded", {})
    attractions = embedded.get("attractions") or []
    name = raw_event.get("name", "")
    home, away = parse_teams(name, attractions)
    candidates = [c for c in (name, home, away) if c]
    candidates.extend(a.get("name") for a in attractions if a.get("name"))
    if not_this_team:
        candidates = [_without_phrases(c, not_this_team) for c in candidates]
    return any(_phrase_match(team_name, c) for c in candidates)


def _parse_price(price_ranges: list[dict[str, Any]] | None) -> PriceRange | None:
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
    raw: dict[str, Any],
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
    home, away, home_away_known = parse_matchup(raw.get("name", ""), attractions)

    city = venue.get("city") or {}
    state = venue.get("state") or {}
    address = venue.get("address") or {}
    country = venue.get("country") or {}
    status = _text((dates.get("status") or {}).get("code"))

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
        ticket_url=safe_ticket_url(raw.get("url")),
        raw_event_name=raw.get("name", ""),
        home_away_known=home_away_known,
        venue_street=_text(address.get("line1")),
        venue_postal_code=_text(venue.get("postalCode")),
        venue_country=_text(country.get("countryCode")),
        status_code=status.lower() if status else None,
    )


def _text(value: object) -> str | None:
    """A non-blank string, stripped; None for anything else."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def unique_by_event_id(games: Iterable[Game]) -> list[Game]:
    """One Game per Ticketmaster event, first occurrence kept, order kept.

    Why this exists: fetch_all_games runs one keyword search per tracked
    team, so a game between two tracked teams (e.g. Atlanta Dream vs
    Connecticut Sun) comes back twice -- once from each team's search -- as
    two Game records that differ only in tracked_team_slug. Team-level
    views need both records (the game belongs on each team's page and
    feed). Every league-level view -- the league page, the league JSON,
    the index count, the coverage report, the league .ics -- must use this
    so the game is listed and counted once. The live build of 2026-09-17
    listed 58 WNBA rows for 29 real games and 105 NWSL rows for 57.
    """
    seen: set[str] = set()
    out: list[Game] = []
    for g in games:
        if g.event_id in seen:
            continue
        seen.add(g.event_id)
        out.append(g)
    return out


def display_start(game: Game) -> str:
    """A single honest human-readable string for the start time -- never
    silently swaps a TBD game's absence for a fabricated time."""
    if game.date_tbd or game.start_local_date is None:
        return "Date TBD"
    day = display_date(game.start_local_date)
    local_time = parse_local_time(game.start_local_time)
    if game.time_tba or local_time is None:
        return f"{day} (time TBA)"
    zone = zone_for(game.tzid)
    # The venue's own zone abbreviation for that date ("PDT", "MST"), from
    # Ticketmaster's venue timezone; "local time" when it sent none.
    abbr = datetime.combine(game.start_local_date, local_time, tzinfo=zone).tzname() if zone else None
    return f"{day}, {display_time(local_time)} {abbr or 'local time'}"


def display_date(d: date) -> str:
    """ "Sun, Sep 20, 2026". Locale-independent: %a and %b are English
    under the C locale the pipeline runs in."""
    return f"{d:%a}, {d:%b} {d.day}, {d.year}"


def display_time(t: time) -> str:
    """ "6:00 PM" from a local wall-clock time."""
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def parse_local_time(value: str | None) -> time | None:
    """Ticketmaster's dates.start.localTime ("19:00:00") as a time, or None
    when absent or unparseable -- never a default time."""
    if not value:
        return None
    try:
        return time.fromisoformat(value)
    except ValueError:
        return None


def local_start(game: Game) -> datetime | None:
    """The exact start instant in the venue's own time zone, or None unless
    every part of it is known: a real (not TBD) date, a published time (not
    TBA), Ticketmaster's UTC instant, and a resolvable venue time zone. This
    is the one test for "known date and time" that the structured data uses;
    nothing here ever fills a gap with a default."""
    if game.date_tbd or game.time_tba or game.start_utc is None or parse_local_time(game.start_local_time) is None:
        return None
    if game.start_utc.tzinfo is None:  # an instant with no offset is not an instant
        return None
    zone = zone_for(game.tzid)
    if zone is None:
        return None
    return game.start_utc.astimezone(zone)


def feed_start(game: Game) -> datetime | date | None:
    """How the game goes in the calendar feeds, the one rule ics.py and the
    page's `in_calendar_feed` both read:

    - a datetime: a timed event at that exact UTC instant;
    - a date: an all-day event on that local date, for a game whose date is
      real but whose start time is not announced (`time_tba`, or no instant
      and no local time), which the page shows as "(time TBA)". A
      `time_tba` game is never a timed event, even when Ticketmaster sent a
      placeholder `dateTime` with it; no time is ever invented for it;
    - None: left out of the feeds. A game with no date at all (`date_tbd`)
      has nothing a calendar entry could say, and is still listed on the
      site.
    """
    if game.date_tbd:
        return None
    if game.time_tba:
        return game.start_local_date
    if game.start_utc is not None:
        return game.start_utc
    if game.start_local_date is not None and parse_local_time(game.start_local_time) is None:
        return game.start_local_date
    return None


def zone_for(tzid: str | None) -> ZoneInfo | None:
    if not tzid:
        return None
    try:
        return ZoneInfo(tzid)
    except Exception:
        return None


def safe_ticket_url(url: object) -> str | None:
    """The event's ticket URL only if it is an http(s) URL, else None.

    The URL comes from a third party and is rendered as a link (`href`) on
    every page and as the `URL` of every calendar entry. html.escape() stops
    it breaking out of the attribute, but not a `javascript:`, `data:` or
    `vbscript:` URL, which runs in the reader's browser when clicked. An
    unusable URL is absence (the page says there is no Ticketmaster
    listing), never a guessed or rewritten link -- rewriting would also
    strip Ticketmaster's affiliate tracking.
    """
    if not isinstance(url, str):
        return None
    scheme, separator, rest = url.partition("://")
    if separator and scheme.lower() in ("http", "https") and rest and not rest.startswith("/"):
        return url
    return None
