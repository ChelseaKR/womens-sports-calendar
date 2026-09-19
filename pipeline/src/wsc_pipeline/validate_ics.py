"""Validate the .ics feeds a build actually wrote, before they are published.

tests/test_ics_validator.py checks calendars built from synthetic fixtures.
Nothing checked the real feeds the nightly build writes into dist/ics/ --
the files every subscriber's calendar app re-fetches -- before pages.yml
deployed them. This does, and exits non-zero on the first build that would
publish a broken or inconsistent feed:

1. Every feed the site links to exists: one per tracked league
   (ics/<league>.ics) and one per tracked team (ics/<league>/<team>.ics),
   per wsc_pipeline.config. A missing file is a subscribe link that 404s.
2. Every feed parses as RFC 5545 (icalendar), declares VERSION:2.0, a
   PRODID, an X-WR-CALNAME, and a URL that is its own page on the site,
   which its X-WR-CALDESC also links to (so a subscriber can always find
   the way back); and every VEVENT has UID, DTSTAMP, DTSTART and SUMMARY.
3. No UID repeats within one feed (a repeat is a duplicate entry in the
   subscriber's calendar).
4. Each feed carries exactly the games its page shows as in the calendar
   feed: the set of UIDs equals the set of make_uid(event_id) for the
   games in the matching data/*.json with in_calendar_feed true. A feed
   that silently drops a game the page lists -- or carries one the page
   does not -- fails here.
5. A game the page marks Cancelled, Postponed or Rescheduled carries the
   matching STATUS, SUMMARY marker and DESCRIPTION note in its feed entry
   (ics.FEED_STATUS), and a game the page marks with nothing carries no
   STATUS: a canceled game must never be an ordinary confirmed event in a
   subscriber's calendar.
6. Every event's DTSTAMP is a UTC date-time that is not after the build's
   fetch time (the data JSON's `fetched_at`): a DTSTAMP is when the calendar
   copy was made, so one in the future (the game's own start time was written
   there before) is wrong, and a build with events but no fetch time to check
   them against is refused.

Usage: python -m wsc_pipeline.validate_ics <dist-dir>
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from icalendar import Calendar, Component

from . import config
from .ics import FEED_STATUS, make_uid

REQUIRED_VEVENT_PROPS = ("uid", "dtstamp", "dtstart", "summary")


class FeedError(ValueError):
    pass


def _expected_feeds(dist: Path) -> list[tuple[Path, Path, str]]:
    """(feed path, matching data JSON path, its page's site path) for every
    feed the site links."""
    triples = []
    for league in config.LEAGUES:
        triples.append((dist / "ics" / f"{league.slug}.ics", dist / "data" / f"{league.slug}.json", f"/{league.slug}/"))
        for team in league.teams:
            triples.append(
                (
                    dist / "ics" / league.slug / f"{team.slug}.ics",
                    dist / "data" / league.slug / f"{team.slug}.json",
                    f"/{league.slug}/{team.slug}/",
                )
            )
    return triples


def _parse_calendar(feed: Path) -> Calendar:
    """The feed as a parsed VCALENDAR with its required calendar-level
    properties; raises FeedError otherwise."""
    if not feed.is_file():
        raise FeedError(f"{feed}: missing -- the site links a subscribe URL that would 404")
    try:
        cal = Calendar.from_ical(feed.read_bytes())
    except Exception as exc:  # icalendar raises ValueError subclasses and others
        raise FeedError(f"{feed}: does not parse as iCalendar: {exc}") from exc
    if str(cal.get("version")) != "2.0":
        raise FeedError(f"{feed}: VCALENDAR must declare VERSION:2.0")
    for prop in ("prodid", "x-wr-calname", "x-wr-caldesc", "url"):
        if cal.get(prop) is None:
            raise FeedError(f"{feed}: VCALENDAR is missing {prop.upper()}")
    return cal


def _check_links_back(feed: Path, cal: Calendar, page_path: str) -> None:
    """The calendar's URL is its own page, and its description links there."""
    url = str(cal.get("url"))
    if not url.startswith(("https://", "http://")) or not url.endswith(page_path):
        raise FeedError(f"{feed}: URL {url!r} is not this calendar's page ({page_path})")
    if url not in str(cal.get("x-wr-caldesc")):
        raise FeedError(f"{feed}: X-WR-CALDESC does not link to {url}")


def _events(feed: Path, cal: Calendar) -> dict[str, Component]:
    """Every VEVENT by UID; raises FeedError on a VEVENT missing a required
    property or on any repeated UID."""
    uids: list[str] = []
    events: dict[str, Component] = {}
    for vevent in cal.walk("VEVENT"):
        for prop in REQUIRED_VEVENT_PROPS:
            if vevent.get(prop) is None:
                raise FeedError(f"{feed}: a VEVENT is missing {prop.upper()}")
        uid = str(vevent.get("uid"))
        uids.append(uid)
        events[uid] = vevent
    if len(uids) != len(set(uids)):
        dupes = sorted({u for u in uids if uids.count(u) > 1})
        raise FeedError(f"{feed}: duplicate UIDs {dupes[:5]}")
    return events


def _page_data(feed: Path, data: Path) -> dict[str, Any]:
    """The data JSON the feed's page renders from."""
    if not data.is_file():
        raise FeedError(f"{data}: missing -- cannot check {feed} against its page's data")
    payload: dict[str, Any] = json.loads(data.read_text(encoding="utf-8"))
    return payload


def _check_matches_page(feed: Path, games: list[dict[str, Any]], uids: set[str]) -> None:
    """The feed's UIDs equal the UIDs of the games its page lists as in the
    calendar feed; raises FeedError otherwise."""
    expected = {make_uid(g["event_id"]) for g in games if g["in_calendar_feed"]}
    if uids != expected:
        raise FeedError(
            f"{feed}: feed and page disagree -- in the page's data but not the feed: "
            f"{sorted(expected - uids)[:5]}; in the feed but not the page's data: "
            f"{sorted(uids - expected)[:5]}"
        )


def _check_status_matches_page(feed: Path, games: list[dict[str, Any]], events: dict[str, Component]) -> None:
    """A game the page marks Cancelled, Postponed or Rescheduled carries that
    status in its feed entry, and a game with no page status carries no
    STATUS; raises FeedError otherwise. Only games in the feed are checked
    here (_check_matches_page owns which games those are)."""
    for game in games:
        if not game["in_calendar_feed"]:
            continue
        uid = make_uid(game["event_id"])
        vevent = events[uid]
        word = game.get("status")
        expected = None
        if word:
            expected = FEED_STATUS.get(word)
            if expected is None:
                raise FeedError(f"{feed}: {uid} has page status {word!r}, which the feed has no rule for")
        raw_status = vevent.get("status")
        actual_status = str(raw_status) if raw_status is not None else None
        expected_status = expected.ics_status if expected else None
        if actual_status != expected_status:
            raise FeedError(
                f"{feed}: {uid} is {word or 'unmarked'} on its page but its STATUS is {actual_status!r} "
                f"in the feed (expected {expected_status!r})"
            )
        if expected is None:
            continue
        if not str(vevent.get("summary")).startswith(expected.summary_prefix):
            raise FeedError(f"{feed}: {uid} is {word} on its page but its SUMMARY does not say so")
        if not str(vevent.get("description", "")).startswith(expected.note):
            raise FeedError(f"{feed}: {uid} is {word} on its page but its DESCRIPTION does not say so")


def _check_dtstamps(feed: Path, events: dict[str, Component], fetched_at: str | None) -> None:
    """Every DTSTAMP is a UTC date-time no later than the build's fetch time;
    raises FeedError otherwise."""
    if not events:
        return
    if not fetched_at:
        raise FeedError(f"{feed}: has events but its page's data records no fetch time to check DTSTAMP against")
    built = datetime.fromisoformat(fetched_at)
    for uid, vevent in events.items():
        stamp = vevent.decoded("dtstamp")
        if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
            raise FeedError(f"{feed}: {uid} DTSTAMP is not a UTC date-time")
        if stamp > built:
            raise FeedError(
                f"{feed}: {uid} DTSTAMP {stamp.isoformat()} is after the build's fetch time {built.isoformat()} "
                "-- a DTSTAMP is when the calendar copy was made, never a game's future start time"
            )


def validate_feed(feed: Path, data: Path, page_path: str) -> int:
    """Returns the number of VEVENTs; raises FeedError on any problem."""
    cal = _parse_calendar(feed)
    _check_links_back(feed, cal, page_path)
    events = _events(feed, cal)
    page = _page_data(feed, data)
    games = page["games"]
    _check_matches_page(feed, games, set(events))
    _check_status_matches_page(feed, games, events)
    _check_dtstamps(feed, events, page.get("fetched_at"))
    return len(events)


def validate_dist(dist: Path) -> tuple[int, int]:
    """Returns (feeds checked, total VEVENTs across league feeds)."""
    feeds = 0
    league_events = 0
    league_feeds = {dist / "ics" / f"{lg.slug}.ics" for lg in config.LEAGUES}
    for feed, data, page_path in _expected_feeds(dist):
        n = validate_feed(feed, data, page_path)
        feeds += 1
        if feed in league_feeds:
            league_events += n
    return feeds, league_events


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        feeds, events = validate_dist(Path(argv[0]))
    except FeedError as exc:
        print(f"ICS VALIDATION FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"ics validation: {feeds} feeds valid, each matching its page; {events} events across league feeds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
