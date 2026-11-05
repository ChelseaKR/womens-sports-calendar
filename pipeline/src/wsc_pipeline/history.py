"""Played games stay in the feeds, and changed events say so (DECISIONS 0027).

Ticketmaster drops a game from its listing once it starts, and the feeds used
to mirror that: a subscriber's calendar lost every game the night after it was
played, so "when did we play Iowa?" had no answer there. The site keeps no
state of its own, so, like guard.py, this reads what the live site published
last (guard.fetch_previous_publish keeps every feed's events) and:

- **keeps played games.** An event the previous publish of a feed carried is
  written into the same feed again when Ticketmaster no longer lists the game
  at all, the game has started (an all-day game: its date is over), it started
  no more than KEEP_PLAYED_DAYS ago, and its event id is not one the
  maintainer removed (config.REMOVED_EVENTS), and its name does not say it is
  a ticket product or a men's game (listings.name_says_not_a_game, for
  entries published before those were left out). It is the published VEVENT as it
  was, with only DTSTAMP set to this build's time: same UID, summary, status
  ("Canceled: " stays canceled), times, description, SEQUENCE and
  LAST-MODIFIED. Nothing about the game is re-derived or invented, and no
  score or result is claimed. A listing this build's own rules leave out
  while Ticketmaster still lists it is never kept, since the test is
  Ticketmaster's listing, not this build's games.
- **numbers revisions.** A game Ticketmaster still lists is compared with its
  previous publish. A new start, end or status raises SEQUENCE by one; any
  change to start, end, status, summary, location or ticket link sets
  LAST-MODIFIED to this build's fetch time. An unchanged event keeps both as
  published. A game first published by this build gets LAST-MODIFIED now. When
  the previous publish could not be fully read, a game it does not show is not
  called new: no LAST-MODIFIED is written for it, since a guessed date would
  be absence shown as a value.

The web pages are not changed: they show what Ticketmaster lists now, with
ticket links. Played games live in the feeds only.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from icalendar import Component, Event
from icalendar.prop import vDDDTypes

from .ics import FEED_STATUS, TIME_TBA_SUFFIX, UID_DOMAIN
from .listings import EVENT_START_SUFFIX, name_says_not_a_game

# How long a played game stays in the feeds after it starts. About a college
# season, or a WNBA one, so a subscriber can look back over the season.
KEEP_PLAYED_DAYS = 120
# The key in each page record (site_data.records_dir, never deployed) that
# names, by event id, the played games the page's feed keeps; validate_ics
# holds the feed to it.
KEPT_PLAYED_KEY = "kept_played_in_feed"

# The properties whose change is a revision of the event a subscriber sees.
# RFC 5545 3.8.7.4: SEQUENCE goes up for a significant change (start, end,
# status); LAST-MODIFIED moves for any of these. DESCRIPTION is left out: it
# repeats these and links the feed's own page, which differs from feed to feed.
_SEQUENCE_PROPS = ("dtstart", "dtend", "status")
_REVISION_PROPS = (*_SEQUENCE_PROPS, "summary", "location", "url")
_UID_PREFIX = "tm-"
_UID_SUFFIX = f"@{UID_DOMAIN}"


def event_id_of(vevent: Component) -> str | None:
    """The Ticketmaster event id in a UID this site writes, else None."""
    uid = str(vevent.get("uid", ""))
    if uid.startswith(_UID_PREFIX) and uid.endswith(_UID_SUFFIX) and len(uid) > len(_UID_PREFIX) + len(_UID_SUFFIX):
        return uid[len(_UID_PREFIX) : -len(_UID_SUFFIX)]
    return None


def _start(vevent: Component) -> datetime | date | None:
    if vevent.get("dtstart") is None:
        return None
    value = vevent.decoded("dtstart")
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else None
    return value if isinstance(value, date) else None


def has_been_played(vevent: Component, now: datetime) -> bool:
    """Started by `now`: a timed event at or before it, an all-day event on
    a date before now's UTC date (so its date is over at every venue)."""
    start = _start(vevent)
    if isinstance(start, datetime):
        return start <= now
    return start is not None and start < now.astimezone(UTC).date()


def within_keep_window(vevent: Component, now: datetime, keep_days: int = KEEP_PLAYED_DAYS) -> bool:
    """Started no more than keep_days before `now`."""
    start = _start(vevent)
    cutoff = now.astimezone(UTC) - timedelta(days=keep_days)
    if isinstance(start, datetime):
        return start >= cutoff
    return start is not None and start >= cutoff.date()


def kept_played(
    previous_events: Iterable[Component],
    *,
    listed_event_ids: frozenset[str],
    removed_event_ids: frozenset[str],
    now: datetime,
    keep_days: int = KEEP_PLAYED_DAYS,
) -> list[Event]:
    """The previous publish's events of one feed that this build writes again
    (see the module docstring), each a copy with DTSTAMP set to `now`."""
    stamp = now.astimezone(UTC).replace(microsecond=0)
    kept: list[Event] = []
    seen: set[str] = set()
    for vevent in previous_events:
        event_id = event_id_of(vevent)
        if event_id is None or event_id in seen:
            continue
        if event_id in listed_event_ids or event_id in removed_event_ids:
            continue
        if not (has_been_played(vevent, now) and within_keep_window(vevent, now, keep_days)):
            continue
        if name_says_not_a_game(listing_name(vevent)):
            continue  # published before listings.py left such listings out
        copy = Event.from_ical(vevent.to_ical())
        if not isinstance(copy, Event):
            continue
        seen.add(event_id)
        copy["DTSTAMP"] = vDDDTypes(stamp)
        kept.append(copy)
    return kept


def listing_name(vevent: Component) -> str:
    """The Ticketmaster name in a feed SUMMARY, without the status prefix and
    the time-TBA or event-start suffix the feeds add."""
    summary = str(vevent.get("summary", ""))
    for status in FEED_STATUS.values():
        if status.summary_prefix and summary.startswith(status.summary_prefix):
            summary = summary.removeprefix(status.summary_prefix)
            break
    return summary.removesuffix(TIME_TBA_SUFFIX).removesuffix(EVENT_START_SUFFIX)


def _value(vevent: Component, prop: str) -> object:
    """A comparable form of one property: start and end as UTC instants or
    dates (a time zone written differently is the same instant), text as
    text, absent as None."""
    if vevent.get(prop) is None:
        return None
    if prop in ("dtstart", "dtend"):
        value = vevent.decoded(prop)
        if isinstance(value, datetime):
            return ("at", value.astimezone(UTC) if value.tzinfo else value)
        return ("on", value)
    return str(vevent.get(prop))


@dataclass(frozen=True)
class _Published:
    values: tuple[object, ...]
    sequence: int
    last_modified: datetime | None


def _published(vevent: Component) -> _Published:
    raw_sequence = vevent.get("sequence")
    try:
        sequence = int(raw_sequence) if raw_sequence is not None else 0
    except (TypeError, ValueError):
        sequence = 0
    last_modified = vevent.decoded("last-modified") if vevent.get("last-modified") is not None else None
    return _Published(
        values=tuple(_value(vevent, p) for p in _REVISION_PROPS),
        sequence=max(sequence, 0),
        last_modified=last_modified if isinstance(last_modified, datetime) else None,
    )


@dataclass
class Revisions:
    """SEQUENCE and LAST-MODIFIED for the events this build writes, from the
    previous publish (see the module docstring). Called on each new VEVENT
    (ics.build_calendar's `revise`)."""

    now: datetime
    previous: dict[str, _Published] = field(default_factory=dict)
    # Whether every previous feed was read: only then is an event the
    # previous publish does not show known to be new.
    complete: bool = False

    @classmethod
    def from_previous(cls, events: Iterable[Component], *, now: datetime, complete: bool) -> Revisions:
        """The highest SEQUENCE any previous feed gave each event wins, with
        that copy's values and LAST-MODIFIED."""
        previous: dict[str, _Published] = {}
        for vevent in events:
            event_id = event_id_of(vevent)
            if event_id is None:
                continue
            published = _published(vevent)
            if event_id not in previous or published.sequence > previous[event_id].sequence:
                previous[event_id] = published
        return cls(now=now.astimezone(UTC).replace(microsecond=0), previous=previous, complete=complete)

    def __call__(self, event: Event) -> None:
        event_id = event_id_of(event)
        if event_id is None:
            return
        values = tuple(_value(event, p) for p in _REVISION_PROPS)
        before = self.previous.get(event_id)
        if before is None:
            _set(event, sequence=0, last_modified=self.now if self.complete else None)
            return
        if values == before.values:
            _set(event, sequence=before.sequence, last_modified=before.last_modified)
            return
        n = len(_SEQUENCE_PROPS)
        significant = values[:n] != before.values[:n]
        _set(event, sequence=before.sequence + (1 if significant else 0), last_modified=self.now)


def _set(event: Event, *, sequence: int, last_modified: datetime | None) -> None:
    """SEQUENCE when above 0 (RFC 5545: 0 is the default, so it is left off),
    and LAST-MODIFIED when known."""
    if sequence > 0:
        event.add("sequence", sequence)
    if last_modified is not None:
        event.add("last-modified", last_modified.astimezone(UTC))


@dataclass
class FeedHistory:
    """What one build carries over from the previous publish: the events to
    keep in each feed (keyed by its path, "ics/wnba.ics" or
    "ics/wnba/indiana-fever.ics") and the revision numbering for the rest."""

    kept: dict[str, list[Event]] = field(default_factory=dict)
    revisions: Revisions | None = None

    def kept_in(self, feed_path: str) -> list[Event]:
        return self.kept.get(feed_path, [])


def from_previous(
    previous_feeds: Mapping[str, Sequence[Component]],
    *,
    complete: bool,
    listed_event_ids: frozenset[str],
    removed_event_ids: frozenset[str],
    now: datetime,
    keep_days: int = KEEP_PLAYED_DAYS,
) -> FeedHistory:
    """The FeedHistory for a build whose Ticketmaster fetch listed
    `listed_event_ids`, against the previous publish's feeds."""
    kept = {
        path: kept_played(
            events,
            listed_event_ids=listed_event_ids,
            removed_event_ids=removed_event_ids,
            now=now,
            keep_days=keep_days,
        )
        for path, events in previous_feeds.items()
    }
    all_events = [vevent for events in previous_feeds.values() for vevent in events]
    return FeedHistory(
        kept={path: events for path, events in kept.items() if events},
        revisions=Revisions.from_previous(all_events, now=now, complete=complete),
    )
