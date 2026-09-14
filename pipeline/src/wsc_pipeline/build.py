"""Pipeline entrypoint: fetch -> normalize -> emit .ics + JSON + static site.

Exit code contract (checked by CI): 0 = a full site was written to --out and
is safe to publish, including the degraded no-API-key mode. Non-zero = a
fetch genuinely failed; --out is not written (or is left incomplete) and the
caller (GitHub Actions) must not deploy it -- Pages then keeps serving
whatever the last successful run published, which is the "a stale build is
never published as current" rule in practice: we never relabel an old or
broken build as today's, we just don't overwrite a good one with a bad one.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from . import config, ics, site, site_data
from .coverage import BuildCoverage, LeagueCoverage, compute_league_coverage, render_report
from .normalize import Game, normalize_event
from .ticketmaster import DiscoveryClient, TicketmasterFetchError

DEFAULT_BASE_URL = "https://calendar.chelseakr.com"


def fetch_all_games(api_key: str) -> tuple[list[Game], dict[str, set[str]], int, int]:
    """Returns (games, truncated_team_slugs_by_league, requests_made, bytes_received).
    Raises TicketmasterFetchError on any failed team query -- callers must
    let this propagate so the build fails rather than publishing a partial,
    silently-thinned result as if it were complete.
    """
    games: list[Game] = []
    truncated: dict[str, set[str]] = {lg.slug: set() for lg in config.LEAGUES}
    with DiscoveryClient(api_key) as client:
        for league, team in config.all_teams():
            raw_events, team_truncated = client.search_team_events(team.slug, team.name, league.country_codes)
            if team_truncated:
                truncated[league.slug].add(team.slug)
            for raw in raw_events:
                game = normalize_event(
                    raw,
                    league_slug=league.slug,
                    tracked_team_slug=team.slug,
                    tracked_team_name=team.name,
                )
                if game is not None:
                    games.append(game)
        budget = client.budget
    return games, truncated, budget.requests_made, budget.bytes_received


def build(*, out_dir: Path, base_url: str, api_key: str | None, affiliate_id: str | None) -> BuildCoverage:
    """Fetches and writes to a temp directory first, then atomically
    replaces --out only on full success. A fetch failure raises before the
    temp directory ever becomes --out, so an existing good --out (e.g. a
    previous local build) is left untouched rather than overwritten with a
    partial one -- the same "never publish a stale/broken build as current"
    rule the GitHub Actions workflow applies at the deploy step.
    """
    api_key_present = bool(api_key)
    if api_key_present:
        games, truncated, requests_made, bytes_received = fetch_all_games(api_key)  # may raise
    else:
        games, truncated, requests_made, bytes_received = [], {}, 0, 0

    tmp_dir = out_dir.with_name(out_dir.name + ".tmp")
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True)
    (tmp_dir / "ics").mkdir()
    (tmp_dir / "data").mkdir()

    games_by_league: dict[str, list[Game]] = {lg.slug: [] for lg in config.LEAGUES}
    for g in games:
        games_by_league[g.league_slug].append(g)

    league_coverages = []
    for lg in config.LEAGUES:
        lc = compute_league_coverage(lg, games_by_league[lg.slug], truncated.get(lg.slug, set()))
        league_coverages.append(lc)

    coverage = BuildCoverage(
        leagues=league_coverages,
        requests_made=requests_made,
        bytes_received=bytes_received,
        api_key_present=api_key_present,
    )

    _write_ics(tmp_dir, games_by_league)
    _write_data(tmp_dir, base_url, games_by_league, api_key_present)
    _write_html(tmp_dir, base_url, games_by_league, api_key_present)
    _write_static(tmp_dir)
    _write_sitemap_and_robots(tmp_dir, base_url)

    (tmp_dir / "COVERAGE.txt").write_text(render_report(coverage) + "\n", encoding="utf-8")

    if out_dir.exists():
        shutil.rmtree(out_dir)
    tmp_dir.rename(out_dir)
    return coverage


def _write_ics(out_dir: Path, games_by_league: dict[str, list[Game]]) -> None:
    for lg in config.LEAGUES:
        games = games_by_league[lg.slug]
        cal = ics.league_calendar(lg.slug, lg.name, games)
        (out_dir / "ics" / f"{lg.slug}.ics").write_bytes(cal.to_ical())
        team_dir = out_dir / "ics" / lg.slug
        team_dir.mkdir(exist_ok=True)
        for team in lg.teams:
            team_cal = ics.team_calendar(team.slug, team.name, games)
            (team_dir / f"{team.slug}.ics").write_bytes(team_cal.to_ical())


def _write_data(out_dir: Path, base_url: str, games_by_league: dict[str, list[Game]], api_key_present: bool) -> None:
    import json

    data_dir = out_dir / "data"
    for lg in config.LEAGUES:
        games = games_by_league[lg.slug]
        payload = site_data.league_data(lg, games)
        (data_dir / f"{lg.slug}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        team_dir = data_dir / lg.slug
        team_dir.mkdir(exist_ok=True)
        for team in lg.teams:
            team_payload = site_data.team_data(team, lg, games)
            (team_dir / f"{team.slug}.json").write_text(json.dumps(team_payload, indent=2), encoding="utf-8")

    summary = site_data.site_summary(
        list(config.LEAGUES),
        games_by_league,
        api_key_present=api_key_present,
        not_included=list(config.LEAGUES_EXAMINED_NOT_INCLUDED),
    )
    (data_dir / "site.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def _write_html(out_dir: Path, base_url: str, games_by_league: dict[str, list[Game]], api_key_present: bool) -> None:
    leagues_summary = [
        {"slug": lg.slug, "name": lg.name, "games_count": len(games_by_league[lg.slug])}
        for lg in config.LEAGUES
    ]
    (out_dir / "index.html").write_text(
        site.render_index(
            leagues=leagues_summary,
            not_included=list(config.LEAGUES_EXAMINED_NOT_INCLUDED),
            base_url=base_url,
        ),
        encoding="utf-8",
    )

    for lg in config.LEAGUES:
        games = games_by_league[lg.slug]
        league_payload = site_data.league_data(lg, games)
        league_dir = out_dir / lg.slug
        league_dir.mkdir(exist_ok=True)
        (league_dir / "index.html").write_text(
            site.render_league(league=league_payload, base_url=base_url), encoding="utf-8"
        )
        for team in lg.teams:
            team_payload = site_data.team_data(team, lg, games)
            team_dir = league_dir / team.slug
            team_dir.mkdir(exist_ok=True)
            (team_dir / "index.html").write_text(
                site.render_team(team=team_payload, base_url=base_url), encoding="utf-8"
            )


def _write_static(out_dir: Path) -> None:
    (out_dir / "style.css").write_text(site.STYLE_CSS, encoding="utf-8")


def _write_sitemap_and_robots(out_dir: Path, base_url: str) -> None:
    urls = [f"{base_url}/"]
    for lg in config.LEAGUES:
        urls.append(f"{base_url}/{lg.slug}/")
        for team in lg.teams:
            urls.append(f"{base_url}/{lg.slug}/{team.slug}/")
    body = "\n".join(f"  <url><loc>{u}</loc></url>" for u in urls)
    sitemap = f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{body}\n</urlset>\n'
    (out_dir / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    (out_dir / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {base_url}/sitemap.xml\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="dist", type=Path)
    parser.add_argument("--base-url", default=os.environ.get("SITE_BASE_URL", DEFAULT_BASE_URL))
    args = parser.parse_args(argv)

    api_key = os.environ.get("TICKETMASTER_API_KEY") or None
    affiliate_id = os.environ.get("TICKETMASTER_AFFILIATE_ID") or None
    if not affiliate_id:
        print(
            "NOTE: TICKETMASTER_AFFILIATE_ID not set. Per "
            "docs/LICENSES-AND-ATTRIBUTION.md §3, Ticketmaster applies "
            "affiliate tracking to event URLs automatically once the "
            "Impact publisher ID is configured in the Ticketmaster "
            "developer account (a one-time console step, not a build-time "
            "one) -- this build does not construct or guess an affiliate "
            "URL format itself.",
            file=sys.stderr,
        )

    try:
        coverage = build(out_dir=args.out, base_url=args.base_url, api_key=api_key, affiliate_id=affiliate_id)
    except TicketmasterFetchError as exc:
        print(f"BUILD FAILED: {exc}", file=sys.stderr)
        print("A failed fetch fails the build; nothing was published to --out.", file=sys.stderr)
        return 1

    print(render_report(coverage))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
