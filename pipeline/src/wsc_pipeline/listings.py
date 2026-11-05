"""Which Ticketmaster listings are games, and what an event listing's start
time means.

Three kinds of listing reached team pages and calendars as if each were one
game (the 2026-11-05 quality audit, measured on the live build):

- **Not a game at all.** "Tennessee Volunteers Women's Basketball Season
  Tickets" (event G5viZ_KhLQpM1), dated Sep 21 at 11:59 PM, was the first
  row of Tennessee's "Upcoming games" on Nov 5. Ticketmaster sells season
  tickets, parking, suites and passes as events with a date; nothing about
  them is a game a fan can put in a calendar.
- **A men's game.** "Pittsburgh Panthers Mens Basketball vs. Penn State
  Nittany Lions Womens Basketball" (Z7r9jZ1A7JFAp, Nov 8 at the Palestra)
  was Penn State's next game. Ticketmaster's listing names the women's team
  on one side, so the participant check accepted it; Penn State's own
  schedule has no Nov 8 game. Every tracked league is a women's league.
- **A multi-game event.** "MarketBeat Invitational Women's Basketball"
  (vvG1bZ_C-7KX6i) starts at 1:00 PM CT, Minnesota and Kansas State's slot;
  Nebraska plays Kansas at 3:30. "The Bad Boys Mower Series: Women's College
  Basketball Doubleheader" (G5viZ_58LMXYN) starts at 5:00 PM CT, Tennessee
  and Baylor's slot, and sat on Vanderbilt's page beside Vanderbilt's own
  listing for the same night ("Vanderbilt Commodores Womens Basketball vs.
  Belmont Bruins Womens", Z7r9jZ1A7Pvqv). Such an event's name has no "A vs
  B" matchup, so its start is the event's, not any one team's game.

The rules are general ones about the listing, never a list of event ids:

- a listing whose name says it is a ticket product (NON_GAME_PRODUCT) is
  dropped;
- a listing that names a men's team is dropped (`_names_mens_team`);
- an event listing with no matchup in its name is dropped from a team's
  page and feed when the same team has its own matchup listing at the same
  venue on the same local date, which is the same game listed twice; that
  matchup listing (with its own time, or "time TBA") is kept;
- any other event listing with no matchup stays, and its start is labeled as
  the event's start (EVENT_START_SUFFIX, EVENT_START_NOTE), never as the
  team's game time.

Ticketmaster's `classifications` were not used: their values for these
listings have not been read from a live response (DECISIONS 0009 declined
to guess them for the same reason), and the event name carried every case
measured.

Only whole listings are dropped, so every game that stays keeps its event id
and therefore its calendar UID (ics.make_uid): subscribers get no
duplicates.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .normalize import Game, _normalize_for_match

# What a ticket product's name says. Matched as whole words on the
# normalized name (apostrophes dropped, punctuation a space).
NON_GAME_PRODUCT = re.compile(
    r"\b(?:season tickets?|ticket plans?|mini plans?|flex plans?|parking|suites?|deposits?|packages?"
    r"|passes|pass|memberships?|gift cards?)\b"
)
# A men's team, as a whole word once normalized: "Men's" and "Mens" are both
# "mens"; "Womens" is a different word.
_MENS = re.compile(r"\b(?:mens|men)\b")
_WOMENS = re.compile(r"\b(?:womens|women|lady)\b")

# What a timed event listing with no matchup says in its calendar SUMMARY and
# on the page, after the time, and the first line of its calendar
# DESCRIPTION. American English, like every visible string.
EVENT_START_SUFFIX = " (event start; game time not listed)"
EVENT_START_NOTE = (
    "Event start: this Ticketmaster listing is an event that does not name a single matchup, such as a "
    "doubleheader or a showcase. The time is when the event starts; Ticketmaster does not list when this "
    "team's game starts."
)


@dataclass(frozen=True)
class DroppedListing:
    """One team's listing the build left out, and why (for COVERAGE.txt)."""

    league_slug: str
    team_slug: str
    event_id: str
    event_name: str
    reason: str

    def describe(self) -> str:
        return f"{self.team_slug}: {self.event_id} ({self.event_name}): {self.reason}"


def is_event_listing(game: Game) -> bool:
    """True when the listing's own name gives no "A vs B" matchup (a
    doubleheader, a showcase, a tournament "at <venue>"): its start is the
    event's start, not one team's game time. home_away_known is set only by
    a matchup in the name (normalize.parse_event_name)."""
    return not game.home_away_known


def event_start_only(game: Game) -> bool:
    """True when the page and the calendar must say that the time shown is
    the event's start: a timed event listing. An event listing with no
    announced time is already "(time TBA)" and claims no time."""
    return is_event_listing(game) and game.start_utc is not None and not game.time_tba and not game.date_tbd


def _non_game_reason(game: Game) -> str | None:
    name = _normalize_for_match(game.raw_event_name or "")
    if NON_GAME_PRODUCT.search(name):
        return "a ticket product, not a game"
    if _names_mens_team(game):
        return "names a men's team"
    return None


def _names_mens_team(game: Game) -> bool:
    """True when a side of the name's matchup is a men's team, or, for a name
    with no matchup, the name says men's and never women's (so a "Men's and
    Women's Doubleheader" stays)."""
    if game.home_away_known:
        sides = [s for s in (game.home_team, game.away_team) if s]
        return any(_MENS.search(_normalize_for_match(s)) for s in sides)
    name = _normalize_for_match(game.raw_event_name or "")
    return bool(_MENS.search(name)) and not _WOMENS.search(name)


def _venue_key(game: Game) -> str | None:
    return _normalize_for_match(game.venue_name) if game.venue_name else None


def only_games(games: Iterable[Game]) -> tuple[list[Game], list[DroppedListing]]:
    """(kept, dropped): `games` without the listings that are not one of the
    team's games (see the module docstring), order kept."""
    games = list(games)
    dropped: list[DroppedListing] = []
    kept: list[Game] = []
    for g in games:
        reason = _non_game_reason(g)
        if reason:
            dropped.append(DroppedListing(g.league_slug, g.tracked_team_slug, g.event_id, g.raw_event_name, reason))
        else:
            kept.append(g)
    # (league, team, local date, venue) of every matchup listing a team has.
    has_matchup = {
        (g.league_slug, g.tracked_team_slug, g.start_local_date, _venue_key(g))
        for g in kept
        if not is_event_listing(g) and g.start_local_date is not None and g.venue_name
    }
    out: list[Game] = []
    for g in kept:
        key = (g.league_slug, g.tracked_team_slug, g.start_local_date, _venue_key(g))
        if is_event_listing(g) and g.venue_name and g.start_local_date is not None and key in has_matchup:
            dropped.append(
                DroppedListing(
                    g.league_slug,
                    g.tracked_team_slug,
                    g.event_id,
                    g.raw_event_name,
                    "an event listing for a game the team's own listing already covers",
                )
            )
            continue
        out.append(g)
    return out, dropped
