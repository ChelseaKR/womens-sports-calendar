"""Compact JSON the site renders from. One dict shape, reused for the
league-level and team-level pages. Absence discipline lives here once so
every consumer (HTML generator, tests) sees the same rule: a game's price
key is present and non-null only when Ticketmaster published a price range
for that specific event -- never omitted-but-implied, never zero.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from .config import League, Team
from .normalize import Game, display_start


def game_to_dict(game: Game) -> dict:
    return {
        "event_id": game.event_id,
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
        "price": (
            {
                "currency": game.price.currency,
                "min": game.price.min,
                "max": game.price.max,
            }
            if game.price is not None
            else None
        ),
        "ticket_url": game.ticket_url,
    }


def team_data(team: Team, league: League, games: list[Game]) -> dict:
    team_games = [g for g in games if g.tracked_team_slug == team.slug]
    return {
        "team_slug": team.slug,
        "team_name": team.name,
        "league_slug": league.slug,
        "league_name": league.name,
        "schedule_source_used": league.schedule_source_used,
        "schedule_source_note": league.schedule_source_note,
        "games": [game_to_dict(g) for g in sorted(team_games, key=_sort_key)],
    }


def league_data(league: League, games: list[Game]) -> dict:
    league_games = [g for g in games if g.league_slug == league.slug]
    return {
        "league_slug": league.slug,
        "league_name": league.name,
        "schedule_source_used": league.schedule_source_used,
        "schedule_source_note": league.schedule_source_note,
        "teams": [t.slug for t in league.teams],
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
                "games_count": len(games_by_league.get(lg.slug, [])),
                "schedule_source_used": lg.schedule_source_used,
            }
            for lg in leagues
        ],
        "leagues_examined_not_included": not_included,
    }
