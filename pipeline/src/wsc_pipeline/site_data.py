"""Compact JSON the site renders from. One dict shape, reused for the
league-level and team-level pages. Absence discipline lives here once so
every consumer (HTML generator, tests) sees the same rule. The site shows
no prices (DECISIONS 0013), so no price is published here either. A game's
`buy` key is present and either the one ticket link (sellers.buy_link) or
null when there is nowhere to buy. It is never a guessed URL.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from .config import League, Team
from .normalize import Game, display_start, unique_by_event_id
from .sellers import buy_link


def game_to_dict(game: Game) -> dict:
    return {
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
        "in_calendar_feed": bool(game.start_utc is not None and not game.date_tbd),
        # The Ticketmaster event URL, the same one the .ics feeds carry.
        "ticket_url": game.ticket_url,
        # Where the page's "Buy tickets" link goes: the home team's primary
        # seller where known, else the event URL (see sellers.py).
        "buy": buy_link(game),
    }


def team_data(
    team: Team,
    league: League,
    games: list[Game],
    *,
    fetched: bool = True,
    possibly_incomplete: bool = False,
) -> dict:
    """`fetched` is False when this build never queried Ticketmaster (no
    API key): an empty `games` list then means "not checked", never "no
    games", and every consumer must say so. `possibly_incomplete` is True
    when Ticketmaster had more result pages than the client reads."""
    team_games = [g for g in games if g.tracked_team_slug == team.slug]
    return {
        "team_slug": team.slug,
        "team_name": team.name,
        "league_slug": league.slug,
        "league_name": league.name,
        "schedule_source_used": league.schedule_source_used,
        "schedule_source_note": league.schedule_source_note,
        "fetched": fetched,
        "possibly_incomplete": possibly_incomplete,
        "games": [game_to_dict(g) for g in sorted(team_games, key=_sort_key)],
    }


def league_data(
    league: League,
    games: list[Game],
    *,
    fetched: bool = True,
    possibly_incomplete_teams: set[str] | frozenset[str] = frozenset(),
) -> dict:
    # Once per event: a game between two tracked teams arrives as one Game
    # per team's search (see normalize.unique_by_event_id).
    league_games = unique_by_event_id(g for g in games if g.league_slug == league.slug)
    return {
        "league_slug": league.slug,
        "league_name": league.name,
        "schedule_source_used": league.schedule_source_used,
        "schedule_source_note": league.schedule_source_note,
        "fetched": fetched,
        "possibly_incomplete_teams": sorted(possibly_incomplete_teams),
        "teams": [t.slug for t in league.teams],
        "team_names": {t.slug: t.name for t in league.teams},
        "games": [game_to_dict(g) for g in sorted(league_games, key=_sort_key)],
    }


def _sort_key(game: Game):
    return (game.date_tbd, game.start_utc is None, game.start_utc, game.start_local_date)


def site_summary(
    leagues: list[League],
    games_by_league: dict[str, list[Game]],
    *,
    api_key_present: bool,
    not_included: list[dict[str, str]],
    generated_at: datetime | None = None,
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc)
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
