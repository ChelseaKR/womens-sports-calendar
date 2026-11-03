"""Measure candidate leagues on the Ticketmaster Discovery API (DECISIONS 0022).

Run only by .github/workflows/measure-leagues.yml (workflow_dispatch). It
answers one question before a league is added to config.LEAGUES: how many
upcoming events would the site really list for it? So it uses the site's own
fetch and attribution code, unchanged: build._search_team (the keyword
search, every page, de-duplicated), normalize.team_is_participant_as_any
(the participant check, DECISIONS 0009), normalize.normalize_event (drops an
event with no id or date) and site_data.tracked_team_is_home.

It writes counts only: no event name, id, URL, venue or price leaves this
module, and an error is recorded as "failed", never as a number. A team that
was not measured (failed, over the request cap, or no confirmed team name) is
shown as not measured, never as 0 events (absence is not a value).

The candidate rosters below were read on 2026-11-02. The college keywords
follow the Big Ten pattern ("<School> <Mascot> Womens Basketball", with a
"<School> women's basketball" title name, DECISIONS 0010). They were NOT
checked against Ticketmaster's artist pages first, so a team with 0 events
returned may mean a wrong keyword, not missing inventory.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .build import _search_team
from .config import League, Team
from .normalize import Game, normalize_event, team_is_participant_as_any
from .site_data import tracked_team_is_home
from .ticketmaster import DiscoveryClient, TicketmasterFetchError

# The Discovery API allows 5000 requests a day (docs/LICENSES-AND-ATTRIBUTION.md
# §2), shared with the nightly build. A full run of every candidate needs
# roughly 100 to 300; this cap keeps a run from ever eating the nightly
# build's share. Teams past the cap are reported as not measured.
MAX_REQUESTS = 1500

FAILED = "failed"
OVER_CAP = "skipped: request cap reached"

# A "<School> women's basketball" title name is a plain substring of the same
# name with a direction in front ("Kentucky" in "Northern Kentucky"), so the
# phrase check would accept the other school's games. These are removed before
# matching, the same way config.KEYWORD_COLLISIONS works for "Bay FC".
_DIRECTIONS = ("North", "South", "Northern", "Southern", "Eastern", "Western", "Central", "East", "West")
# Collisions that are not a direction: "kansas women s basketball" is inside
# "arkansas women s basketball".
_EXTRA_COLLISIONS: dict[str, tuple[str, ...]] = {
    "Kansas": ("Arkansas women's basketball", "Arkansas Razorbacks Womens Basketball"),
}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _college_teams(schools: dict[str, str]) -> tuple[Team, ...]:
    """{school: mascot} -> teams named the Big Ten way."""
    teams = []
    for school, mascot in schools.items():
        not_this = tuple(f"{d} {school} women's basketball" for d in _DIRECTIONS) + _EXTRA_COLLISIONS.get(school, ())
        name = f"{school} {mascot} Womens Basketball"
        teams.append(
            Team(slug=_slug(name), name=name, not_this_team=not_this, title_name=f"{school} women's basketball")
        )
    return tuple(teams)


def _pro_teams(*names: str) -> tuple[Team, ...]:
    return tuple(Team(slug=_slug(n), name=n) for n in names)


@dataclass(frozen=True)
class Candidate:
    """A league that might be added. `league` holds its teams in the same
    shape config.LEAGUES does, so the site's own code can be run on them."""

    league: League
    # Also searched as a keyword, to count events that name the league but
    # no team (a touring event, a tournament). None: not searched.
    league_keyword: str | None = None
    # Teams that could not be measured, and why: {team: reason}.
    unmeasured_teams: dict[str, str] = field(default_factory=dict)
    source: str = ""


def _league(slug: str, name: str, teams: tuple[Team, ...]) -> League:
    return League(slug=slug, name=name, country_codes=("US",), teams=teams)


CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        _league(
            "ncaaw-sec",
            "NCAA Women's Basketball (SEC)",
            _college_teams(
                {
                    "Alabama": "Crimson Tide",
                    "Arkansas": "Razorbacks",
                    "Auburn": "Tigers",
                    "Florida": "Gators",
                    "Georgia": "Lady Bulldogs",
                    "Kentucky": "Wildcats",
                    "LSU": "Tigers",
                    "Mississippi State": "Bulldogs",
                    "Missouri": "Tigers",
                    "Oklahoma": "Sooners",
                    "Ole Miss": "Rebels",
                    "South Carolina": "Gamecocks",
                    "Tennessee": "Lady Volunteers",
                    "Texas": "Longhorns",
                    "Texas A&M": "Aggies",
                    "Vanderbilt": "Commodores",
                }
            ),
        ),
        source="SEC membership for 2026-27 (16 schools).",
    ),
    Candidate(
        _league(
            "ncaaw-acc",
            "NCAA Women's Basketball (ACC)",
            _college_teams(
                {
                    "Boston College": "Eagles",
                    "California": "Golden Bears",
                    "Clemson": "Tigers",
                    "Duke": "Blue Devils",
                    "Florida State": "Seminoles",
                    "Georgia Tech": "Yellow Jackets",
                    "Louisville": "Cardinals",
                    "Miami": "Hurricanes",
                    "NC State": "Wolfpack",
                    "North Carolina": "Tar Heels",
                    "Notre Dame": "Fighting Irish",
                    "Pittsburgh": "Panthers",
                    "SMU": "Mustangs",
                    "Stanford": "Cardinal",
                    "Syracuse": "Orange",
                    "Virginia": "Cavaliers",
                    "Virginia Tech": "Hokies",
                    "Wake Forest": "Demon Deacons",
                }
            ),
        ),
        source="ACC membership for 2026-27 (18 schools).",
    ),
    Candidate(
        _league(
            "ncaaw-big-12",
            "NCAA Women's Basketball (Big 12)",
            _college_teams(
                {
                    "Arizona": "Wildcats",
                    "Arizona State": "Sun Devils",
                    "Baylor": "Bears",
                    "BYU": "Cougars",
                    "Cincinnati": "Bearcats",
                    "Colorado": "Buffaloes",
                    "Houston": "Cougars",
                    "Iowa State": "Cyclones",
                    "Kansas": "Jayhawks",
                    "Kansas State": "Wildcats",
                    "Oklahoma State": "Cowgirls",
                    "TCU": "Horned Frogs",
                    "Texas Tech": "Lady Raiders",
                    "UCF": "Knights",
                    "Utah": "Utes",
                    "West Virginia": "Mountaineers",
                }
            ),
        ),
        source="Big 12 membership for 2026-27 (16 schools).",
    ),
    Candidate(
        _league(
            "ncaaw-big-east",
            "NCAA Women's Basketball (Big East)",
            _college_teams(
                {
                    "Butler": "Bulldogs",
                    "Creighton": "Bluejays",
                    "DePaul": "Blue Demons",
                    "Georgetown": "Hoyas",
                    "Marquette": "Golden Eagles",
                    "Providence": "Friars",
                    "St. John's": "Red Storm",
                    "Seton Hall": "Pirates",
                    "UConn": "Huskies",
                    "Villanova": "Wildcats",
                    "Xavier": "Musketeers",
                }
            ),
        ),
        source="Big East membership for 2026-27 (11 schools).",
    ),
    Candidate(
        _league(
            "mlv",
            "Major League Volleyball",
            _pro_teams(
                "Atlanta Vibe",
                "Columbus Fury",
                "Dallas Pulse",
                "Grand Rapids Rise",
                "Indy Ignite",
                "Omaha Supernovas",
                "Orlando Valkyries",
                "Vegas Thrill",
            ),
        ),
        league_keyword="Major League Volleyball",
        unmeasured_teams={
            "Los Angeles": "2027 expansion team; no confirmed team name found on 2026-11-02",
            "Minnesota": "2027 expansion team; no confirmed team name found on 2026-11-02",
            "Northern California": "2027 expansion team; no confirmed team name found on 2026-11-02",
            "Washington, DC": "2027 expansion team; no confirmed team name found on 2026-11-02",
        },
        source="MLV 2027 conference alignment (mlvb.com, 2026-08): 12 markets.",
    ),
    Candidate(
        _league(
            "unrivaled",
            "Unrivaled",
            _pro_teams(
                "Breeze BC", "Hive BC", "Laces BC", "Lunar Owls BC", "Mist BC", "Phantom BC", "Rose BC", "Vinyl BC"
            ),
        ),
        league_keyword="Unrivaled",
        source="The eight 2026 clubs; the 2027 rosters were not yet announced on 2026-11-02.",
    ),
    Candidate(
        _league(
            "lovb",
            "LOVB Pro",
            _pro_teams(
                "LOVB Atlanta",
                "LOVB Austin",
                "LOVB Houston",
                "LOVB Madison",
                "LOVB Nebraska",
                "LOVB Salt Lake",
                "LOVB Los Angeles",
                "LOVB Minnesota",
                "LOVB San Francisco",
                "LOVB Miami",
            ),
        ),
        league_keyword="LOVB",
        source="Six 2026 teams plus the four announced for 2027 (lovb.com news).",
    ),
)


@dataclass
class TeamCount:
    team: str
    keyword: str
    # None whenever `status` is not "measured": not measured is not 0.
    events_returned: int | None = None
    attributed: int | None = None
    attributed_upcoming: int | None = None
    home_games: int | None = None
    truncated: bool | None = None
    status: str = "measured"


@dataclass
class CandidateCount:
    slug: str
    name: str
    source: str
    teams: list[TeamCount]
    unmeasured_teams: dict[str, str]
    league_keyword: str | None
    league_keyword_events: int | None = None
    league_keyword_attributed: int | None = None
    league_keyword_status: str | None = None
    # Unique events across teams (a game between two candidate teams counts once).
    unique_attributed: int | None = None
    unique_attributed_upcoming: int | None = None
    teams_with_upcoming: int | None = None
    teams_total: int = 0
    complete: bool = False


def _is_upcoming(game: Game, today: date) -> bool:
    """Not dated before `today` (UTC). A date-TBD game is upcoming."""
    if game.date_tbd:
        return True
    day = game.start_local_date or (game.start_utc.date() if game.start_utc else None)
    return day is None or day >= today


def _attribute(team: Team, league: League, raw_events: list[dict[str, Any]]) -> list[Game]:
    """The games the site would list on this team's page."""
    games = []
    for raw in raw_events:
        if not team_is_participant_as_any(team.match_names, raw, team.not_this_team):
            continue
        game = normalize_event(raw, league_slug=league.slug, tracked_team_slug=team.slug, tracked_team_name=team.name)
        if game is not None:
            games.append(game)
    return games


def _measure_team(
    client: DiscoveryClient, league: League, team: Team, today: date, upcoming_ids: set[str], all_ids: set[str]
) -> TeamCount:
    count = TeamCount(team=team.shown_name, keyword=team.name)
    if client.budget.requests_made >= MAX_REQUESTS:
        count.status = OVER_CAP
        return count
    try:
        raw_events, truncated = _search_team(client, league, team)
    except TicketmasterFetchError as exc:
        # The client has already redacted the key; GitHub also masks it.
        print(f"{league.slug}/{team.slug}: {exc}", file=sys.stderr)
        count.status = FAILED
        return count
    games = _attribute(team, league, raw_events)
    upcoming = [g for g in games if _is_upcoming(g, today)]
    count.events_returned = len(raw_events)
    count.attributed = len(games)
    count.attributed_upcoming = len(upcoming)
    count.home_games = sum(1 for g in upcoming if tracked_team_is_home(team, g) is True)
    count.truncated = truncated
    all_ids.update(g.event_id for g in games)
    upcoming_ids.update(g.event_id for g in upcoming)
    return count


def _measure_league_keyword(client: DiscoveryClient, cand: Candidate, result: CandidateCount) -> None:
    if cand.league_keyword is None:
        return
    if client.budget.requests_made >= MAX_REQUESTS:
        result.league_keyword_status = OVER_CAP
        return
    try:
        raw_events, _truncated = client.search_team_events(cand.league.slug, cand.league_keyword, ("US",))
    except TicketmasterFetchError as exc:
        print(f"{cand.league.slug} league keyword: {exc}", file=sys.stderr)
        result.league_keyword_status = FAILED
        return
    result.league_keyword_status = "measured"
    result.league_keyword_events = len(raw_events)
    result.league_keyword_attributed = sum(
        1 for raw in raw_events if any(_attribute(t, cand.league, [raw]) for t in cand.league.teams)
    )


def measure_candidate(client: DiscoveryClient, cand: Candidate, today: date) -> CandidateCount:
    upcoming_ids: set[str] = set()
    all_ids: set[str] = set()
    teams = [_measure_team(client, cand.league, t, today, upcoming_ids, all_ids) for t in cand.league.teams]
    result = CandidateCount(
        slug=cand.league.slug,
        name=cand.league.name,
        source=cand.source,
        teams=teams,
        unmeasured_teams=dict(cand.unmeasured_teams),
        league_keyword=cand.league_keyword,
        teams_total=len(teams) + len(cand.unmeasured_teams),
    )
    _measure_league_keyword(client, cand, result)
    measured = [t for t in teams if t.status == "measured"]
    if measured:
        result.unique_attributed = len(all_ids)
        result.unique_attributed_upcoming = len(upcoming_ids)
        result.teams_with_upcoming = sum(1 for t in measured if t.attributed_upcoming)
    result.complete = len(measured) == len(teams) and not cand.unmeasured_teams
    return result


def measure(
    client: DiscoveryClient, candidates: tuple[Candidate, ...], today: date, *, generated_at: datetime
) -> dict[str, Any]:
    results = [asdict(measure_candidate(client, c, today)) for c in candidates]
    return {
        "generated_at": generated_at.isoformat(),
        "counted_from": today.isoformat(),
        "source": "Ticketmaster Discovery API v2, the site's own search and attribution code",
        "requests_made": client.budget.requests_made,
        "bytes_received": client.budget.bytes_received,
        "candidates": results,
    }


def _cell(value: object) -> str:
    """A count, or a dash when it was not measured (never 0 for unknown)."""
    if value is None:
        return "–"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _candidate_markdown(c: dict[str, Any]) -> list[str]:
    measured = sum(1 for t in c["teams"] if t["status"] == "measured")
    lines = [
        f"## {c['name']}",
        "",
        f"Source: {c['source']}",
        "",
        f"- Teams measured: {measured} of {c['teams_total']}"
        + ("" if c["complete"] else " (incomplete: see the rows marked not measured)"),
        f"- Teams with at least one upcoming attributed event: {_cell(c['teams_with_upcoming'])}",
        f"- Unique attributed events: {_cell(c['unique_attributed'])},"
        f" upcoming: {_cell(c['unique_attributed_upcoming'])}",
    ]
    if c["league_keyword"]:
        status = c["league_keyword_status"]
        suffix = "" if status == "measured" else f" ({status})"
        lines.append(
            f'- League keyword "{c["league_keyword"]}": {_cell(c["league_keyword_events"])} events returned,'
            f" {_cell(c['league_keyword_attributed'])} attributable to a listed team{suffix}"
        )
    lines += [
        "",
        "| Team | Returned | Attributed | Upcoming | Home | Truncated | Status |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in c["teams"]:
        lines.append(
            f"| {t['team']} | {_cell(t['events_returned'])} | {_cell(t['attributed'])} |"
            f" {_cell(t['attributed_upcoming'])} | {_cell(t['home_games'])} | {_cell(t['truncated'])} | {t['status']} |"
        )
    for team, reason in c["unmeasured_teams"].items():
        lines.append(f"| {team} | – | – | – | – | – | not measured: {reason} |")
    lines.append("")
    return lines


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Candidate league measurement",
        "",
        f"Generated {report['generated_at']}. Upcoming means not dated before {report['counted_from']} (UTC).",
        f"{report['requests_made']} Discovery API requests, {report['bytes_received']} bytes.",
        "",
        "Counts only. Returned: events the keyword search returned. Attributed: events the site's participant"
        " check accepts for that team (what its page would list). Home: upcoming attributed events whose name"
        " says this team is at home. A dash means not measured, not zero. A team with 0 returned may have the"
        " wrong keyword.",
        "",
    ]
    for c in report["candidates"]:
        lines += _candidate_markdown(c)
    return "\n".join(lines)


def _select(arg: str) -> tuple[Candidate, ...]:
    if arg.strip() in ("", "all"):
        return CANDIDATES
    by_slug = {c.league.slug: c for c in CANDIDATES}
    wanted = [s.strip() for s in arg.split(",") if s.strip()]
    unknown = [s for s in wanted if s not in by_slug]
    if unknown:
        raise ValueError(f"unknown candidate(s): {', '.join(unknown)}; known: {', '.join(by_slug)}")
    return tuple(by_slug[s] for s in wanted)


def main(argv: list[str] | None = None, *, client: DiscoveryClient | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--out", type=Path, required=True, help="directory for measure.json and measure.md")
    parser.add_argument("--candidates", default="all", help="'all' or comma-separated slugs")
    args = parser.parse_args(argv)
    try:
        candidates = _select(args.candidates)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if client is None:
        api_key = os.environ.get("TICKETMASTER_API_KEY", "")
        if not api_key:
            print("TICKETMASTER_API_KEY is not set; nothing was measured.", file=sys.stderr)
            return 2
        client = DiscoveryClient(api_key)
    now = datetime.now(UTC).replace(microsecond=0)
    with client:
        report = measure(client, candidates, now.date(), generated_at=now)
    markdown = render_markdown(report)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "measure.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (args.out / "measure.md").write_text(markdown + "\n", encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(markdown + "\n")
    print(markdown)
    failed = any(t["status"] == FAILED for c in report["candidates"] for t in c["teams"]) or any(
        c["league_keyword_status"] == FAILED for c in report["candidates"]
    )
    # Every count is written either way; a failed fetch still fails the run.
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
