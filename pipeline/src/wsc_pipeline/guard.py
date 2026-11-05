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
its calendar feed, ics/<league>/<team>.ics: exactly the games a subscriber of
that team has (validate_ics holds every feed to its page's games). The
per-team JSON files it used to read are no longer published (DECISIONS 0024).
The thresholds and the per-league override live in
config.py (PUBLISH_GUARD, PUBLISH_GUARD_OVERRIDES); the decision and its
trade-offs are docs/adr/0006.

What counts as a vanished game (all must hold):

- the previous publish listed it, and it was in that publish's calendar feed:
  a timed event, or an all-day event for a game with a date and no announced
  time (never a date-TBD game, which no feed carries);
- it was to start more than `settle_hours` after this build. A game that has
  started and left Ticketmaster's listing since last night is the normal end
  of a game, so a season that ends, or an off-season league, vanishes
  nothing, and no season calendar is needed. A game with only a date counts
  when that date is after the day the window ends;
- the previous publish had not marked it cancelled or postponed (removal of a
  listing is what those look like);
- its event id is not in config.REMOVED_EVENTS, the removals the maintainer
  has accepted one event at a time (reported, not counted);
- this build no longer lists it (a game still listed but now cancelled is not
  vanished: it is reported as a change instead).

A refusal raises PublishRefused and the build writes nothing, so the last good
deploy stays live.

A previous feed that existed but could not be read (a request error, a status
other than 200 or 404, or a body that is not a fetched feed) refuses the build
too, for its league ("previous-unreadable"): the live feed is the only copy
of the played games it keeps (history.py, DECISIONS 0027), so publishing
without it would erase them for good. The live site keeps serving the last
good feeds, and the next run that can read them publishes. A feed that never
existed (404) is new and has nothing to lose. A dated league override in
PUBLISH_GUARD_OVERRIDES accepts the loss, as for the other rules. Until
2026-11-05 an unreadable previous publish never blocked.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta

import httpx
from icalendar import Calendar, Component

from . import config
from .ics import FEED_STATUS, NOT_FETCHED_CALDESC, TIME_TBA_SUFFIX, UID_DOMAIN
from .listings import EVENT_START_SUFFIX
from .normalize import Game, feed_start
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
    """One game as the previous publish listed it (a VEVENT in
    ics/<league>/<team>.ics)."""

    event_id: str
    name: str
    # The calendar feed's instant, timezone-aware. For an all-day game (a
    # date and no announced time) it is 00:00 UTC on that date, and
    # `date_only` is set. That is no later than the date begins at any venue
    # tracked (all in the Americas), so comparing it with the horizon counts
    # the game only when its date is after the day the horizon falls on: it
    # may start at any hour of its own date.
    start: datetime
    status: str | None  # "Cancelled" / "Postponed" / "Rescheduled" / None
    date_only: bool = False

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
    fetched_at: str | None = None  # the oldest DTSTAMP (the build's fetch time) among the feeds read
    # Every VEVENT of each feed read, by its path ("ics/wnba.ics",
    # "ics/wnba/indiana-fever.ics"): the team feeds above and the league
    # feeds, for history.py (played games kept, SEQUENCE, LAST-MODIFIED).
    # The guard's own rules read only `games`.
    feeds: dict[str, list[Component]] = field(default_factory=dict)
    # League feeds that could not be read, and why (a team's are in
    # `unreadable`). Their played games cannot be kept tonight.
    unreadable_feeds: dict[str, str] = field(default_factory=dict)

    @property
    def fully_read(self) -> bool:
        """Every team and league feed was read (a new team's 404 counts)."""
        return bool(self.games) and not self.unreadable and not self.unreadable_feeds


@dataclass(frozen=True)
class VanishedGame:
    league_slug: str
    team_slug: str
    event_id: str
    name: str
    start: datetime
    date_only: bool = False

    def describe(self) -> str:
        when = self.start.strftime("%Y-%m-%d, time TBA" if self.date_only else "%Y-%m-%d %H:%MZ")
        return f"{self.event_id} ({self.name}, {when})"


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
    # Gone, but named in config.REMOVED_EVENTS: accepted, not counted.
    accepted_removals: list[str] = field(default_factory=list)
    expired_overrides: list[str] = field(default_factory=list)
    unreadable: dict[TeamKey, str] = field(default_factory=dict)

    @property
    def refused(self) -> bool:
        return bool(self.violations)


def not_compared(reason: str) -> GuardReport:
    return GuardReport(compared=False, note=reason)


# The feed's STATUS for each page status word, read back (ics.FEED_STATUS).
# "Rescheduled" writes no STATUS, and the guard needs only the two that mean
# a game was going away.
_STATUS_FROM_FEED = {fs.ics_status: word for word, fs in FEED_STATUS.items() if fs.ics_status}
_UID_SUFFIX = f"@{UID_DOMAIN}"


def _event_id_from_uid(uid: str) -> str:
    """The Ticketmaster event id in an ics.make_uid UID; raises ValueError
    for any other UID."""
    if not (uid.startswith("tm-") and uid.endswith(_UID_SUFFIX)) or len(uid) <= len("tm-") + len(_UID_SUFFIX):
        raise ValueError(f"not a UID this site writes: {uid!r}")
    return uid[len("tm-") : -len(_UID_SUFFIX)]


def _name_from_summary(summary: str, status: str | None) -> str:
    """The event name without the feed's status prefix and its time-TBA or
    event-start suffix."""
    if status:
        summary = summary.removeprefix(FEED_STATUS[status].summary_prefix)
    return summary.removesuffix(TIME_TBA_SUFFIX).removesuffix(EVENT_START_SUFFIX)


def _parse_previous_event(vevent: object) -> tuple[PreviousGame, datetime | None]:
    """The game and its DTSTAMP. A game with a date and no announced time is
    an all-day event, read by its local date at 00:00 UTC. Raises ValueError
    when the event is not a shape this module can read."""
    if not hasattr(vevent, "get") or not hasattr(vevent, "decoded"):
        raise ValueError("not an event")
    event_id = _event_id_from_uid(str(vevent.get("uid", "")))
    if vevent.get("dtstart") is None:
        raise ValueError("an event without DTSTART")
    raw_start = vevent.decoded("dtstart")
    if isinstance(raw_start, datetime):
        if raw_start.tzinfo is None:
            raise ValueError("an event start with no offset is not an instant")
        start, date_only = raw_start.astimezone(UTC), False
    elif isinstance(raw_start, date):
        start, date_only = datetime.combine(raw_start, time(0), UTC), True
    else:
        raise ValueError("an event start that is not a date")
    raw_status = vevent.get("status")
    status = _STATUS_FROM_FEED.get(str(raw_status).upper()) if raw_status is not None else None
    name = _name_from_summary(str(vevent.get("summary", "")), status)
    stamp = vevent.decoded("dtstamp") if vevent.get("dtstamp") is not None else None
    return (
        PreviousGame(event_id=event_id, name=name or event_id, start=start, status=status, date_only=date_only),
        stamp if isinstance(stamp, datetime) else None,
    )


def _parse_previous_team(feed: bytes) -> tuple[str | None, list[PreviousGame]] | None:
    """(fetch time, calendar-feed games) from an ics/<league>/<team>.ics
    body, or None when it is not a fetched team feed this module can read
    -- never partly trusted. A degraded build's feed (it fetched nothing)
    says so in its description, and is not read as an empty schedule."""
    try:
        cal = Calendar.from_ical(feed)
    except Exception:  # icalendar raises ValueError and others on bad input
        return None
    if not isinstance(cal, Calendar) or str(cal.get("x-wr-caldesc", "")).startswith(NOT_FETCHED_CALDESC):
        return None
    games: list[PreviousGame] = []
    stamps: list[datetime] = []
    try:
        for vevent in cal.walk("VEVENT"):
            game, stamp = _parse_previous_event(vevent)
            games.append(game)
            if stamp is not None:
                stamps.append(stamp)
    except (ValueError, KeyError, TypeError):
        return None
    fetched_at = min(stamps).astimezone(UTC).isoformat() if stamps else None
    return fetched_at, games


def _feed_events(feed: bytes) -> list[Component] | None:
    """Every VEVENT of a fetched feed, or None when it is not one (the same
    test as _parse_previous_team)."""
    try:
        cal = Calendar.from_ical(feed)
    except Exception:  # icalendar raises ValueError and others on bad input
        return None
    if not isinstance(cal, Calendar) or str(cal.get("x-wr-caldesc", "")).startswith(NOT_FETCHED_CALDESC):
        return None
    return list(cal.walk("VEVENT"))


def fetch_previous_publish(base_url: str, *, client: httpx.Client | None = None) -> PreviousPublish:
    """The live site's per-team calendar feeds, then its league feeds (for
    history.py only). Never raises: whatever cannot be read is recorded in
    `unreadable` (or `unreadable_feeds`), and evaluate() refuses the build
    for that league (UNREADABLE_RULE)."""
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
            url = f"{base_url}/ics/{league.slug}/{team.slug}.ics"
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
            parsed = _parse_previous_team(response.content)
            if parsed is None:
                previous.unreadable[key] = "not a fetched team feed this build can read"
                continue
            fetched_at, games = parsed
            previous.games[key] = games
            previous.feeds[f"ics/{league.slug}/{team.slug}.ics"] = _feed_events(response.content) or []
            if fetched_at:
                fetched_times.append(fetched_at)
        _fetch_league_feeds(http, base_url, previous, transport_failures)
    finally:
        if owns_client:
            http.close()
    previous.fetched_at = min(fetched_times) if fetched_times else None
    return previous


def _fetch_league_feeds(http: httpx.Client, base_url: str, previous: PreviousPublish, transport_failures: int) -> None:
    """Each league feed's events into previous.feeds, or why not into
    previous.unreadable_feeds, giving up as the team loop does."""
    for league in config.LEAGUES:
        path = f"ics/{league.slug}.ics"
        if transport_failures >= _GIVE_UP_AFTER:
            previous.unreadable_feeds[path] = "not tried: the site did not answer the requests before it"
            continue
        try:
            response = http.get(f"{base_url}/{path}")
        except httpx.HTTPError as exc:
            transport_failures += 1
            previous.unreadable_feeds[path] = f"request failed ({type(exc).__name__})"
            continue
        transport_failures = 0
        if response.status_code == 404:
            previous.feeds[path] = []  # a new league: nothing to keep
            continue
        events = _feed_events(response.content) if response.status_code == 200 else None
        if events is None:
            why = f"HTTP {response.status_code}" if response.status_code != 200 else "not a fetched feed"
            previous.unreadable_feeds[path] = why
            continue
        previous.feeds[path] = events


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


def _upcoming_now(game: Game, now: datetime) -> bool:
    """Whether a freshly fetched game in the feed is still ahead: by its
    instant when timed, by its date when all-day."""
    start = feed_start(game)
    if isinstance(start, datetime):
        return start > now
    return start is not None and start > now.date()


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
        removed_event_ids: frozenset[str] = frozenset(),
    ) -> None:
        self.removed_event_ids = removed_event_ids
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
        in_feed = any(feed_start(g) is not None for g in fresh_league.values())
        league_found = self._league_rule(lg, len(league_previous), len(vanished), in_feed)
        if league_found is not None:
            violations.append(league_found)
        return violations

    def _team(self, lg: config.League, team: config.Team, league_previous: dict[str, PreviousGame]) -> Violation | None:
        key = (lg.slug, team.slug)
        fresh_team = self.fresh_by_team.get(key, {})
        listed = self.previous.games[key]
        counted = [pg for pg in listed if pg.counts_at(self.horizon)]
        upcoming = [pg for pg in counted if pg.event_id not in self.removed_event_ids]
        rows = [
            VanishedGame(lg.slug, team.slug, pg.event_id, pg.name, pg.start.astimezone(UTC), pg.date_only)
            for pg in upcoming
            if pg.event_id not in fresh_team
        ]
        self.report.removed_after_cancel.extend(
            f"{lg.slug}/{team.slug}: {pg.event_id} ({pg.name})"
            for pg in listed
            if pg.status in _EXPECTED_TO_LEAVE and pg.start > self.horizon and pg.event_id not in fresh_team
        )
        self.report.accepted_removals.extend(
            f"{lg.slug}/{team.slug}: {pg.event_id} ({pg.name})"
            for pg in counted
            if pg.event_id in self.removed_event_ids and pg.event_id not in fresh_team
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
            and _upcoming_now(g, self.now)
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
    removed_events: Sequence[config.EventRemoval] | None = None,
) -> GuardReport:
    """Compare this build's games with the previous publish; see the module
    docstring for the rules and config.PublishGuard for the thresholds."""
    leagues = config.LEAGUES if leagues is None else leagues
    settings = config.PUBLISH_GUARD if settings is None else settings
    overrides = config.PUBLISH_GUARD_OVERRIDES if overrides is None else overrides
    removed_events = config.REMOVED_EVENTS if removed_events is None else removed_events
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
    for lg in leagues:
        unread = _unreadable_violation(previous, lg)
        if unread is None:
            continue
        override = active.get(lg.slug)
        if override is None:
            report.violations.append(unread)
        else:
            report.accepted.append(
                replace(unread, override_reason=f"{override.reason} (until {override.until.isoformat()})")
            )
    if not previous.games:
        report.note = _no_previous_note(previous, configured)
        return report

    removed_ids = frozenset(r.event_id for r in removed_events)
    evaluation = _Evaluation(previous, games, truncated, now, settings, report, removed_ids)
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


UNREADABLE_RULE = "previous-unreadable"


def _unreadable_violation(previous: PreviousPublish, lg: config.League) -> Violation | None:
    """The league's previous feeds that existed but could not be read, as one
    violation, or None when every one was read (or was new)."""
    unread = [
        f"ics/{lg.slug}/{t.slug}.ics ({previous.unreadable[(lg.slug, t.slug)]})"
        for t in lg.teams
        if (lg.slug, t.slug) in previous.unreadable
    ]
    league_path = f"ics/{lg.slug}.ics"
    if league_path in previous.unreadable_feeds:
        unread.insert(0, f"{league_path} ({previous.unreadable_feeds[league_path]})")
    if not unread:
        return None
    shown = "; ".join(unread[:MAX_NAMED]) + (f"; and {len(unread) - MAX_NAMED} more" if len(unread) > MAX_NAMED else "")
    return Violation(
        lg.slug,
        lg.name,
        None,
        UNREADABLE_RULE,
        f"{lg.name} ({lg.slug}): {len(unread)} previous calendar feed(s) could not be read, and the live "
        f"feed is the only copy of the played games it keeps: {shown}",
    )


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
    if any(v.rule == UNREADABLE_RULE for v in report.violations):
        lines.append(
            "A previous feed that could not be read is not a loss of games: re-run the pages workflow once "
            "the live site answers. If a feed stays unreadable, a dated override for its league in "
            "PUBLISH_GUARD_OVERRIDES publishes without the played games it kept."
        )
    lines.append(
        "If this is a real removal (Ticketmaster withdrew the listings, the league canceled the games, a "
        "playoff series ended before its 'if necessary' games), accept it in "
        "pipeline/src/wsc_pipeline/config.py, then re-run the pages workflow: add each event id named above "
        "to REMOVED_EVENTS with the date and the reason, or, for a league-wide withdrawal, add a dated "
        "override for that league to PUBLISH_GUARD_OVERRIDES."
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
    if report.accepted_removals:
        lines.append(
            f"  removals accepted one event at a time (not counted): {len(report.accepted_removals)}: "
            + "; ".join(report.accepted_removals[:MAX_NAMED])
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
