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
  team's game time;
- a listing that names another sport than the league's (football, baseball,
  volleyball and so on) is dropped (`_other_sport_reason`), with one
  exception: when the tracked team's own side names the league's sport and
  only the opponent's side ends in another sport's word, it is the team's
  game with a mislabeled opponent, and it stays with that one word taken off
  the opponent's name (`fix_opponent_sport`). "Texas Longhorns Womens
  Basketball vs Northern Colorado Bears Football" (Z7r9jZ1AAZSFK, Nov 7 at
  Moody Center ATX) was Texas's next home game on Nov 5, and the page said
  it was "against Northern Colorado Bears Football"; texaslonghorns.com
  lists that game as women's basketball vs Northern Colorado, Nov 7 at 7 PM
  CT at Moody Center. The page and the feed now say "Northern Colorado
  Bears", and COVERAGE.txt names the listing.

Ticketmaster's `classifications` were not used: their values for these
listings have not been read from a live response (DECISIONS 0009 declined
to guess them for the same reason), and the event name carried every case
measured.

Only whole listings are dropped, and a relabeled listing keeps its event id,
so every game that stays keeps its calendar UID (ics.make_uid): subscribers
get no duplicates.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace

from . import config
from .config import Team
from .normalize import (
    Game,
    _normalize_for_match,
    parse_event_name,
    side_begins_with,
    side_names_college_team,
    team_is_participant_as_any,
)

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

# Each league sport's own word, and the words of every other sport a school
# or a city's teams play, as whole words on the normalized name. A soccer
# league's "football" is its own sport ("Football Club"), so it is never
# another sport's word there; elsewhere "Football Club" is still soccer.
_SPORT_WORDS: dict[str, str] = {
    "basketball": r"basketball",
    "soccer": r"soccer",
    "ice hockey": r"hockey",
    "softball": r"softball",
}
_OTHER_SPORT_WORDS: tuple[str, ...] = (
    r"football(?! club)",
    r"baseball",
    r"volleyball",
    r"lacrosse",
    r"wrestling",
    r"gymnastics",
    *_SPORT_WORDS.values(),
)


def _sport_word(league_slug: str) -> str | None:
    """The league's own sport word (a regex), or None when the league states
    no sport this module knows: then no other-sport rule applies."""
    try:
        sport = config.league_by_slug(league_slug).sport
    except KeyError:
        return None
    return _SPORT_WORDS.get(sport.lower())


def _other_sport(league_slug: str) -> re.Pattern[str] | None:
    """Whole words of every sport but the league's, or None (see
    _sport_word)."""
    own = _sport_word(league_slug)
    if own is None:
        return None
    others = [w for w in _OTHER_SPORT_WORDS if w != own and not (own == "soccer" and w.startswith("football"))]
    return re.compile(r"\b(?:" + "|".join(others) + r")\b")


def side_is_team(team: Team, side: str) -> bool:
    """True if one side of a matchup names this team: by any of its search
    names, as its school's women's basketball under another of
    Ticketmaster's spellings (normalize.side_names_college_team: "Penn State
    Lady Lion Basketball vs. Rutgers" is a Penn State home game), or by its
    title name at the start of the side. The build accepts
    a game through the title name (Team.match_names), as in "Nebraska Women's
    Basketball vs San Jose State" (live 2026-11-02), so the home flag must
    read it too. Only at the start: "Western Michigan Women's Basketball" is
    not Michigan."""
    if team_is_participant_as_any(team.all_names, {"name": side}, team.not_this_team):
        return True
    if team.school is not None and side_names_college_team(team.school, team.mascots, side):
        return True
    return team.title_name is not None and side_begins_with(team.title_name, side)


def _tracked_team(game: Game) -> Team | None:
    try:
        league = config.league_by_slug(game.league_slug)
    except KeyError:
        return None
    return next((t for t in league.teams if t.slug == game.tracked_team_slug), None)


def _sides(game: Game) -> tuple[str, str] | None:
    """(tracked team's side, opponent's side), or None when the listing has
    no two sides or neither (or both) of them is the tracked team."""
    team = _tracked_team(game)
    if team is None or not game.home_team or not game.away_team:
        return None
    home, away = side_is_team(team, game.home_team), side_is_team(team, game.away_team)
    if home and not away:
        return game.home_team, game.away_team
    if away and not home:
        return game.away_team, game.home_team
    return None


def _trailing_other_sport(side: str, other: re.Pattern[str]) -> str | None:
    """The side without its last word, when that last word (and only it)
    names another sport ("Northern Colorado Bears Football" is "Northern
    Colorado Bears"); else None."""
    words = side.split()
    if len(words) < 2 or not other.fullmatch(_normalize_for_match(words[-1])):
        return None
    rest = " ".join(words[:-1]).rstrip(" -:,")
    if not rest or other.search(_normalize_for_match(rest)):
        return None
    return rest


def _other_sport_reason(game: Game) -> str | None:
    """Why a listing is another sport's event and not one of the team's
    games, else None. Kept (None) only when no side names another sport, or
    when the tracked team's own side names the league's sport and the
    opponent's side ends in another sport's word (fix_opponent_sport then
    takes that word off)."""
    other = _other_sport(game.league_slug)
    own = _sport_word(game.league_slug)
    if other is None or own is None:
        return None
    name = _normalize_for_match(game.raw_event_name or "")
    sides = [s for s in (game.home_team, game.away_team) if s]
    if not sides:
        if other.search(name) and not re.search(rf"\b{own}\b", name):
            return "names another sport"
        return None
    if not any(other.search(_normalize_for_match(s)) for s in sides) and not other.search(name):
        return None
    if _opponent_fix(game) is not None:
        return None
    return "names another sport"


def _opponent_fix(game: Game) -> tuple[str, str] | None:
    """(opponent's side as listed, the side without the other sport's word)
    when only the opponent's side is mislabeled (see _other_sport_reason),
    else None."""
    other = _other_sport(game.league_slug)
    own = _sport_word(game.league_slug)
    pair = _sides(game)
    if other is None or own is None or pair is None:
        return None
    tracked, opponent = pair
    tracked_norm = _normalize_for_match(tracked)
    if other.search(tracked_norm) or not re.search(rf"\b{own}\b", tracked_norm):
        return None
    fixed = _trailing_other_sport(opponent, other)
    raw = game.raw_event_name or ""
    if fixed is None or opponent not in raw:
        return None
    # Nothing else in the name may name another sport.
    if other.search(_normalize_for_match(raw.replace(opponent, fixed, 1))):
        return None
    return opponent, fixed


@dataclass(frozen=True)
class RelabeledListing:
    """One team's listing whose opponent's name had another sport's word
    taken off (for COVERAGE.txt)."""

    league_slug: str
    team_slug: str
    event_id: str
    event_name: str
    opponent_shown: str

    def describe(self) -> str:
        return f"{self.team_slug}: {self.event_id} ({self.event_name}): opponent shown as {self.opponent_shown!r}"


def fix_opponent_sport(games: Iterable[Game]) -> tuple[list[Game], list[RelabeledListing]]:
    """(games, relabeled): `games`, order kept, with each mislabeled
    opponent's other-sport word taken off its side and the event name (see
    the module docstring). Every other game is returned unchanged."""
    out: list[Game] = []
    relabeled: list[RelabeledListing] = []
    for g in games:
        fix = _opponent_fix(g)
        if fix is None:
            out.append(g)
            continue
        listed, shown = fix
        out.append(
            replace(
                g,
                home_team=shown if g.home_team == listed else g.home_team,
                away_team=shown if g.away_team == listed else g.away_team,
                raw_event_name=g.raw_event_name.replace(listed, shown, 1),
            )
        )
        relabeled.append(RelabeledListing(g.league_slug, g.tracked_team_slug, g.event_id, g.raw_event_name, shown))
    return out, relabeled


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
    return _other_sport_reason(game)


def _names_mens_team(game: Game) -> bool:
    """True when a side of the name's matchup is a men's team, or, for a name
    with no matchup, the name says men's and never women's (so a "Men's and
    Women's Doubleheader" stays)."""
    if game.home_away_known:
        sides = [s for s in (game.home_team, game.away_team) if s]
        return any(_MENS.search(_normalize_for_match(s)) for s in sides)
    name = _normalize_for_match(game.raw_event_name or "")
    return bool(_MENS.search(name)) and not _WOMENS.search(name)


def name_says_not_a_game(name: str) -> str | None:
    """Why a listing's name alone says it is not a team's game (a ticket
    product, or a matchup naming a men's team), else None: the name rules of
    only_games for an event that is known only by its name, such as a played
    game a feed keeps (history.py). The doubleheader rule needs the team's
    other listings and is not applied."""
    normalized = _normalize_for_match(name)
    if NON_GAME_PRODUCT.search(normalized):
        return "a ticket product, not a game"
    matchup = parse_event_name(name, [])
    if matchup.home_away_known:
        sides = [s for s in (matchup.home, matchup.away) if s]
        if any(_MENS.search(_normalize_for_match(s)) for s in sides):
            return "names a men's team"
    elif _MENS.search(normalized) and not _WOMENS.search(normalized):
        return "names a men's team"
    return None


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
