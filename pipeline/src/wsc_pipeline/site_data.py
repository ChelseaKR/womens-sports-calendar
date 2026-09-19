"""Compact JSON the site renders from. One dict shape, reused for the
league-level and team-level pages. Absence discipline lives here once so
every consumer (HTML generator, tests) sees the same rule. The site shows
no prices (DECISIONS 0013), so no price is published here either. A game's
`buy` key is present and either the one ticket link (sellers.buy_link) or
null when there is nowhere to buy. It is never a guessed URL.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from .config import League, Team
from .normalize import Game, display_start, local_start, team_is_participant_as_any, unique_by_event_id
from .sellers import buy_link

# Ticketmaster dates.status.code values that mean the listed date is not
# simply going ahead. Shown next to the date on the page and, in the
# structured data, as eventStatus; any other code (onsale, offsale) states
# nothing about whether the game is on, so it is not shown as a status.
NOTABLE_STATUSES = {
    "cancelled": "Cancelled",
    "canceled": "Cancelled",
    "postponed": "Postponed",
    "rescheduled": "Rescheduled",
}


def game_to_dict(game: Game) -> dict[str, Any]:
    start = local_start(game)
    data = {
        "event_id": game.event_id,
        # Ticketmaster's own event name -- what the page shows when home/away
        # could not be split out of it, instead of "TBD vs TBD".
        "event_name": game.raw_event_name or None,
        "home_team": game.home_team,
        "away_team": game.away_team,
        "venue_name": game.venue_name,
        "venue_city": game.venue_city,
        "venue_state": game.venue_state,
        "start_display": display_start(game),
        "start_utc": game.start_utc.isoformat() if game.start_utc else None,
        # ISO date only (no time), for rendering -- e.g. a big "JUN 15"
        # date-chip -- without the HTML layer re-parsing start_display's
        # human-readable string. None exactly when there is no real local
        # date (same "date TBD" case start_display already handles).
        "start_local_date": game.start_local_date.isoformat() if game.start_local_date else None,
        "tzid": game.tzid,
        "date_tbd": game.date_tbd,
        "time_tba": game.time_tba,
        # The exact start in the venue's time zone with its UTC offset
        # ("2026-09-20T18:00:00-07:00"), or None unless the date, the time
        # and the zone are all published (normalize.local_start). The only
        # start time the structured data and <time datetime> ever use.
        "start_local_datetime": start.isoformat(timespec="seconds") if start else None,
        "in_calendar_feed": bool(game.start_utc is not None and not game.date_tbd),
        # Whether home_team/away_team are known to be in that order (the
        # event name said so), rather than just the two teams involved.
        "home_away_known": game.home_away_known,
        # Street, postcode and country for the structured-data address.
        "venue_street": game.venue_street,
        "venue_postal_code": game.venue_postal_code,
        "venue_country": game.venue_country,
        # "Cancelled" / "Postponed" / "Rescheduled" when Ticketmaster says
        # so, else None (see NOTABLE_STATUSES).
        "status": NOTABLE_STATUSES.get(game.status_code or ""),
        # The Ticketmaster event URL, the same one the .ics feeds carry.
        "ticket_url": game.ticket_url,
        # Where the page's "Buy tickets" link goes: the home team's primary
        # seller where known, else the event URL (see sellers.py).
        "buy": buy_link(game),
    }
    # Additive keys, present only when the event name carried them, so every
    # game without one is published byte for byte as before. Neither is part
    # of a team name: the title is what sat in front of the first team ("McBride
    # Homes Braggin' Rights"), the game type what followed the matchup
    # ("Exhibition", "Game 2").
    if game.event_title:
        data["event_title"] = game.event_title
    if game.game_type:
        data["game_type"] = game.game_type
    return data


def team_data(
    team: Team,
    league: League,
    games: list[Game],
    *,
    fetched: bool = True,
    possibly_incomplete: bool = False,
) -> dict[str, Any]:
    """`fetched` is False when this build never queried Ticketmaster (no
    API key): an empty `games` list then means "not checked", never "no
    games", and every consumer must say so. `possibly_incomplete` is True
    when Ticketmaster had more result pages than the client reads."""
    team_games = sorted((g for g in games if g.tracked_team_slug == team.slug), key=_sort_key)
    game_dicts = []
    for g in team_games:
        d = game_to_dict(g)
        d["tracked_team_is_home"] = tracked_team_is_home(team, g)
        game_dicts.append(d)
    next_home = next(
        (d for d in game_dicts if d["tracked_team_is_home"] is True and d["status"] != "Cancelled"),
        None,
    )
    return {
        "team_slug": team.slug,
        "team_name": team.shown_name,
        "league_slug": league.slug,
        "league_name": league.name,
        "schedule_source_used": league.schedule_source_used,
        "schedule_source_note": league.schedule_source_note,
        "sport": league.sport,
        "organization_name": league.organization_name,
        "fetched": fetched,
        "possibly_incomplete": possibly_incomplete,
        "season": season_label(team_games) if fetched else None,
        # The event_id of the soonest listed home game, or None when no
        # listed game is known to be at home.
        "next_home_event_id": next_home["event_id"] if next_home else None,
        "games": game_dicts,
    }


def tracked_team_is_home(team: Team, game: Game) -> bool | None:
    """True/False when the event name says who is at home and one side is
    this team; None when that is not known (the teams came from Ticketmaster's
    attraction list, or neither parsed side is this team). Never guessed
    from the venue or the city."""
    if not game.home_away_known or not game.home_team or not game.away_team:
        return None
    if team_is_participant_as_any(team.all_names, {"name": game.home_team}, team.not_this_team):
        return True
    if team_is_participant_as_any(team.all_names, {"name": game.away_team}, team.not_this_team):
        return False
    return None


def season_label(games: list[Game]) -> str | None:
    """The season the listed games span, from their real dates: "2026" when
    they all fall in one year, "2026-27" across two, "2026-2028" wider. None
    when no listed game has a real date -- a year is never assumed."""
    years = sorted({g.start_local_date.year for g in games if g.start_local_date and not g.date_tbd})
    if not years:
        return None
    first, last = years[0], years[-1]
    if first == last:
        return str(first)
    if last == first + 1:
        return f"{first}-{last % 100:02d}"
    return f"{first}-{last}"


def league_data(
    league: League,
    games: list[Game],
    *,
    fetched: bool = True,
    possibly_incomplete_teams: set[str] | frozenset[str] = frozenset(),
) -> dict[str, Any]:
    # Once per event: a game between two tracked teams arrives as one Game
    # per team's search (see normalize.unique_by_event_id).
    league_games = unique_by_event_id(g for g in games if g.league_slug == league.slug)
    return {
        "league_slug": league.slug,
        "league_name": league.name,
        "season": season_label(league_games) if fetched else None,
        "sport": league.sport,
        "schedule_source_used": league.schedule_source_used,
        "schedule_source_note": league.schedule_source_note,
        "fetched": fetched,
        "possibly_incomplete_teams": sorted(possibly_incomplete_teams),
        "teams": [t.slug for t in league.teams],
        "team_names": {t.slug: t.shown_name for t in league.teams},
        "games": [game_to_dict(g) for g in sorted(league_games, key=_sort_key)],
    }


def _sort_key(game: Game) -> tuple[bool, bool, date | None, bool, datetime | None, str]:
    """Soonest first by the local date, then by the start instant: a
    time-TBA game sits among the games of its own date (after the timed
    ones), not after every timed game in the season. Date-TBD games last.
    The event id breaks ties, so the order (and the page's sitemap
    fingerprint) does not depend on the order Ticketmaster answered in."""
    return (
        game.date_tbd,
        game.start_local_date is None,
        game.start_local_date,
        game.start_utc is None,
        game.start_utc,
        game.event_id,
    )


def site_summary(
    leagues: list[League],
    games_by_league: dict[str, list[Game]],
    *,
    api_key_present: bool,
    not_included: list[dict[str, str]],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    return {
        "generated_at": generated_at.isoformat(),
        "api_key_present": api_key_present,
        "leagues": [
            {
                "slug": lg.slug,
                "name": lg.name,
                # null, not 0, when nothing was fetched (see team_data).
                "games_count": len(unique_by_event_id(games_by_league.get(lg.slug, []))) if api_key_present else None,
                "schedule_source_used": lg.schedule_source_used,
            }
            for lg in leagues
        ],
        "leagues_examined_not_included": not_included,
    }


# The one data source (docs/data/ticketmaster-discovery-api.md).
SOURCE_ID = "ticketmaster-discovery-api"


def provenance(fetched_at: datetime | None) -> dict[str, str | None]:
    """Source and machine-readable fetch time for every published data file
    and page payload (DATA-GOVERNANCE-STANDARD DG-02). `fetched_at` is null
    when the build fetched nothing -- never a made-up time."""
    return {"source": SOURCE_ID, "fetched_at": fetched_at.isoformat() if fetched_at else None}
