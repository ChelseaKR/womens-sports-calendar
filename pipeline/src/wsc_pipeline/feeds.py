"""Atom 1.0 (RFC 4287) feeds of upcoming home games: one per league and one
for every league, under /feeds/.

Every value comes from the Ticketmaster listings, never from the clock:

* an entry's ``id`` is the team page's permalink plus Ticketmaster's event
  id, so the same game keeps one id on every rebuild;
* an entry's ``updated`` is the game's own scheduled start (UTC). The
  listings carry no "last changed" time, and the build's fetch time moves
  every night (the .ics DTSTAMP does, and that is not repeated here), so the
  only date that is both the data's and stable is the game's. Readers that
  sort by it list games in play order. A game's later change (a cancellation)
  changes its summary but not its ``updated``; the feed says so;
* the feed's ``updated`` is its newest entry's.

Only a game that is a home game for a tracked team, with a published date and
time and an exact start (normalize.local_start), is an entry. A feed with no
such game is not written at all (absence, not an empty feed with an invented
date), and its pages carry no autodiscovery link. No buy link is in a feed.
"""

from __future__ import annotations

# The standard library's ElementTree only writes the feed here (Element,
# SubElement, tostring); nothing is parsed, so the XXE and entity-expansion
# risk behind the rule cannot arise. defusedxml has no way to build elements.
import xml.etree.ElementTree as ET  # nosemgrep: python.lang.security.use-defused-xml.use-defused-xml
from collections.abc import Mapping
from datetime import UTC
from typing import Any

from . import config, site_data, structured_data
from .normalize import Game, local_start

ATOM_NS = "http://www.w3.org/2005/Atom"
FEED_MEDIA_TYPE = "application/atom+xml"
FEEDS_DIR = "feeds"
ALL_KEY = "all"
SOURCE_LINE = "Game listings: Ticketmaster Discovery API."

ET.register_namespace("", ATOM_NS)


def _q(tag: str) -> str:
    return f"{{{ATOM_NS}}}{tag}"


def feed_path(key: str) -> str:
    """Site-relative path: "feeds/all.atom" or "feeds/<league>.atom"."""
    return f"{FEEDS_DIR}/{key}.atom"


def _entries(league: config.League, games: list[Game]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for team in league.teams:
        payload = site_data.team_data(team, league, games)
        by_id = {g.event_id: g for g in games if g.tracked_team_slug == team.slug}
        for d in payload["games"]:
            if d["tracked_team_is_home"] is not True or d["event_id"] in seen:
                continue
            g = by_id.get(d["event_id"])
            start = local_start(g) if g else None
            if start is None or not d["home_team"] or not d["away_team"]:
                continue
            seen.add(d["event_id"])
            out.append(
                {
                    "league": league,
                    "team": team,
                    "game": d,
                    "start": start,
                    "updated": start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            )
    return sorted(out, key=lambda x: (x["updated"], x["game"]["event_id"]))


def _render(*, entries: list[dict[str, Any]], base_url: str, path: str, title: str, page_url: str) -> str:
    feed = ET.Element(_q("feed"), {"{http://www.w3.org/XML/1998/namespace}lang": "en-US"})
    self_url = f"{base_url}/{path}"
    ET.SubElement(feed, _q("id")).text = self_url
    ET.SubElement(feed, _q("title")).text = title
    ET.SubElement(feed, _q("subtitle")).text = (
        "Upcoming home games as Ticketmaster lists them, soonest first. Each entry's date is the "
        "game's own start time, not a publication time. Confirm a game before you go."
    )
    ET.SubElement(feed, _q("updated")).text = max(e["updated"] for e in entries)
    ET.SubElement(feed, _q("link"), {"rel": "self", "type": FEED_MEDIA_TYPE, "href": self_url})
    ET.SubElement(feed, _q("link"), {"rel": "alternate", "type": "text/html", "href": page_url})
    author = ET.SubElement(feed, _q("author"))
    ET.SubElement(author, _q("name")).text = "Next Home Game"
    ET.SubElement(author, _q("uri")).text = f"{base_url}/"
    ET.SubElement(
        feed, _q("rights")
    ).text = f"{SOURCE_LINE} Next Home Game is independent and is not affiliated with any league, team or Ticketmaster."
    ET.SubElement(feed, _q("generator")).text = "Next Home Game"
    for e in entries:
        d, team, league = e["game"], e["team"], e["league"]
        permalink = f"{base_url}/{league.slug}/{team.slug}/"
        item = ET.SubElement(feed, _q("entry"))
        ET.SubElement(item, _q("id")).text = f"{permalink}#game-{d['event_id']}"
        label = structured_data.event_name({"home_team": d["home_team"], "away_team": d["away_team"]})
        status = f" ({d['status']})" if d["status"] else ""
        ET.SubElement(item, _q("title")).text = f"{label}, {e['start'].strftime('%b %-d')}{status}"
        ET.SubElement(item, _q("link"), {"rel": "alternate", "type": "text/html", "href": permalink})
        ET.SubElement(item, _q("updated")).text = e["updated"]
        venue = ", ".join(x for x in (d["venue_name"], d["venue_city"], d["venue_state"]) if x)
        parts = [
            f"{league.name} home game for {team.shown_name}: {label}.",
            f"Starts {d['start_display']}.",
        ]
        if venue:
            parts.append(f"Venue: {venue}.")
        if d["status"]:
            parts.append(f"Ticketmaster lists this game as {d['status'].lower()}.")
        parts.append(SOURCE_LINE)
        ET.SubElement(item, _q("summary"), {"type": "text"}).text = " ".join(parts)
    ET.indent(feed)
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(feed, encoding="unicode") + "\n"


def build_feeds(games_by_league: Mapping[str, list[Game]], *, base_url: str, fetched: bool) -> dict[str, str]:
    """{feed key: Atom text} for each league with at least one eligible game,
    plus ALL_KEY across them. Empty when the build did not fetch."""
    if not fetched:
        return {}
    per_league = {lg.slug: _entries(lg, games_by_league[lg.slug]) for lg in config.LEAGUES}
    out: dict[str, str] = {}
    for lg in config.LEAGUES:
        if per_league[lg.slug]:
            out[lg.slug] = _render(
                entries=per_league[lg.slug],
                base_url=base_url,
                path=feed_path(lg.slug),
                title=f"Next Home Game: {lg.name} home games",
                page_url=f"{base_url}/{lg.slug}/",
            )
    everything = sorted(
        (e for v in per_league.values() for e in v), key=lambda x: (x["updated"], x["game"]["event_id"])
    )
    if everything:
        out[ALL_KEY] = _render(
            entries=everything,
            base_url=base_url,
            path=feed_path(ALL_KEY),
            title="Next Home Game: home games in every league",
            page_url=f"{base_url}/",
        )
    return out


def feed_title(key: str) -> str:
    if key == ALL_KEY:
        return "Next Home Game: home games in every league (Atom)"
    lg = next(x for x in config.LEAGUES if x.slug == key)
    return f"Next Home Game: {lg.name} home games (Atom)"
