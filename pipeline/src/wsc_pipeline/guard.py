"""Refuse to publish a build that would take games out of subscribers' calendars.

The build used to refuse only when a fetch errored, or when every tracked team
across every league came back empty at once. If one league, or one team,
quietly came back with none of its games (a renamed team, a keyword that stops
matching, a change in how Ticketmaster catalogs a team's events), the build
succeeded and published an empty page and an empty feed for it, and a
subscriber's calendar app mirrored that at its next refresh.

This module compares a build with what the live site published last, the way
sitemap.py already does for <lastmod>: the site is stateless, so the only
record of the previous publish is the live site itself, read team by team from
data/<league>/<team>.json. The thresholds and the per-league override live in
config.py (PUBLISH_GUARD, PUBLISH_GUARD_OVERRIDES); the decision and its
trade-offs are docs/adr/0006.

What counts as a vanished game (all must hold):

- the previous publish listed it, and it was in that publish's calendar feed
  (a real date and instant, not date-TBD);
- it was to start more than `settle_hours` after this build. A game that has
  started and left Ticketmaster's listing since last night is the normal end
  of a game, so a season that ends, or an off-season league, vanishes
  nothing, and no season calendar is needed;
- the previous publish had not marked it cancelled or postponed (removal of a
  listing is what those look like);
- this build no longer lists it (a game still listed but now cancelled is not
  vanished: it is reported as a change instead).

A refusal raises PublishRefused and the build writes nothing, so the last good
deploy stays live. An unreadable previous publish never blocks (the same
fail-open as sitemap.fetch_previous_state), but it is reported, in the run log
and in COVERAGE.txt, rather than skipped silently.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

import httpx

from . import config
from .normalize import Game
from .site_data import NOTABLE_STATUSES
from .ticketmaster import USER_AGENT

# What the previous publish says about a game that is not simply going ahead.
# Removal of a listing is what a cancelled or postponed game looks like.
_EXPECTED_TO_LEAVE = frozenset({"Cancelled", "Postponed"})
# Consecutive requests that fail at the transport level before the rest of the
# previous publish is not even tried (a site that is down is 67 timeouts).
_GIVE_UP_AFTER = 5
# How many games one report line names before it counts the rest.
MAX_NAMED = 12

TeamKey = tuple[str, str]  # (league slug, team slug)


class PublishRefused(RuntimeError):
    """The build would shrink what subscribers already have. Nothing was
    written; the last good deploy stays live."""

    def __init__(self, report: GuardReport):
        self.report = report
        super().__init__(render_refusal(report))


@dataclass(frozen=True)
class PreviousGame:
    """One game as the previous publish listed it (a game dict in
    data/<league>/<team>.json)."""

    event_id: str
    name: str
    start: datetime  # the calendar feed's instant, timezone-aware
    status: str | None  # "Cancelled" / "Postponed" / "Rescheduled" / None

    def counts_at(self, horizon: datetime) -> bool:
        """True when its disappearance would be a loss: it starts after the
        horizon, and it was not already going away."""
        return self.start > horizon and self.status not in _EXPECTED_TO_LEAVE


@dataclass
class PreviousPublish:
    """What the live site published last, per team."""

    # Teams whose previous file was read. A team with no page yet (a new team)
    # is here with no games: there is nothing of it to lose.
    games: dict[TeamKey, list[PreviousGame]] = field(default_factory=dict)
    new_teams: set[TeamKey] = field(default_factory=set)
    # Teams whose previous file could not be read, and why. Not compared.
    unreadable: dict[TeamKey, str] = field(default_factory=dict)
    fetched_at: str | None = None  # the oldest `fetched_at` among the files read


@dataclass(frozen=True)
class VanishedGame:
    league_slug: str
    team_slug: str
    event_id: str
    name: str
    start: datetime

    def describe(self) -> str:
        return f"{self.event_id} ({self.name}, {self.start.strftime('%Y-%m-%d %H:%MZ')})"


@dataclass(frozen=True)
class Violation:
    league_slug: str
    league_name: str
    team_slug: str | None  # None for a league-level violation
    rule: str
    message: str
    override_reason: str | None = None  # set when an active override accepted it


@dataclass
class GuardReport:
    compared: bool
    note: str = ""
    previous_fetched_at: str | None = None
    teams_read: int = 0
    teams_configured: int = 0
    # Upcoming games in the previous publish, and how many of them are gone,
    # each game once per league (a game between two tracked teams counts once).
    previous_upcoming: int = 0
    league_vanished: int = 0
    # The same games team by team, as the team pages and feeds carry them.
    vanished: list[VanishedGame] = field(default_factory=list)
    # Vanished games that were not counted, because this build's fetch for
    # the team was cut short (ticketmaster.MAX_PAGES_PER_QUERY): the later
    # games are the ones a truncated fetch leaves out.
    unverifiable: list[VanishedGame] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)
    accepted: list[Violation] = field(default_factory=list)
    newly_cancelled: list[str] = field(default_factory=list)
    removed_after_cancel: list[str] = field(default_factory=list)
    expired_overrides: list[str] = field(default_factory=list)
    unreadable: dict[TeamKey, str] = field(default_factory=dict)

    @property
    def refused(self) -> bool:
        return bool(self.violations)


def not_compared(reason: str) -> GuardReport:
    return GuardReport(compared=False, note=reason)


def _parse_previous_game(entry: object) -> PreviousGame | None:
    """The game, or None when it is not in the previous calendar feed (a
    date-TBD game: no subscriber has an event for it, so none can be lost).
    Raises ValueError when the entry is not a shape this module can read."""
    if not isinstance(entry, dict) or not isinstance(entry.get("event_id"), str):
        raise ValueError("a game entry without an event id")
    raw_start = entry.get("start_utc")
    if entry.get("in_calendar_feed") is not True or not isinstance(raw_start, str):
        return None
    try:
        start = datetime.fromisoformat(raw_start)
    except ValueError:
        return None
    if start.tzinfo is None:
        return None  # an instant with no offset is not an instant
    name, status = entry.get("event_name"), entry.get("status")
    return PreviousGame(
        event_id=entry["event_id"],
        name=name if isinstance(name, str) and name else entry["event_id"],
        start=start,
        status=status if isinstance(status, str) else None,
    )


def _parse_previous_team(payload: object) -> tuple[str | None, list[PreviousGame]] | None:
    """(fetched_at, calendar-feed games) from a data/<league>/<team>.json
    body, or None when it is not a fetched team payload this module can
    read -- never partly trusted."""
    if not isinstance(payload, dict) or payload.get("fetched") is not True:
        return None
    raw_games = payload.get("games")
    if not isinstance(raw_games, list):
        return None
    try:
        parsed = [_parse_previous_game(entry) for entry in raw_games]
    except ValueError:
        return None
    games = [g for g in parsed if g is not None]
    fetched_at = payload.get("fetched_at")
    return (fetched_at if isinstance(fetched_at, str) else None), games


def fetch_previous_publish(base_url: str, *, client: httpx.Client | None = None) -> PreviousPublish:
    """The live site's per-team data files. Never raises: whatever cannot be
    read is recorded in `unreadable` and reported, and costs only that
    team's comparison."""
    previous = PreviousPublish()
    owns_client = client is None
    http = client or httpx.Client(timeout=10.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
    transport_failures = 0
    fetched_times: list[str] = []
    try:
        for league, team in config.all_teams():
            key = (league.slug, team.slug)
            if transport_failures >= _GIVE_UP_AFTER:
                previous.unreadable[key] = "not tried: the site did not answer the requests before it"
                continue
            url = f"{base_url}/data/{league.slug}/{team.slug}.json"
            try:
                response = http.get(url)
            except httpx.HTTPError as exc:
                transport_failures += 1
                previous.unreadable[key] = f"request failed ({type(exc).__name__})"
                continue
            transport_failures = 0
            if response.status_code == 404:
                previous.games[key] = []
                previous.new_teams.add(key)
                continue
            if response.status_code != 200:
                previous.unreadable[key] = f"HTTP {response.status_code}"
                continue
            try:
                parsed = _parse_previous_team(response.json())
            except ValueError:
                parsed = None
            if parsed is None:
                previous.unreadable[key] = "not a fetched team file this build can read"
                continue
            fetched_at, games = parsed
            previous.games[key] = games
            if fetched_at:
                fetched_times.append(fetched_at)
    finally:
        if owns_client:
            http.close()
    previous.fetched_at = min(fetched_times) if fetched_times else None
    return previous


def _active_overrides(
    overrides: Sequence[config.GuardOverride], today: datetime
) -> tuple[dict[str, config.GuardOverride], list[str]]:
    active: dict[str, config.GuardOverride] = {}
    expired: list[str] = []
    for override in overrides:
        if today.date() <= override.until:
            active[override.league_slug] = override
        else:
            expired.append(
                f"the guard override for {override.league_slug} expired on {override.until.isoformat()} "
                f"and no longer applies ({override.reason})"
            )
    return active, expired


def _is_expected_to_leave_now(game: Game) -> bool:
    return NOTABLE_STATUSES.get(game.status_code or "") in _EXPECTED_TO_LEAVE


def _no_previous_note(previous: PreviousPublish, configured: int) -> str:
    if previous.unreadable:
        return (
            "the previous publish could not be read, so this build was NOT compared with it "
            f"({len(previous.unreadable)} of {configured} team files unreadable)"
        )
    return "no previous publish was found, so there was nothing to compare"


class _Evaluation:
    """One comparison of a build with the previous publish. Holds the fresh
    games indexed by team and league so the per-team and per-league rules
    can each be a short method."""

    def __init__(
        self,
        previous: PreviousPublish,
        games: Sequence[Game],
        truncated: Mapping[str, set[str]],
        now: datetime,
        settings: config.PublishGuard,
        report: GuardReport,
    ) -> None:
        self.previous = previous
        self.truncated = truncated
        self.now = now
        self.settings = settings
        self.report = report
        self.horizon = now + timedelta(hours=settings.settle_hours)
        self.fresh_by_team: dict[TeamKey, dict[str, Game]] = defaultdict(dict)
        self.fresh_by_league: dict[str, dict[str, Game]] = defaultdict(dict)
        for g in games:
            self.fresh_by_team[(g.league_slug, g.tracked_team_slug)][g.event_id] = g
            self.fresh_by_league[g.league_slug][g.event_id] = g

    def league(self, lg: config.League) -> list[Violation]:
        """The league's violations. Fills the report's counters and lists."""
        league_previous: dict[str, PreviousGame] = {}
        violations: list[Violation] = []
        for team in lg.teams:
            if (lg.slug, team.slug) not in self.previous.games:
                continue
            found = self._team(lg, team, league_previous)
            if found is not None:
                violations.append(found)
        fresh_league = self.fresh_by_league.get(lg.slug, {})
        vanished = [e for e in league_previous if e not in fresh_league]
        self.report.previous_upcoming += len(league_previous)
        self.report.league_vanished += len(vanished)
        in_feed = any(g.start_utc is not None and not g.date_tbd for g in fresh_league.values())
        league_found = self._league_rule(lg, len(league_previous), len(vanished), in_feed)
        if league_found is not None:
            violations.append(league_found)
        return violations

    def _team(self, lg: config.League, team: config.Team, league_previous: dict[str, PreviousGame]) -> Violation | None:
        key = (lg.slug, team.slug)
        fresh_team = self.fresh_by_team.get(key, {})
        listed = self.previous.games[key]
        upcoming = [pg for pg in listed if pg.counts_at(self.horizon)]
        rows = [
            VanishedGame(lg.slug, team.slug, pg.event_id, pg.name, pg.start.astimezone(UTC))
            for pg in upcoming
            if pg.event_id not in fresh_team
        ]
        self.report.removed_after_cancel.extend(
            f"{lg.slug}/{team.slug}: {pg.event_id} ({pg.name})"
            for pg in listed
            if pg.status in _EXPECTED_TO_LEAVE and pg.start > self.horizon and pg.event_id not in fresh_team
        )
        if team.slug in self.truncated.get(lg.slug, set()):
            # This build's fetch stopped before the end of Ticketmaster's
            # results, so a game missing from it is not known to be gone.
            self.report.unverifiable.extend(rows)
            return None
        self.report.vanished.extend(rows)
        for pg in upcoming:
            league_previous.setdefault(pg.event_id, pg)
        if len(upcoming) >= self.settings.min_previous_upcoming and len(rows) == len(upcoming):
            return Violation(
                lg.slug,
                lg.name,
                team.slug,
                "team-all",
                f"{team.name} ({lg.slug}/{team.slug}) lost all {len(upcoming)} of its upcoming games: " + _named(rows),
            )
        return None

    def _league_rule(
        self, lg: config.League, previous_count: int, vanished_count: int, in_feed: bool
    ) -> Violation | None:
        if previous_count and not in_feed:
            return Violation(
                lg.slug,
                lg.name,
                None,
                "league-empty",
                f"{lg.name} ({lg.slug}) would publish an EMPTY calendar over one that had "
                f"{previous_count} upcoming game(s)",
            )
        limit = self.settings.max_league_vanished_share
        if previous_count >= self.settings.min_previous_upcoming and vanished_count / previous_count > limit:
            return Violation(
                lg.slug,
                lg.name,
                None,
                "league-share",
                f"{lg.name} ({lg.slug}) lost {vanished_count} of {previous_count} upcoming games "
                f"({vanished_count / previous_count:.0%}; the limit is {limit:.0%})",
            )
        return None

    def newly_cancelled(self) -> list[str]:
        """Upcoming games still listed but now cancelled or postponed that the
        previous publish did not say so about: reported, never blocking."""
        was: dict[str, str | None] = {}
        for listed in self.previous.games.values():
            for pg in listed:
                was.setdefault(pg.event_id, pg.status)
        return [
            f"{g.league_slug}: {g.event_id} ({g.raw_event_name})"
            for league_games in self.fresh_by_league.values()
            for g in league_games.values()
            if _is_expected_to_leave_now(g)
            and g.start_utc is not None
            and g.start_utc > self.now
            and was.get(g.event_id) not in _EXPECTED_TO_LEAVE
        ]


def evaluate(
    previous: PreviousPublish,
    games: Sequence[Game],
    truncated: Mapping[str, set[str]],
    *,
    now: datetime,
    leagues: Sequence[config.League] | None = None,
    settings: config.PublishGuard | None = None,
    overrides: Sequence[config.GuardOverride] | None = None,
) -> GuardReport:
    """Compare this build's games with the previous publish; see the module
    docstring for the rules and config.PublishGuard for the thresholds."""
    leagues = config.LEAGUES if leagues is None else leagues
    settings = config.PUBLISH_GUARD if settings is None else settings
    overrides = config.PUBLISH_GUARD_OVERRIDES if overrides is None else overrides
    now = now.astimezone(UTC)
    active, expired = _active_overrides(overrides, now)
    configured = sum(len(lg.teams) for lg in leagues)
    report = GuardReport(
        compared=bool(previous.games),
        previous_fetched_at=previous.fetched_at,
        teams_read=len(previous.games),
        teams_configured=configured,
        expired_overrides=expired,
        unreadable=dict(previous.unreadable),
    )
    if not previous.games:
        report.note = _no_previous_note(previous, configured)
        return report

    evaluation = _Evaluation(previous, games, truncated, now, settings, report)
    for lg in leagues:
        override = active.get(lg.slug)
        for violation in evaluation.league(lg):
            if override is None:
                report.violations.append(violation)
            else:
                accepted_because = f"{override.reason} (until {override.until.isoformat()})"
                report.accepted.append(replace(violation, override_reason=accepted_because))
    report.newly_cancelled = evaluation.newly_cancelled()
    return report


def _named(rows: Sequence[VanishedGame]) -> str:
    named = "; ".join(r.describe() for r in rows[:MAX_NAMED])
    return named + (f"; and {len(rows) - MAX_NAMED} more" if len(rows) > MAX_NAMED else "")


def render_refusal(report: GuardReport) -> str:
    lines = [
        "the publish guard refused this build: publishing it would remove games from "
        "subscribers' calendars (docs/adr/0006).",
    ]
    for v in report.violations:
        lines.append(f"  - {v.message}")
    lines.append(
        "Nothing was written to --out, so the last good deploy (every league's calendar as of the "
        "previous good night) stays live."
    )
    lines.append(
        "If this is a real removal (Ticketmaster withdrew the listings, the league canceled the games, an "
        "intended off-season), add a dated override for that league to PUBLISH_GUARD_OVERRIDES in "
        "pipeline/src/wsc_pipeline/config.py with the reason, then re-run the pages workflow."
    )
    lines.append(
        "If it is not, a Ticketmaster query for these teams has stopped matching (a rename, a keyword, a "
        "catalog change): check the team names in config.py against Ticketmaster before overriding."
    )
    return "\n".join(lines)


def _render_vanished(report: GuardReport) -> list[str]:
    per_team: dict[tuple[str, str], list[VanishedGame]] = defaultdict(list)
    for row in report.vanished:
        per_team[(row.league_slug, row.team_slug)].append(row)
    lines = [f"  vanished, {league}/{team}: {_named(rows)}" for (league, team), rows in sorted(per_team.items())]
    if report.unverifiable:
        teams = sorted({f"{r.league_slug}/{r.team_slug}" for r in report.unverifiable})
        lines.append(
            f"  {len(report.unverifiable)} game(s) missing for possibly-incomplete teams were not counted "
            f"(the fetch stopped before the end of Ticketmaster's results): {', '.join(teams)}"
        )
    return lines


def _render_changes(report: GuardReport) -> list[str]:
    lines = []
    if report.newly_cancelled:
        lines.append(
            f"  newly cancelled or postponed, still listed: {len(report.newly_cancelled)}: "
            + "; ".join(report.newly_cancelled[:MAX_NAMED])
        )
    if report.removed_after_cancel:
        lines.append(
            "  removed after being marked cancelled or postponed (expected, not counted): "
            f"{len(report.removed_after_cancel)}: " + "; ".join(report.removed_after_cancel[:MAX_NAMED])
        )
    return lines


def render_section(report: GuardReport) -> list[str]:
    """The publish guard's part of COVERAGE.txt. Published, so it names no
    repository file."""
    lines = ["-- Publish guard (compares this build with the previous publish) --"]
    if not report.compared:
        return [*lines, f"  NOT COMPARED: {report.note}", ""]
    lines.append(
        f"  compared with the publish fetched {report.previous_fetched_at or 'at an unknown time'}: "
        f"{report.teams_read} of {report.teams_configured} team files read."
    )
    lines.append(
        f"  upcoming games in that publish (each counted once per league): {report.previous_upcoming}; "
        f"vanished from this build: {report.league_vanished}."
    )
    if report.unreadable:
        unread = ", ".join(f"{lg}/{t} ({why})" for (lg, t), why in sorted(report.unreadable.items()))
        lines.append(
            f"  WARNING: {len(report.unreadable)} team file(s) of the previous publish could not be read, so "
            f"those teams were NOT compared: {unread}"
        )
    lines.extend(_render_vanished(report))
    lines.extend(_render_changes(report))
    lines.extend(f"  ACCEPTED BY OVERRIDE ({v.override_reason}): {v.message}" for v in report.accepted)
    lines.extend(f"  NOTE: {note}" for note in report.expired_overrides)
    lines.append("")
    return lines


def announce(report: GuardReport, *, github_actions: bool) -> None:
    """One-line messages for the run log (stderr) about what the guard could
    not check or accepted; `::warning` annotations under GitHub Actions."""
    messages: list[str] = []
    if not report.compared:
        messages.append(f"NOT COMPARED with the previous publish: {report.note}")
    elif report.unreadable:
        messages.append(
            f"{len(report.unreadable)} of {report.teams_configured} previous team files could not be read; "
            "those teams were not compared"
        )
    messages.extend(f"accepted by override: {v.message} ({v.override_reason})" for v in report.accepted)
    messages.extend(report.expired_overrides)
    for message in messages:
        print(f"WARNING: publish guard: {message}", file=sys.stderr)
        if github_actions:
            print(f"::warning title=Publish guard::{message}", file=sys.stderr)
