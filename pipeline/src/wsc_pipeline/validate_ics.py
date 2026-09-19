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

Usage: python -m wsc_pipeline.validate_ics <dist-dir>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from icalendar import Calendar

from . import config
from .ics import make_uid

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
            # A feed kept at each slug the team used to have: same data,
            # same page, and (checked in validate_dist) the same bytes.
            for former in team.former_slugs:
                triples.append(
                    (
                        dist / "ics" / league.slug / f"{former}.ics",
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


def _event_uids(feed: Path, cal: Calendar) -> list[str]:
    """Every VEVENT's UID, in order; raises FeedError on a VEVENT missing a
    required property or on any repeated UID."""
    uids: list[str] = []
    for vevent in cal.walk("VEVENT"):
        for prop in REQUIRED_VEVENT_PROPS:
            if vevent.get(prop) is None:
                raise FeedError(f"{feed}: a VEVENT is missing {prop.upper()}")
        uids.append(str(vevent.get("uid")))
    if len(uids) != len(set(uids)):
        dupes = sorted({u for u in uids if uids.count(u) > 1})
        raise FeedError(f"{feed}: duplicate UIDs {dupes[:5]}")
    return uids


def _check_matches_page(feed: Path, data: Path, uids: list[str]) -> None:
    """The feed's UIDs equal the UIDs of the games its page lists as in the
    calendar feed; raises FeedError otherwise."""
    if not data.is_file():
        raise FeedError(f"{data}: missing -- cannot check {feed} against its page's data")
    games = json.loads(data.read_text(encoding="utf-8"))["games"]
    expected = {make_uid(g["event_id"]) for g in games if g["in_calendar_feed"]}
    actual = set(uids)
    if actual != expected:
        raise FeedError(
            f"{feed}: feed and page disagree -- in the page's data but not the feed: "
            f"{sorted(expected - actual)[:5]}; in the feed but not the page's data: "
            f"{sorted(actual - expected)[:5]}"
        )


def validate_feed(feed: Path, data: Path, page_path: str) -> int:
    """Returns the number of VEVENTs; raises FeedError on any problem."""
    cal = _parse_calendar(feed)
    _check_links_back(feed, cal, page_path)
    uids = _event_uids(feed, cal)
    _check_matches_page(feed, data, uids)
    return len(uids)


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
    _check_former_feeds_match(dist)
    return feeds, league_events


def _check_former_feeds_match(dist: Path) -> None:
    """A feed at a former slug is the current feed, byte for byte: the
    subscriber holding the old URL must see exactly what the new one shows."""
    for league in config.LEAGUES:
        for team in league.teams:
            current = dist / "ics" / league.slug / f"{team.slug}.ics"
            for former in team.former_slugs:
                old = dist / "ics" / league.slug / f"{former}.ics"
                if old.read_bytes() != current.read_bytes():
                    raise FeedError(f"{old}: differs from {current}; a former slug must serve the same feed")


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
