"""Coverage report, printed every build.

Per docs/DECISIONS.md 0006 there is no separate league feed to join against
Ticketmaster, so "join hit-rate" is reinterpreted honestly as: of the teams
we queried, how many had at least one upcoming Ticketmaster listing. That
substitution is documented here and in the printed report, not hidden.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import League
from .normalize import Game, unique_by_event_id


@dataclass
class LeagueCoverage:
    league_slug: str
    league_name: str
    teams_configured: int
    teams_with_games: int
    games_total: int
    games_with_price: int
    games_date_tbd: int
    teams_truncated: list[str] = field(default_factory=list)
    teams_with_mismatched_events: list[str] = field(default_factory=list)

    @property
    def team_hit_rate(self) -> float:
        if self.teams_configured == 0:
            return 0.0
        return self.teams_with_games / self.teams_configured

    @property
    def price_coverage(self) -> float:
        if self.games_total == 0:
            return 0.0
        return self.games_with_price / self.games_total


@dataclass
class BuildCoverage:
    leagues: list[LeagueCoverage]
    requests_made: int
    bytes_received: int
    api_key_present: bool

    @property
    def leagues_examined(self) -> int:
        return len(self.leagues)

    @property
    def leagues_with_games(self) -> int:
        return sum(1 for lc in self.leagues if lc.games_total > 0)

    @property
    def games_total(self) -> int:
        return sum(lc.games_total for lc in self.leagues)

    @property
    def games_with_price_total(self) -> int:
        return sum(lc.games_with_price for lc in self.leagues)


def compute_league_coverage(
    league: League,
    games: list[Game],
    truncated_team_slugs: set[str],
    mismatched_team_slugs: set[str] | None = None,
) -> LeagueCoverage:
    teams_with_games = {g.tracked_team_slug for g in games}
    # Games are counted once per event; teams_with_games above still uses
    # every per-team record, since a head-to-head game counts for both teams.
    unique_games = unique_by_event_id(games)
    return LeagueCoverage(
        league_slug=league.slug,
        league_name=league.name,
        teams_configured=len(league.teams),
        teams_with_games=len(teams_with_games & {t.slug for t in league.teams}),
        games_total=len(unique_games),
        games_with_price=sum(1 for g in unique_games if g.price is not None),
        games_date_tbd=sum(1 for g in unique_games if g.date_tbd),
        teams_truncated=sorted(truncated_team_slugs),
        teams_with_mismatched_events=sorted(mismatched_team_slugs or set()),
    )


def render_report(coverage: BuildCoverage) -> str:
    lines = ["=== womens-sports-calendar coverage report ===", ""]
    if not coverage.api_key_present:
        lines.append(
            "TICKETMASTER_API_KEY not configured. Build proceeded in "
            "degraded mode: nothing was fetched, so every page says "
            "'not fetched' (never 'no games') and every calendar is empty "
            "with a not-fetched description. Fine for local/PR checks; the "
            "deploy workflow refuses to publish this (--require-api-key)."
        )
        lines.append("")

    lines.append(
        f"Leagues examined for licensing: 8. Leagues configured and "
        f"queried this build: {coverage.leagues_examined}. Leagues with "
        f"at least one game found: {coverage.leagues_with_games}."
    )
    lines.append(
        f"Games fetched: {coverage.games_total}. "
        f"Games with a Ticketmaster price: {coverage.games_with_price_total} "
        f"of {coverage.games_total}."
    )
    lines.append(f"Crawl budget used: {coverage.requests_made} requests, {coverage.bytes_received} bytes received.")
    lines.append("")

    for lc in coverage.leagues:
        lines.append(f"-- {lc.league_name} ({lc.league_slug}) --")
        lines.append(
            f"  teams configured: {lc.teams_configured}; "
            f"teams with >=1 game: {lc.teams_with_games} "
            f"(team hit-rate {lc.team_hit_rate:.0%})"
        )
        lines.append(
            f"  games: {lc.games_total}; with price: {lc.games_with_price} "
            f"({lc.price_coverage:.0%}); date TBD (excluded from .ics): "
            f"{lc.games_date_tbd}"
        )
        if lc.teams_truncated:
            lines.append(
                f"  WARNING: possibly-incomplete (Discovery API reported "
                f"more than one page) for: {', '.join(lc.teams_truncated)}"
            )
        if lc.teams_with_mismatched_events:
            lines.append(
                f"  NOTE: excluded >=1 Discovery API keyword-search result "
                f"that did not actually name the team (a false-positive "
                f"match, e.g. wrong sport/wrong team at the same venue or "
                f"city) for: {', '.join(lc.teams_with_mismatched_events)}"
            )
        lines.append("")

    return "\n".join(lines)
