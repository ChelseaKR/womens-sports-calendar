"""Emit RFC 5545 .ics calendars, one per league and one per team.

Stable UIDs: a Ticketmaster event id is stable across our nightly rebuilds
(it names the same on-sale event every night we see it), so the UID is
derived deterministically from it. Re-subscribing, or a calendar client
re-fetching the same feed tomorrow, must not duplicate entries -- this is
the whole reason the UID is not random and not build-timestamp-based.

UID_DOMAIN is a placeholder identifier, not a resolvable domain (the real
domain is undecided, DECISIONS 0005). It must never change once games have
been published under it, or every subscriber's calendar app will treat the
next build's games as new duplicates instead of updates. Pin it once and
leave it as the product's domain gets decided.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from icalendar import Calendar, Event, Timezone, vText

from .normalize import Game, display_start, zone_for

UID_DOMAIN = "womens-sports-calendar.invalid"
PRODID = "-//ChelseaKR//womens-sports-calendar//EN"


class DuplicateUIDError(ValueError):
    pass


def make_uid(event_id: str) -> str:
    return f"tm-{event_id}@{UID_DOMAIN}"


def check_no_duplicate_uids(games: list[Game]) -> None:
    counts = Counter(make_uid(g.event_id) for g in games)
    dupes = {uid: n for uid, n in counts.items() if n > 1}
    if dupes:
        raise DuplicateUIDError(f"duplicate UIDs would be emitted: {dupes}")


def _dedup_by_event_id(games: list[Game]) -> list[Game]:
    seen: set[str] = set()
    out = []
    for g in games:
        if g.event_id in seen:
            continue
        seen.add(g.event_id)
        out.append(g)
    return out


def build_calendar(games: list[Game], *, cal_name: str) -> Calendar:
    """Games with no usable date were already dropped by normalize_event;
    games with date_tbd=True (a real Ticketmaster date placeholder, not a
    missing field) are also excluded here -- a calendar entry needs a real
    date, and RFC 5545 does not have a clean "TBD" representation. Those
    games are still visible on the site (see site_data.py), just not in
    the .ics. This is documented, not silent.
    """
    games = _dedup_by_event_id(games)
    check_no_duplicate_uids(games)

    cal = Calendar()
    cal.add("prodid", PRODID)
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", cal_name)
    cal.add("x-wr-caldesc", "Ticketmaster-listed games; see the site for licensing notes.")

    tzids_seen: set[str] = set()
    n_included = 0
    for game in sorted(games, key=lambda g: (g.start_utc is None, g.start_utc or g.start_local_date)):
        if game.date_tbd or game.start_utc is None:
            continue
        if game.tzid and game.tzid not in tzids_seen:
            tzids_seen.add(game.tzid)
            vtz = Timezone.from_tzid(game.tzid)
            if vtz is not None:
                cal.add_component(vtz)

        event = Event()
        event.add("uid", make_uid(game.event_id))
        event.add("dtstamp", game.start_utc)
        zone = zone_for(game.tzid)
        dtstart = game.start_utc.astimezone(zone) if zone else game.start_utc
        event.add("dtstart", dtstart)
        summary = game.raw_event_name or f"{game.home_team or '?'} vs {game.away_team or '?'}"
        event.add("summary", vText(summary))
        location_parts = [p for p in (game.venue_name, game.venue_city, game.venue_state) if p]
        if location_parts:
            event.add("location", vText(", ".join(location_parts)))
        description_lines = [f"League: {game.league_slug.upper()}"]
        if game.price:
            description_lines.append(
                f"Tickets: {game.price.currency} {game.price.min:.2f}-{game.price.max:.2f} (Ticketmaster)"
            )
        else:
            description_lines.append("Tickets: price not available from Ticketmaster")
        if game.ticket_url:
            description_lines.append(f"Buy: {game.ticket_url}")
            event.add("url", game.ticket_url)
        event.add("description", vText("\n".join(description_lines)))
        cal.add_component(event)
        n_included += 1

    return cal


def league_calendar(league_slug: str, league_name: str, games: list[Game]) -> Calendar:
    return build_calendar(games, cal_name=f"{league_name} (Ticketmaster listings)")


def team_calendar(team_slug: str, team_name: str, games: list[Game]) -> Calendar:
    team_games = [g for g in games if g.tracked_team_slug == team_slug]
    return build_calendar(team_games, cal_name=f"{team_name} (Ticketmaster listings)")


def group_by_team(games: list[Game]) -> dict[str, list[Game]]:
    out: dict[str, list[Game]] = defaultdict(list)
    for g in games:
        out[g.tracked_team_slug].append(g)
    return dict(out)
