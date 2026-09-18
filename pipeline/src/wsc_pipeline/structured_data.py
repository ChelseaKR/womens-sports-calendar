"""schema.org JSON-LD for the pages: SportsEvent, SportsTeam, BreadcrumbList
and WebSite.

Everything here is built from the same page payload the visible HTML is
rendered from (site_data.py), so the markup can only say what the page
says. The rules, each one checked again on the built site by
validate_seo.py:

- A SportsEvent is emitted only for a listed game whose date AND time are
  both published, with the venue's UTC offset (normalize.local_start):
  never for a date-TBD or time-TBA game, and never with a start time filled
  in. Those games stay visible on the page as "Date TBD" or "(time TBA)"
  and are simply not marked up.
- homeTeam and awayTeam are set only when the event name says which side is
  at home ("Home vs Away", "Away at Home"). A listing whose two teams are
  not known in that order, or that is not a two-team game at all (a
  "Premium Experiences" package), gets no SportsEvent. A team's name drops
  a trailing theme-night parenthetical ("Chicago Sky (HBCU + D9 Night)").
- location is the venue's name and postal address as Ticketmaster
  publishes it; a game with no venue name, city and region is not marked
  up (Google requires location.name and location.address).
- eventStatus appears only when Ticketmaster says the game is cancelled,
  postponed or rescheduled -- and the page shows that word next to the
  date. Otherwise it is left out, which Google reads as "scheduled".
- A build that did not fetch (payload "fetched" false) emits no events.

Google's event rich result currently supports only pages that focus on one
event (developers.google.com/search/docs/appearance/structured-data/event,
updated 2026-09-08); these are league and team schedule pages, so the
events are valid schema.org and pass the Event property rules, but are not
expected to earn the event rich result.

The JSON is written into a <script type="application/ld+json"> data block,
which browsers never execute. "<", ">" and "&" are written as \\u escapes, so
no string from Ticketmaster can close the block or open a tag.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

CONTEXT = "https://schema.org"
OFFLINE = "https://schema.org/OfflineEventAttendanceMode"
FEMALE = "https://schema.org/Female"
# A theme-night suffix Ticketmaster appends to a team in an event name,
# e.g. "Chicago Sky (HBCU + D9 Night)" (seen live 2026-09-18). Google asks
# that an event's name carry no promotional text, and the team is the team.
_TRAILING_PARENTHETICAL = re.compile(r"\s*\([^()]*\)\s*$")
# site_data.NOTABLE_STATUSES label -> schema.org EventStatusType.
EVENT_STATUS = {
    "Cancelled": "https://schema.org/EventCancelled",
    "Postponed": "https://schema.org/EventPostponed",
    "Rescheduled": "https://schema.org/EventRescheduled",
}


def script_block(nodes: list[dict[str, Any]]) -> str:
    """One JSON-LD <script> holding every node as an @graph, or "" when
    there is nothing to say."""
    if not nodes:
        return ""
    doc = {"@context": CONTEXT, "@graph": nodes}
    text = json.dumps(doc, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
    text = text.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    return f'<script type="application/ld+json">{text}</script>\n'


def website(*, name: str, base_url: str) -> dict[str, Any]:
    """The home page's WebSite node: the site's name, for search results'
    site-name line."""
    return {"@type": "WebSite", "@id": f"{base_url}/#website", "name": name, "url": f"{base_url}/"}


def breadcrumbs(trail: list[tuple[str, str]]) -> dict[str, Any]:
    """BreadcrumbList from (name, absolute URL) pairs, matching the page's
    visible breadcrumb trail."""
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i, "name": name, "item": url}
            for i, (name, url) in enumerate(trail, start=1)
        ],
    }


def sports_team(*, name: str, page_url: str, sport: str, organization: str) -> dict[str, Any]:
    """The team a team page is about. Only facts the site holds: the name
    Ticketmaster lists it under, its sport, that it is a women's team, and
    the league or conference it plays in."""
    node: dict[str, Any] = {
        "@type": "SportsTeam",
        "@id": f"{page_url}#team",
        "name": name,
        "gender": FEMALE,
    }
    if sport:
        node["sport"] = sport
    if organization:
        node["memberOf"] = {"@type": "SportsOrganization", "name": organization}
    return node


def event_eligible(game: Mapping[str, Any]) -> bool:
    """True only when every fact a SportsEvent states is published."""
    return bool(
        game.get("start_local_datetime")
        and not game.get("date_tbd")
        and not game.get("time_tba")
        and game.get("in_calendar_feed")
        and game.get("home_away_known")
        and game.get("home_team")
        and game.get("away_team")
        and game.get("venue_name")
        and game.get("venue_city")
        and (game.get("venue_state") or game.get("venue_country"))
    )


def team_label(name: str) -> str:
    """The team's name without a trailing theme-night parenthetical."""
    return _TRAILING_PARENTHETICAL.sub("", name).strip() or name


def event_name(game: Mapping[str, Any]) -> str:
    return f"{team_label(game['home_team'])} vs {team_label(game['away_team'])}"


def sports_event(game: Mapping[str, Any], *, sport: str) -> dict[str, Any] | None:
    """The SportsEvent for one listed game, or None when it is not eligible
    (see event_eligible and the module docstring)."""
    if not event_eligible(game):
        return None
    address: dict[str, Any] = {"@type": "PostalAddress"}
    for key, field in (
        ("streetAddress", "venue_street"),
        ("addressLocality", "venue_city"),
        ("addressRegion", "venue_state"),
        ("postalCode", "venue_postal_code"),
        ("addressCountry", "venue_country"),
    ):
        if game.get(field):
            address[key] = game[field]
    node: dict[str, Any] = {
        "@type": "SportsEvent",
        "name": event_name(game),
        "startDate": game["start_local_datetime"],
        "eventAttendanceMode": OFFLINE,
        "location": {"@type": "Place", "name": game["venue_name"], "address": address},
        "homeTeam": {"@type": "SportsTeam", "name": team_label(game["home_team"])},
        "awayTeam": {"@type": "SportsTeam", "name": team_label(game["away_team"])},
    }
    if sport:
        node["sport"] = sport
    status = EVENT_STATUS.get(game.get("status") or "")
    if status:
        node["eventStatus"] = status
    return node


def sports_events(games: list[Mapping[str, Any]], *, sport: str, fetched: bool) -> list[dict[str, Any]]:
    """Every eligible game's SportsEvent, in page order, once per game: two
    Ticketmaster listings of the same teams at the same instant are one
    event. None when the build did not fetch."""
    if not fetched:
        return []
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for game in games:
        node = sports_event(game, sport=sport)
        if node is None or (node["name"], node["startDate"]) in seen:
            continue
        seen.add((node["name"], node["startDate"]))
        out.append(node)
    return out
