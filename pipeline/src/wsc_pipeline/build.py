"""Pipeline entrypoint: fetch -> normalize -> emit .ics + JSON + static site.

Exit code contract (checked by CI): 0 = a full site was written to --out.
With an API key that site is safe to publish; without one (degraded mode,
allowed only when --require-api-key is not given) nothing was fetched and
every page says so, and the deploy workflow never publishes it. Non-zero =
a fetch genuinely failed, found zero games across every tracked team, or
--require-api-key was given without a key; --out is not written and the
caller (GitHub Actions) must not deploy it -- Pages then keeps serving
whatever the last successful run published, which is the "a stale build is
never published as current" rule in practice: we never relabel an old or
broken build as today's, we just don't overwrite a good one with a bad one.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import UTC, date, datetime
from importlib.metadata import version as package_version
from pathlib import Path

from . import analytics, config, guard, ics, site, site_data, sitemap
from .coverage import BuildCoverage, compute_league_coverage, render_report
from .normalize import Game, normalize_event, team_is_participant, unique_by_event_id
from .ticketmaster import DiscoveryClient, TicketmasterFetchError

DEFAULT_BASE_URL = "https://nexthomegame.com"

# Favicon and Open Graph / Twitter card images: hand-authored SVG rendered
# to PNG by scripts/render_social_assets.py, committed here rather than
# regenerated on every build -- a normal (including nightly CI) build never
# needs rsvg-convert installed, it only copies already-rendered files. See
# that script's module docstring for the rendering pipeline and the
# contrast ratios checked for everything drawn into them.
ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"
STATIC_ASSET_FILES = (
    "favicon.svg",
    "favicon-32.png",
    "apple-touch-icon.png",
    "og-image.png",
    "og-image-wnba.png",
    "og-image-nwsl.png",
    "og-image-pwhl.png",
)
# Self-hosted webfonts (SIL OFL licensed, latin-subset .woff2 files
# committed under pipeline/assets/fonts/) -- never a Google Fonts <link>,
# since a third-party font request would contact Google on every page load,
# including for a visitor who sent Global Privacy Control or Do Not Track
# (the only thing that may contact Google is the guarded GA4 loader, see
# analytics.py). Copied into dist/fonts/ so site.STYLE_CSS's @font-face
# rules (url("/fonts/...")) resolve.
STATIC_FONT_FILES = (
    "big-shoulders-display-latin.woff2",
    "big-shoulders-text-latin.woff2",
    "public-sans-latin.woff2",
)


def fetch_all_games(api_key: str) -> tuple[list[Game], dict[str, set[str]], dict[str, set[str]], int, int]:
    """Returns (games, truncated_team_slugs_by_league,
    mismatched_team_slugs_by_league, requests_made, bytes_received).
    Raises TicketmasterFetchError on any failed team query -- callers must
    let this propagate so the build fails rather than publishing a partial,
    silently-thinned result as if it were complete.

    Every raw event Discovery API returns for a team's keyword search is
    checked with team_is_participant() before it is normalized: Discovery
    API's keyword search is a broad full-text match (confirmed in
    production to match on venue names, not just event/attraction names),
    so a raw result is not proof the event actually involves the team
    searched for. Events that fail the check are dropped, not published --
    same "never fabricate, drop rather than guess" discipline normalize_event
    already applies to a missing id/date -- and counted per team so the
    coverage report makes the exclusion visible instead of silent.
    """
    games: list[Game] = []
    truncated: dict[str, set[str]] = {lg.slug: set() for lg in config.LEAGUES}
    mismatched: dict[str, set[str]] = {lg.slug: set() for lg in config.LEAGUES}
    with DiscoveryClient(api_key) as client:
        for league, team in config.all_teams():
            raw_events, team_truncated = client.search_team_events(team.slug, team.name, league.country_codes)
            if team_truncated:
                truncated[league.slug].add(team.slug)
            for raw in raw_events:
                if not team_is_participant(team.name, raw, team.not_this_team):
                    mismatched[league.slug].add(team.slug)
                    continue
                game = normalize_event(
                    raw,
                    league_slug=league.slug,
                    tracked_team_slug=team.slug,
                    tracked_team_name=team.name,
                )
                if game is not None:
                    games.append(game)
        budget = client.budget
    if not games:
        # Every tracked team across every league at once coming back empty
        # is not an off-season (the five leagues' seasons never all pause
        # together) -- it is what a silently broken query or API change
        # looks like. Publishing it would empty every subscriber's
        # calendar as if there were no games, so it fails like any other
        # fetch failure and the last good deploy stays live.
        raise TicketmasterFetchError(
            f"0 games found across all {sum(len(lg.teams) for lg in config.LEAGUES)} "
            "tracked teams -- treated as a failed fetch, not as 'no games'"
        )
    return games, truncated, mismatched, budget.requests_made, budget.bytes_received


def build(
    *,
    out_dir: Path,
    base_url: str,
    api_key: str | None,
    affiliate_id: str | None,
    ga4_id: str | None = None,
    previous_state: dict[str, sitemap.PageState] | None = None,
    previous_publish: guard.PreviousPublish | None = None,
    now: datetime | None = None,
) -> BuildCoverage:
    """Fetches and writes to a temp directory first, then atomically
    replaces --out only on full success. A fetch failure raises before the
    temp directory ever becomes --out, so an existing good --out (e.g. a
    previous local build) is left untouched rather than overwritten with a
    partial one -- the same "never publish a stale/broken build as current"
    rule the GitHub Actions workflow applies at the deploy step.

    ga4_id reaches the HTML pages only (analytics.py): the .ics feeds and
    data/*.json are written without it, so they are byte-identical whether
    or not an ID is set. None or "" emits no analytics at all; a malformed
    ID raises ValueError here, before anything is fetched or written.

    previous_state is the live site's lastmod.json (main() reads it;
    sitemap.py has the rules): what each page's sitemap <lastmod> is
    carried over from. None means no history, so no schedule page gets a
    lastmod -- never the build time in its place.
    """
    ga4_id = analytics.measurement_id(ga4_id)
    api_key_present = bool(api_key)
    if api_key:
        games, truncated, mismatched, requests_made, bytes_received = fetch_all_games(api_key)  # may raise
    else:
        games, truncated, mismatched, requests_made, bytes_received = [], {}, {}, 0, 0
    # When the listings were read (DATA-GOVERNANCE-STANDARD DG-02). None when
    # nothing was fetched: a degraded build states no fetch time at all.
    # Whole seconds, everywhere it is published: the page's <time datetime>
    # allows at most three fractional digits (the 2026-09-18 nightly deploy
    # failed on six, #37), and it is also every changed page's sitemap
    # <lastmod>, which validate_seo holds to whole seconds.
    fetched_at = (now or datetime.now(UTC)).replace(microsecond=0) if api_key_present else None
    guard_report: guard.GuardReport | None = None
    if fetched_at is not None:
        if previous_publish is None:
            guard_report = guard.not_compared("the previous publish was not read")
        else:
            guard_report = guard.evaluate(previous_publish, games, truncated, now=fetched_at)
            if guard_report.refused:
                raise guard.PublishRefused(guard_report)

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
        lc = compute_league_coverage(
            lg, games_by_league[lg.slug], truncated.get(lg.slug, set()), mismatched.get(lg.slug, set())
        )
        league_coverages.append(lc)

    coverage = BuildCoverage(
        leagues=league_coverages,
        requests_made=requests_made,
        bytes_received=bytes_received,
        api_key_present=api_key_present,
        publish_guard=guard_report,
    )

    _write_ics(tmp_dir, base_url, games_by_league, api_key_present)
    fingerprints = _write_data(tmp_dir, base_url, games_by_league, api_key_present, truncated, fetched_at=fetched_at)
    _write_html(tmp_dir, base_url, games_by_league, api_key_present, truncated, ga4_id, fetched_at=fetched_at)
    _write_static(tmp_dir)
    state = sitemap.next_state(fingerprints, previous_state, fetched_at)
    _write_sitemap_and_robots(tmp_dir, base_url, state)
    _write_version(tmp_dir, fetched_at)

    (tmp_dir / "COVERAGE.txt").write_text(render_report(coverage) + "\n", encoding="utf-8")

    if out_dir.exists():
        shutil.rmtree(out_dir)
    tmp_dir.rename(out_dir)
    return coverage


def _write_ics(out_dir: Path, base_url: str, games_by_league: dict[str, list[Game]], fetched: bool) -> None:
    for lg in config.LEAGUES:
        games = games_by_league[lg.slug]
        cal = ics.league_calendar(lg.slug, lg.name, games, fetched=fetched, base_url=base_url)
        (out_dir / "ics" / f"{lg.slug}.ics").write_bytes(cal.to_ical())
        team_dir = out_dir / "ics" / lg.slug
        team_dir.mkdir(exist_ok=True)
        for team in lg.teams:
            team_cal = ics.team_calendar(
                team.slug, team.name, games, fetched=fetched, base_url=base_url, league_slug=lg.slug
            )
            (team_dir / f"{team.slug}.ics").write_bytes(team_cal.to_ical())


def _write_data(
    out_dir: Path,
    base_url: str,
    games_by_league: dict[str, list[Game]],
    api_key_present: bool,
    truncated: dict[str, set[str]],
    *,
    fetched_at: datetime | None = None,
) -> dict[str, str]:
    """Writes data/*.json and returns each schedule page's fingerprint
    (sitemap.fingerprint), keyed by its site path: the league and team
    pages render from exactly these payloads, and the home page from the
    per-league counts in site.json."""
    data_dir = out_dir / "data"
    provenance = site_data.provenance(fetched_at)
    fingerprints: dict[str, str] = {}
    for lg in config.LEAGUES:
        games = games_by_league[lg.slug]
        incomplete = truncated.get(lg.slug, set())
        payload = site_data.league_data(lg, games, fetched=api_key_present, possibly_incomplete_teams=incomplete)
        fingerprints[f"/{lg.slug}/"] = sitemap.fingerprint(payload)
        payload.update(provenance)
        (data_dir / f"{lg.slug}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        team_dir = data_dir / lg.slug
        team_dir.mkdir(exist_ok=True)
        for team in lg.teams:
            team_payload = site_data.team_data(
                team, lg, games, fetched=api_key_present, possibly_incomplete=team.slug in incomplete
            )
            fingerprints[f"/{lg.slug}/{team.slug}/"] = sitemap.fingerprint(team_payload)
            team_payload.update(provenance)
            (team_dir / f"{team.slug}.json").write_text(json.dumps(team_payload, indent=2), encoding="utf-8")

    summary = site_data.site_summary(
        list(config.LEAGUES),
        games_by_league,
        api_key_present=api_key_present,
        not_included=list(config.LEAGUES_EXAMINED_NOT_INCLUDED),
    )
    fingerprints["/"] = sitemap.fingerprint({"leagues": summary["leagues"]})
    summary.update(provenance)
    (data_dir / "site.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return fingerprints


def _write_html(
    out_dir: Path,
    base_url: str,
    games_by_league: dict[str, list[Game]],
    api_key_present: bool,
    truncated: dict[str, set[str]],
    ga4_id: str | None,
    *,
    fetched_at: datetime | None = None,
) -> None:
    leagues_summary = [
        {
            "slug": lg.slug,
            "name": lg.name,
            # None, not 0, when nothing was fetched: "0 upcoming games" would
            # state a fact this build never checked.
            "games_count": len(unique_by_event_id(games_by_league[lg.slug])) if api_key_present else None,
        }
        for lg in config.LEAGUES
    ]
    (out_dir / "index.html").write_text(
        site.render_index(
            leagues=leagues_summary,
            not_included=list(config.LEAGUES_EXAMINED_NOT_INCLUDED),
            base_url=base_url,
            ga4_id=ga4_id,
        ),
        encoding="utf-8",
    )
    (out_dir / "404.html").write_text(
        site.render_not_found(leagues=leagues_summary, base_url=base_url, ga4_id=ga4_id), encoding="utf-8"
    )
    privacy_dir = out_dir / "privacy"
    privacy_dir.mkdir(exist_ok=True)
    (privacy_dir / "index.html").write_text(site.render_privacy(base_url=base_url, ga4_id=ga4_id), encoding="utf-8")
    accessibility_dir = out_dir / "accessibility"
    accessibility_dir.mkdir(exist_ok=True)
    (accessibility_dir / "index.html").write_text(
        site.render_accessibility(base_url=base_url, ga4_id=ga4_id), encoding="utf-8"
    )

    for lg in config.LEAGUES:
        games = games_by_league[lg.slug]
        incomplete = truncated.get(lg.slug, set())
        league_payload = site_data.league_data(lg, games, fetched=api_key_present, possibly_incomplete_teams=incomplete)
        league_payload.update(site_data.provenance(fetched_at))
        league_dir = out_dir / lg.slug
        league_dir.mkdir(exist_ok=True)
        (league_dir / "index.html").write_text(
            site.render_league(league=league_payload, base_url=base_url, ga4_id=ga4_id), encoding="utf-8"
        )
        for team in lg.teams:
            team_payload = site_data.team_data(
                team, lg, games, fetched=api_key_present, possibly_incomplete=team.slug in incomplete
            )
            team_payload.update(site_data.provenance(fetched_at))
            team_dir = league_dir / team.slug
            team_dir.mkdir(exist_ok=True)
            (team_dir / "index.html").write_text(
                site.render_team(team=team_payload, base_url=base_url, ga4_id=ga4_id), encoding="utf-8"
            )


def _write_static(out_dir: Path) -> None:
    (out_dir / "style.css").write_text(site.STYLE_CSS, encoding="utf-8")
    for name in STATIC_ASSET_FILES:
        src = ASSETS_DIR / name
        if not src.is_file():
            raise FileNotFoundError(
                f"missing static asset {src} -- run "
                "`uv run python scripts/render_social_assets.py` and commit its output"
            )
        shutil.copyfile(src, out_dir / name)

    fonts_dir = out_dir / "fonts"
    fonts_dir.mkdir(exist_ok=True)
    for name in STATIC_FONT_FILES:
        src = ASSETS_DIR / "fonts" / name
        if not src.is_file():
            raise FileNotFoundError(f"missing static font {src} -- see pipeline/assets/fonts/")
        shutil.copyfile(src, fonts_dir / name)


def _write_sitemap_and_robots(out_dir: Path, base_url: str, state: dict[str, sitemap.PageState]) -> None:
    """sitemap.xml (every indexable page; the 404 is not one), robots.txt,
    and lastmod.json, the state the next build compares against."""
    entries: list[tuple[str, str | date | None]] = [
        ("/", state["/"].changed_at),
        (site.PRIVACY_PATH, site.PRIVACY_UPDATED),
        (site.ACCESSIBILITY_PATH, site.ACCESSIBILITY_UPDATED),
    ]
    for lg in config.LEAGUES:
        entries.append((f"/{lg.slug}/", state[f"/{lg.slug}/"].changed_at))
        for team in lg.teams:
            path = f"/{lg.slug}/{team.slug}/"
            entries.append((path, state[path].changed_at))
    (out_dir / "sitemap.xml").write_text(sitemap.render_sitemap(base_url, entries), encoding="utf-8")
    (out_dir / "robots.txt").write_text(sitemap.render_robots(base_url), encoding="utf-8")
    (out_dir / sitemap.STATE_PATH).write_text(sitemap.render_state(state), encoding="utf-8")


def _write_version(out_dir: Path, fetched_at: datetime | None) -> None:
    """dist/version.json: which source commit and pipeline version built the
    live site, and when (RELEASE-AND-VERSIONING-STANDARD §5.3 build stamp).
    `commit` is GITHUB_SHA in Actions and null elsewhere, never a guess.
    scripts/check_live_freshness.py reads `fetched_at` to raise the
    staleness alarm."""
    stamp = {
        "commit": os.environ.get("GITHUB_SHA") or None,
        "pipeline_version": package_version("wsc-pipeline"),
        "built_at": datetime.now(UTC).isoformat(),
        **site_data.provenance(fetched_at),
    }
    (out_dir / "version.json").write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="dist", type=Path)
    parser.add_argument("--base-url", default=os.environ.get("SITE_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument(
        "--require-api-key",
        action="store_true",
        help=(
            "fail instead of building in degraded (no-key) mode. The deploy "
            "workflow passes this: a no-key build has fetched nothing, and "
            "publishing its empty calendars would empty every subscriber's "
            "calendar as if there were no games."
        ),
    )
    args = parser.parse_args(argv)

    api_key = os.environ.get("TICKETMASTER_API_KEY") or None
    if args.require_api_key and not api_key:
        print(
            "BUILD FAILED: --require-api-key was given but TICKETMASTER_API_KEY "
            "is not set. Nothing was fetched, so nothing was written to --out; "
            "an unfetched build is never published as a real schedule.",
            file=sys.stderr,
        )
        return 1
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

    ga4_id = analytics.GA4_MEASUREMENT_ID
    if not ga4_id:
        print(
            "NOTE: analytics.GA4_MEASUREMENT_ID is empty, so no page carries "
            "Google Analytics and the privacy copy says the site runs none. "
            "Set it in pipeline/src/wsc_pipeline/analytics.py once the GA4 "
            "property exists (DECISIONS 0012).",
            file=sys.stderr,
        )

    # The live site's own record of when each page last changed (sitemap.py).
    # Read only for a build that will fetch listings: a degraded build
    # records no dates, so it has nothing to compare.
    previous_state = sitemap.fetch_previous_state(args.base_url) if api_key else None
    # And, for the publish guard, what each team's page data said last night.
    previous_publish = guard.fetch_previous_publish(args.base_url) if api_key else None

    try:
        coverage = build(
            out_dir=args.out,
            base_url=args.base_url,
            api_key=api_key,
            affiliate_id=affiliate_id,
            ga4_id=ga4_id,
            previous_state=previous_state,
            previous_publish=previous_publish,
        )
    except TicketmasterFetchError as exc:
        print(f"BUILD FAILED: {exc}", file=sys.stderr)
        print("A failed fetch fails the build; nothing was published to --out.", file=sys.stderr)
        return 1
    except guard.PublishRefused as exc:
        print(f"BUILD FAILED: {exc}", file=sys.stderr)
        if os.environ.get("GITHUB_ACTIONS") == "true":
            for violation in exc.report.violations:
                print(f"::error title=Publish guard refused the build::{violation.message}", file=sys.stderr)
        return 1

    if coverage.publish_guard is not None:
        guard.announce(coverage.publish_guard, github_actions=os.environ.get("GITHUB_ACTIONS") == "true")
    print(render_report(coverage))
    fallback_count = sum(len(lc.zone_fallbacks) for lc in coverage.leagues)
    if fallback_count:
        # Also on stderr (and as a workflow annotation in Actions), so a bad
        # venue time zone is noticed in the run log, not only in COVERAGE.txt.
        message = (
            f"{fallback_count} game(s) were written to the calendars with a UTC start because their venue "
            "time zone is missing or unrecognized; see COVERAGE.txt for which"
        )
        print(f"WARNING: {message}", file=sys.stderr)
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print(f"::warning title=Unknown venue time zone::{message}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
