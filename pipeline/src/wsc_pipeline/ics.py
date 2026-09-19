"""Emit RFC 5545 .ics calendars, one per league and one per team.

Stable UIDs: a Ticketmaster event id is stable across our nightly rebuilds
(it names the same on-sale event every night we see it), so the UID is
derived deterministically from it. Re-subscribing, or a calendar client
re-fetching the same feed tomorrow, must not duplicate entries -- this is
the whole reason the UID is not random and not build-timestamp-based.

UID_DOMAIN is a placeholder identifier, not a resolvable domain. It must
never change once games have been published under it, or every
subscriber's calendar app will treat the next build's games as new
duplicates instead of updates. Games have been live under it at
nexthomegame.com since 2026-09-14, so it keeps the old working name on
purpose; it is an opaque id, not a link.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from icalendar import Calendar, Event, Timezone, vText

from .normalize import Game, unique_by_event_id, zone_for
from .site_data import NOTABLE_STATUSES

UID_DOMAIN = "womens-sports-calendar.invalid"
# PRODID only names the producing software; clients do not key on it, so it
# can follow the product name (unlike UID_DOMAIN above, which must not move).
PRODID = "-//Next Home Game//nexthomegame.com//EN"
# The product name, as the pages spell it (site.SITE_NAME); repeated here
# rather than imported so the feed module does not depend on the HTML one.
SITE_NAME = "Next Home Game"
# The site rebuilds every night, so a subscriber's app is asked to refresh
# daily (RFC 7986 REFRESH-INTERVAL, and X-PUBLISHED-TTL for Outlook). Apps
# may poll less often; none is asked to poll more often than the data moves.
REFRESH_INTERVAL = timedelta(days=1)
# The line in every event that carries an estimated DTEND. Ticketmaster
# publishes no end time (DECISIONS 0015), so the end is a per-sport estimate
# (config.GAME_DURATIONS) and the event says so rather than presenting it as
# data. validate_ics requires it wherever a DTEND is written.
END_ESTIMATE_NOTE = "End time estimated; not published by the ticket source."


@dataclass(frozen=True)
class FeedStatus:
    """What a subscriber's calendar is told about a game Ticketmaster does
    not list as simply going ahead: the machine-readable RFC 5545 STATUS
    (None leaves the property off, so the event stays an ordinary one), a
    visible prefix on SUMMARY for the apps that hide or ignore STATUS, and
    the first line of DESCRIPTION. Visible text is American English; the
    page's own status word ("Cancelled", site_data.NOTABLE_STATUSES) is a
    published value and is not touched."""

    ics_status: str | None
    summary_prefix: str
    note: str


# Keyed by the page's status word (game_to_dict's `status`), so the feed and
# the page read one rule for which games have a status. validate_ics holds
# every feed to this table against its page's data. "Rescheduled" keeps the
# event confirmed at the time Ticketmaster lists and only says so in the
# description; it does not claim which date the listing carries.
FEED_STATUS = {
    "Cancelled": FeedStatus(
        ics_status="CANCELLED",
        summary_prefix="Canceled: ",
        note="Canceled: Ticketmaster lists this game as canceled.",
    ),
    "Postponed": FeedStatus(
        ics_status="TENTATIVE",
        summary_prefix="Postponed: ",
        note=(
            "Postponed: Ticketmaster lists this game as postponed. The date and time shown may be the "
            "original ones; check the Ticketmaster listing for a new date."
        ),
    ),
    "Rescheduled": FeedStatus(
        ics_status=None,
        summary_prefix="",
        note=(
            "Rescheduled: Ticketmaster lists this game as rescheduled. Check the Ticketmaster listing "
            "for the current date and time."
        ),
    ),
}


def feed_status(game: Game) -> FeedStatus | None:
    """The game's feed status, or None for a game with nothing notable
    (Ticketmaster's onsale, offsale or no status say nothing about whether
    the game is on)."""
    word = NOTABLE_STATUSES.get(game.status_code or "")
    return FEED_STATUS[word] if word else None


class DuplicateUIDError(ValueError):
    pass


def make_uid(event_id: str) -> str:
    return f"tm-{event_id}@{UID_DOMAIN}"


def check_no_duplicate_uids(games: list[Game]) -> None:
    counts = Counter(make_uid(g.event_id) for g in games)
    dupes = {uid: n for uid, n in counts.items() if n > 1}
    if dupes:
        raise DuplicateUIDError(f"duplicate UIDs would be emitted: {dupes}")


NOT_FETCHED_CALDESC = (
    "Not fetched: this build did not query Ticketmaster, so this calendar is "
    "empty because nothing was read, not because there are no games."
)


def calendar_name(subject: str) -> str:
    """The calendar's display name in the subscriber's app (X-WR-CALNAME,
    RFC 7986 NAME, and the Outlook subscribe link's `name`): the team or
    league first, then where it came from."""
    return f"{subject} ({SITE_NAME})"


def calendar_description(subject: str, *, page_url: str | None, fetched: bool) -> str:
    """X-WR-CALDESC / DESCRIPTION: what the calendar holds, and a link back
    to its page on the site, where the full schedule and the other
    calendars are."""
    link = f" Schedule, venues and ticket links: {page_url}" if page_url else ""
    if not fetched:
        return NOT_FETCHED_CALDESC + link
    return f"Every {subject} game listed by Ticketmaster, updated nightly by {SITE_NAME}.{link}"


def build_calendar(
    games: list[Game],
    *,
    cal_name: str,
    fetched: bool = True,
    cal_desc: str | None = None,
    page_url: str | None = None,
    dtstamp: datetime | None = None,
    game_duration: timedelta | None = None,
) -> Calendar:
    """Games with no usable date were already dropped by normalize_event;
    games with date_tbd=True (a real Ticketmaster date placeholder, not a
    missing field) are also excluded here -- a calendar entry needs a real
    date, and RFC 5545 does not have a clean "TBD" representation. Those
    games are still visible on the site (see site_data.py), just not in
    the .ics. This is documented, not silent.

    A game Ticketmaster lists as cancelled, postponed or rescheduled stays
    in the feed and carries that status (FEED_STATUS): a feed that dropped it
    would leave the subscriber's calendar showing a game that is off, and a
    feed that kept it unmarked would be worse.

    page_url, when given, is the calendar's page on the site: the
    calendar's URL property, and the last line of every event's
    description. Nothing about it reaches a UID, so adding or changing it
    never duplicates a subscriber's events.

    dtstamp is when this copy of the calendar was built (RFC 5545 section
    3.8.7.2: for METHOD:PUBLISH, when the calendar object was created), the
    same for every event, timezone-aware, kept to whole seconds. The caller
    passes the build's fetch time in: this module never reads the clock, so
    a given build is reproducible and a test can pin it. It is required as
    soon as any event is written; a build that wrote no events (nothing
    fetched) has none to stamp. It is never the game's own start time, which
    is in the future for an upcoming game and moves when a game does.

    game_duration is the assumed length of one game of this calendar's sport
    (config.estimated_duration): each timed event gets a DTEND that long
    after its start and a description line saying the end is estimated. None
    (a sport with no estimate) writes no DTEND at all.
    """
    games = unique_by_event_id(games)
    check_no_duplicate_uids(games)

    if cal_desc is None:
        cal_desc = "Ticketmaster-listed games; see the site for licensing notes." if fetched else NOT_FETCHED_CALDESC
    cal = _calendar_header(cal_name=cal_name, cal_desc=cal_desc, page_url=page_url)

    stamp = _as_dtstamp(dtstamp) if dtstamp is not None else None
    tzids_seen: set[str] = set()
    for game in sorted(games, key=lambda g: (g.start_utc is None, g.start_utc or g.start_local_date)):
        if game.date_tbd or game.start_utc is None:
            continue
        if stamp is None:
            raise ValueError("build_calendar needs dtstamp (the build's time) to write an event")
        if game.tzid and game.tzid not in tzids_seen:
            tzids_seen.add(game.tzid)
            vtz = Timezone.from_tzid(game.tzid)
            if vtz is not None:
                cal.add_component(vtz)
        cal.add_component(_event(game, game.start_utc, page_url=page_url, dtstamp=stamp, duration=game_duration))

    return cal


def _as_dtstamp(when: datetime) -> datetime:
    """`when` as a UTC, whole-second DTSTAMP; naive times are refused, since
    a floating DTSTAMP is not RFC 5545 and would be a guess about the zone."""
    if when.tzinfo is None:
        raise ValueError("dtstamp must be timezone-aware (the build's UTC time)")
    return when.astimezone(UTC).replace(microsecond=0)


def _calendar_header(*, cal_name: str, cal_desc: str, page_url: str | None) -> Calendar:
    cal = Calendar()
    cal.add("prodid", PRODID)
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", cal_name)
    cal.add("x-wr-caldesc", cal_desc)
    # RFC 7986 spellings of the same name and description, for apps that
    # read those instead of the X-WR- extensions.
    cal.add("name", cal_name)
    cal.add("description", cal_desc)
    if page_url:
        cal.add("url", page_url)
    cal.add("refresh-interval", REFRESH_INTERVAL, parameters={"VALUE": "DURATION"})
    cal.add("x-published-ttl", "P1D")
    return cal


def _event(
    game: Game,
    start_utc: datetime,
    *,
    page_url: str | None,
    dtstamp: datetime,
    duration: timedelta | None,
) -> Event:
    """One VEVENT, for a game whose real start instant is start_utc, in a
    calendar built at dtstamp.

    DTEND is start_utc plus `duration` when there is one: an estimate, not
    Ticketmaster data, and the description says so (END_ESTIMATE_NOTE). It is
    added to the UTC instant and then shown in the venue's zone, so a game
    that spans a clock change still ends the estimated time later. There is
    no SEQUENCE or LAST-MODIFIED: either needs the previous published data
    to compare against, and a value derived without it would change on
    every build for every event.
    """
    event = Event()
    event.add("uid", make_uid(game.event_id))
    event.add("dtstamp", dtstamp)
    zone = zone_for(game.tzid)
    dtstart = start_utc.astimezone(zone) if zone else start_utc
    event.add("dtstart", dtstart)
    if duration is not None:
        end_utc = start_utc + duration
        event.add("dtend", end_utc.astimezone(zone) if zone else end_utc)
    summary = game.raw_event_name or f"{game.home_team or '?'} vs {game.away_team or '?'}"
    status = feed_status(game)
    if status:
        summary = status.summary_prefix + summary
        if status.ics_status:
            event.add("status", status.ics_status)
    event.add("summary", vText(summary))
    location_parts = [p for p in (game.venue_name, game.venue_city, game.venue_state) if p]
    if location_parts:
        event.add("location", vText(", ".join(location_parts)))
    description_lines = [status.note] if status else []
    description_lines.append(f"League: {game.league_slug.upper()}")
    if duration is not None:
        description_lines.append(END_ESTIMATE_NOTE)
    if game.price:
        description_lines.append(
            f"Tickets: {game.price.currency} {game.price.min:.2f}-{game.price.max:.2f} (Ticketmaster)"
        )
    else:
        description_lines.append("Tickets: price not available from Ticketmaster")
    if game.ticket_url:
        description_lines.append(f"Buy: {game.ticket_url}")
        event.add("url", game.ticket_url)
    if page_url:
        description_lines.append(f"More games and calendars: {page_url}")
    event.add("description", vText("\n".join(description_lines)))
    return event


def league_calendar(
    league_slug: str,
    league_name: str,
    games: list[Game],
    *,
    fetched: bool = True,
    base_url: str | None = None,
    dtstamp: datetime | None = None,
    game_duration: timedelta | None = None,
) -> Calendar:
    page_url = f"{base_url}/{league_slug}/" if base_url else None
    return build_calendar(
        games,
        cal_name=calendar_name(league_name),
        fetched=fetched,
        cal_desc=calendar_description(league_name, page_url=page_url, fetched=fetched),
        page_url=page_url,
        dtstamp=dtstamp,
        game_duration=game_duration,
    )


def team_calendar(
    team_slug: str,
    team_name: str,
    games: list[Game],
    *,
    fetched: bool = True,
    base_url: str | None = None,
    league_slug: str | None = None,
    dtstamp: datetime | None = None,
    game_duration: timedelta | None = None,
) -> Calendar:
    team_games = [g for g in games if g.tracked_team_slug == team_slug]
    page_url = f"{base_url}/{league_slug}/{team_slug}/" if base_url and league_slug else None
    return build_calendar(
        team_games,
        cal_name=calendar_name(team_name),
        fetched=fetched,
        cal_desc=calendar_description(team_name, page_url=page_url, fetched=fetched),
        page_url=page_url,
        dtstamp=dtstamp,
        game_duration=game_duration,
    )


def group_by_team(games: list[Game]) -> dict[str, list[Game]]:
    out: dict[str, list[Game]] = defaultdict(list)
    for g in games:
        out[g.tracked_team_slug].append(g)
    return dict(out)
