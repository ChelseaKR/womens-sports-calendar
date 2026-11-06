"""Pipeline entrypoint: fetch -> normalize -> emit .ics + JSON + static site.

Exit code contract (checked by CI): 0 = a full site was written to --out.
With an API key that site is safe to publish; without one (degraded mode,
allowed only when --require-api-key is not given) nothing was fetched and
every page says so, and the deploy workflow never publishes it. Non-zero =
a fetch genuinely failed, found zero games across every tracked team, was
refused by the publish guard (guard.py: it would take a league's or a team's
upcoming games out of subscribers' calendars), or --require-api-key was given without a key; --out is not written and the
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
from collections.abc import Iterable
from datetime import UTC, date, datetime
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any

from . import (
    analytics,
    config,
    feeds,
    guard,
    history,
    ics,
    indexnow,
    listings,
    llms,
    sellers,
    site,
    site_data,
    sitemap,
)
from .coverage import BuildCoverage, compute_league_coverage, render_report
from .normalize import Game, event_names_college_team, event_names_team, normalize_event, unique_by_event_id
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


def _search_team(
    client: DiscoveryClient, league: config.League, team: config.Team
) -> tuple[list[dict[str, Any]], bool]:
    """Every raw event for a team: the search under its Ticketmaster keyword
    (`name`), then one more search per `search_names` entry, each counted in
    the crawl budget. An event several searches return is kept once."""
    events: list[dict[str, Any]] = []
    seen: set[object] = set()
    truncated = False
    for name in team.all_names:
        found, cut_short = client.search_team_events(team.slug, name, league.country_codes)
        truncated = truncated or cut_short
        for raw in found:
            if raw.get("id") in seen:
                continue
            seen.add(raw.get("id"))
            events.append(raw)
    return events, truncated


def attribute_games(
    leagues: Iterable[config.League], raw_by_team: dict[tuple[str, str], list[dict[str, Any]]]
) -> tuple[list[Game], dict[str, set[str]]]:
    """(games, mismatched team slugs by league) from each team's raw search
    results ({(league slug, team slug): raw events}).

    Every event any of a league's searches returned is tested against every
    team in that league (normalize.event_names_team), and becomes a Game for
    each team it names. A game used to be filed only under the team whose search returned it, so
    a game only the opponent's search found never reached the team's own
    page: Ticketmaster names a school differently at each host venue ("Penn
    State Lady Lion Basketball vs. Rutgers", "Northwestern ... vs. Indiana
    University Womens Basketball"), and the live build of 2026-11-05 listed
    43 such games in the league feeds but not on 14 college teams' own pages
    and feeds. An event another league's search returned counts only
    through the strict college rule (Vanderbilt, SEC, at Iowa, Big Ten, was
    found only by Iowa's search). This costs no requests. A team's slug is
    in `mismatched` when its own search returned an event that names none of
    its names, as before."""
    leagues = tuple(leagues)
    pools, mismatched = _league_pools(leagues, raw_by_team)
    games: list[Game] = []
    for league in leagues:
        for team in league.teams:
            for raw in _events_naming(team, league, pools):
                game = normalize_event(
                    raw,
                    league_slug=league.slug,
                    tracked_team_slug=team.slug,
                    tracked_team_name=team.name,
                )
                if game is not None:
                    games.append(game)
    return games, mismatched


def _league_pools(
    leagues: tuple[config.League, ...], raw_by_team: dict[tuple[str, str], list[dict[str, Any]]]
) -> tuple[dict[str, dict[object, dict[str, Any]]], dict[str, set[str]]]:
    """({league slug: every event its searches returned, once, by id},
    {league slug: slugs of teams whose own search returned an event that
    names none of their names})."""
    pools: dict[str, dict[object, dict[str, Any]]] = {lg.slug: {} for lg in leagues}
    mismatched: dict[str, set[str]] = {lg.slug: set() for lg in leagues}
    for league in leagues:
        for team in league.teams:
            for raw in raw_by_team.get((league.slug, team.slug), []):
                event_id = raw.get("id")
                pools[league.slug].setdefault(event_id if event_id else object(), raw)
                if not event_names_team(team, raw):
                    mismatched[league.slug].add(team.slug)
    return pools, mismatched


def _events_naming(
    team: config.Team, league: config.League, pools: dict[str, dict[object, dict[str, Any]]]
) -> list[dict[str, Any]]:
    """The events that are this team's games: any in its own league's pool
    that names it (event_names_team), and any in another league's pool whose
    side is this school's own women's team (event_names_college_team). A bare
    "vs. Washington" from another league is not the Washington Mystics."""
    matched = {key: raw for key, raw in pools[league.slug].items() if event_names_team(team, raw)}
    if team.school is not None:
        for slug, pool in pools.items():
            if slug == league.slug:
                continue
            for key, raw in pool.items():
                if key not in matched and event_names_college_team(team, raw):
                    matched[key] = raw
    return list(matched.values())


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
    truncated: dict[str, set[str]] = {lg.slug: set() for lg in config.LEAGUES}
    raw_by_team: dict[tuple[str, str], list[dict[str, Any]]] = {}
    with DiscoveryClient(api_key) as client:
        for league, team in config.all_teams():
            raw_by_team[(league.slug, team.slug)], team_truncated = _search_team(client, league, team)
            if team_truncated:
                truncated[league.slug].add(team.slug)
        games, mismatched = attribute_games(config.LEAGUES, raw_by_team)
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

    ga4_id reaches the HTML pages only (analytics.py): the .ics feeds,
    data/site.json and the page records are written without it, so they are byte-identical whether
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
    # Every event Ticketmaster lists tonight, before this build's own rules
    # leave any out: a played game is kept in the feeds only once Ticketmaster
    # no longer lists it (history.py), never because a rule here dropped it.
    listed_event_ids = frozenset(g.event_id for g in games)
    # An event named in config.REMOVED_EVENTS is withheld from every page,
    # feed and data file, even while Ticketmaster still lists it: the
    # Ticketmaster terms' removal within 24 hours on request (ADR 0006). The
    # publish guard below then reports it as an accepted removal.
    games = without_removed_events(games)
    # Listings that are not one of the team's games (a season-ticket product,
    # a men's game, a doubleheader listed again beside the team's own game)
    # are left out of every page, feed and data file, and named in
    # COVERAGE.txt (listings.py).
    games, dropped_listings = listings.only_games(games)
    # A team's game whose opponent Ticketmaster named with another sport's
    # word ("Northern Colorado Bears Football" at a women's basketball game)
    # is shown without that word, and named in COVERAGE.txt (listings.py).
    games, relabeled_listings = listings.fix_opponent_sport(games)
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
    feed_history = _feed_history(previous_publish, listed_event_ids, fetched_at)

    tmp_dir = out_dir.with_name(out_dir.name + ".tmp")
    # Each page's payload, kept beside the site and never deployed
    # (site_data.records_dir, DECISIONS 0024). Written and swapped in with
    # the site, so the two always come from one build.
    records = site_data.records_dir(out_dir)
    tmp_records = records.with_name(records.name + ".tmp")
    _empty_dir(tmp_dir)
    _empty_dir(tmp_records)
    (tmp_dir / "ics").mkdir()
    (tmp_dir / "data").mkdir()

    games_by_league: dict[str, list[Game]] = {lg.slug: [] for lg in config.LEAGUES}
    for g in games:
        games_by_league[g.league_slug].append(g)

    league_coverages = []
    for lg in config.LEAGUES:
        lc = compute_league_coverage(
            lg,
            games_by_league[lg.slug],
            truncated.get(lg.slug, set()),
            mismatched.get(lg.slug, set()),
            dropped=[d for d in dropped_listings if d.league_slug == lg.slug],
            relabeled=[r for r in relabeled_listings if r.league_slug == lg.slug],
        )
        league_coverages.append(lc)

    coverage = BuildCoverage(
        leagues=league_coverages,
        requests_made=requests_made,
        bytes_received=bytes_received,
        api_key_present=api_key_present,
        publish_guard=guard_report,
    )

    _write_ics(tmp_dir, base_url, games_by_league, api_key_present, dtstamp=fetched_at, feed_history=feed_history)
    _write_combined_ics(
        tmp_dir, base_url, games_by_league, api_key_present, dtstamp=fetched_at, feed_history=feed_history
    )
    fingerprints = _write_data(
        tmp_dir,
        tmp_records,
        base_url,
        games_by_league,
        api_key_present,
        truncated,
        fetched_at=fetched_at,
        feed_history=feed_history,
    )
    # A Ticketmaster event URL can arrive already wrapped in Impact affiliate
    # tracking (docs/LICENSES-AND-ATTRIBUTION.md §3): the pages then label it
    # as a paid link and turn the disclosure on (DECISIONS 0018). The feeds
    # and each page record's `ticket_url` carry the unwrapped address either way.
    paid_links = sellers.any_paid_buy_link(games)
    atom_feeds = feeds.build_feeds(games_by_league, base_url=base_url, fetched=api_key_present)
    feeds_dir = tmp_dir / feeds.FEEDS_DIR
    feeds_dir.mkdir()
    for key, text in atom_feeds.items():
        (tmp_dir / feeds.feed_path(key)).write_text(text, encoding="utf-8")
    (tmp_dir / "llms.txt").write_text(llms.render(base_url=base_url, feed_keys=atom_feeds), encoding="utf-8")
    _write_html(
        tmp_dir,
        base_url,
        games_by_league,
        api_key_present,
        truncated,
        ga4_id,
        fetched_at=fetched_at,
        paid_links=paid_links,
        feed_keys=frozenset(atom_feeds),
    )
    _write_static(tmp_dir, paid_links=paid_links)
    state = sitemap.next_state(fingerprints, previous_state, fetched_at)
    unlisted = _pages_kept_out_of_search(games_by_league, api_key_present, truncated)
    _write_sitemap_and_robots(tmp_dir, base_url, state, unlisted=unlisted)
    _write_version(tmp_dir, fetched_at)

    (tmp_dir / "COVERAGE.txt").write_text(render_report(coverage) + "\n", encoding="utf-8")

    _replace_dir(tmp_dir, out_dir)
    _replace_dir(tmp_records, records)
    return coverage


def _empty_dir(path: Path) -> None:
    """A new, empty directory at path, removing whatever was there."""
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def _replace_dir(built: Path, final: Path) -> None:
    """Moves a finished build directory into place over the previous one."""
    if final.exists():
        shutil.rmtree(final)
    built.rename(final)


def _feed_history(
    previous_publish: guard.PreviousPublish | None, listed_event_ids: frozenset[str], fetched_at: datetime | None
) -> history.FeedHistory:
    """What this build carries over from the previous publish's feeds
    (history.py): nothing when it fetched nothing or did not read them."""
    if fetched_at is None or previous_publish is None or not previous_publish.feeds:
        return history.FeedHistory()
    return history.from_previous(
        previous_publish.feeds,
        complete=previous_publish.fully_read,
        listed_event_ids=listed_event_ids,
        removed_event_ids=frozenset(r.event_id for r in config.REMOVED_EVENTS),
        now=fetched_at,
    )


def _kept_ids(feed_history: history.FeedHistory, feed_path: str) -> list[str]:
    """The event ids of the played games a feed keeps, for its page record
    (validate_ics checks the feed against it)."""
    return [event_id for e in feed_history.kept_in(feed_path) if (event_id := history.event_id_of(e))]


def without_removed_events(games: list[Game], removals: tuple[config.EventRemoval, ...] | None = None) -> list[Game]:
    """`games` without any event config.REMOVED_EVENTS names (or `removals`,
    for a test). An event id is matched exactly; nothing else is dropped."""
    removed = {r.event_id for r in (config.REMOVED_EVENTS if removals is None else removals)}
    return [g for g in games if g.event_id not in removed]


def _write_ics(
    out_dir: Path,
    base_url: str,
    games_by_league: dict[str, list[Game]],
    fetched: bool,
    *,
    dtstamp: datetime | None,
    feed_history: history.FeedHistory | None = None,
) -> None:
    """dtstamp is the build's fetch time (None only when nothing was fetched,
    so no event is written to stamp): every event's DTSTAMP, the same in
    every feed of one build. feed_history is the played games each feed
    keeps and the revision numbering (history.py)."""
    feed_history = feed_history or history.FeedHistory()
    for lg in config.LEAGUES:
        games = games_by_league[lg.slug]
        duration = config.estimated_duration(lg)
        cal = ics.league_calendar(
            lg.slug,
            lg.name,
            games,
            fetched=fetched,
            base_url=base_url,
            dtstamp=dtstamp,
            game_duration=duration,
            kept=feed_history.kept_in(f"ics/{lg.slug}.ics"),
            revise=feed_history.revisions,
        )
        (out_dir / "ics" / f"{lg.slug}.ics").write_bytes(cal.to_ical())
        team_dir = out_dir / "ics" / lg.slug
        team_dir.mkdir(exist_ok=True)
        for team in lg.teams:
            team_cal = ics.team_calendar(
                team.slug,
                team.shown_name,
                games,
                fetched=fetched,
                base_url=base_url,
                league_slug=lg.slug,
                dtstamp=dtstamp,
                game_duration=duration,
                kept=feed_history.kept_in(f"ics/{lg.slug}/{team.slug}.ics"),
                revise=feed_history.revisions,
            )
            feed = team_cal.to_ical()
            (team_dir / f"{team.slug}.ics").write_bytes(feed)
            # The same feed at every path this team used to have: a static
            # host cannot redirect an .ics request, and a subscriber's app
            # holds the old URL. Same bytes, so same UIDs and the same
            # `URL` (the current page).
            for former in team.former_slugs:
                (team_dir / f"{former}.ics").write_bytes(feed)


def _write_combined_ics(
    out_dir: Path,
    base_url: str,
    games_by_league: dict[str, list[Game]],
    fetched: bool,
    *,
    dtstamp: datetime | None,
    feed_history: history.FeedHistory | None = None,
) -> None:
    """ics/all.ics: every league's events in one feed, each exactly as its
    league feed has it (same UID), so a subscriber of both never gets a game
    twice under two UIDs. Its played games are the league feeds' kept ones."""
    feed_history = feed_history or history.FeedHistory()
    combined = ics.combined_calendar(
        [(lg.slug, games_by_league[lg.slug], config.estimated_duration(lg)) for lg in config.LEAGUES],
        fetched=fetched,
        base_url=base_url,
        dtstamp=dtstamp,
        kept=[(lg.slug, feed_history.kept_in(f"ics/{lg.slug}.ics")) for lg in config.LEAGUES],
        revise=feed_history.revisions,
    )
    (out_dir / ics.COMBINED_FEED_PATH).write_bytes(combined.to_ical())


def _write_data(
    out_dir: Path,
    records_dir: Path,
    base_url: str,
    games_by_league: dict[str, list[Game]],
    api_key_present: bool,
    truncated: dict[str, set[str]],
    *,
    fetched_at: datetime | None = None,
    feed_history: history.FeedHistory | None = None,
) -> dict[str, str]:
    """Writes each league and team page's payload to records_dir (not
    deployed), data/site.json (counts only) to the site, and returns each
    schedule page's fingerprint (sitemap.fingerprint), keyed by its site
    path: the league and team pages render from exactly these payloads, and
    the home page from the per-league counts in site.json. Each record also
    names the played games its feed keeps (`kept_played_in_feed`, after the
    fingerprint: the page does not show them, so they never move its
    lastmod)."""
    feed_history = feed_history or history.FeedHistory()
    data_dir = out_dir / "data"
    provenance = site_data.provenance(fetched_at)
    fingerprints: dict[str, str] = {}
    for lg in config.LEAGUES:
        games = games_by_league[lg.slug]
        incomplete = truncated.get(lg.slug, set())
        payload = site_data.league_data(lg, games, fetched=api_key_present, possibly_incomplete_teams=incomplete)
        fingerprints[f"/{lg.slug}/"] = sitemap.fingerprint(payload)
        payload.update(provenance)
        payload[history.KEPT_PLAYED_KEY] = _kept_ids(feed_history, f"ics/{lg.slug}.ics")
        (records_dir / f"{lg.slug}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        team_dir = records_dir / lg.slug
        team_dir.mkdir(exist_ok=True)
        for team in lg.teams:
            team_payload = site_data.team_data(
                team, lg, games, fetched=api_key_present, possibly_incomplete=team.slug in incomplete
            )
            fingerprints[f"/{lg.slug}/{team.slug}/"] = sitemap.fingerprint(team_payload)
            team_payload.update(provenance)
            team_payload[history.KEPT_PLAYED_KEY] = _kept_ids(feed_history, f"ics/{lg.slug}/{team.slug}.ics")
            (team_dir / f"{team.slug}.json").write_text(json.dumps(team_payload, indent=2), encoding="utf-8")

    summary = site_data.site_summary(
        list(config.LEAGUES),
        games_by_league,
        api_key_present=api_key_present,
        not_included=list(config.LEAGUES_EXAMINED_NOT_INCLUDED),
    )
    fingerprints["/"] = sitemap.fingerprint({"leagues": summary["leagues"]})
    fingerprints[site.SCHEDULE_PATH] = sitemap.fingerprint(
        _schedule_payload(games_by_league, api_key_present, truncated, fetched_at)
    )
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
    paid_links: bool = False,
    feed_keys: frozenset[str] = frozenset(),
) -> None:
    leagues_summary = [
        {
            "slug": lg.slug,
            "name": lg.name,
            # None, not 0, when nothing was fetched: "0 upcoming games" would
            # state a fact this build never checked.
            "games_count": len(unique_by_event_id(games_by_league[lg.slug])) if api_key_present else None,
            # Every team's address and name, for the home page's team links.
            "teams": [{"slug": t.slug, "name": t.shown_name} for t in lg.teams],
        }
        for lg in config.LEAGUES
    ]
    (out_dir / "index.html").write_text(
        site.render_index(
            leagues=leagues_summary,
            not_included=list(config.LEAGUES_EXAMINED_NOT_INCLUDED),
            base_url=base_url,
            ga4_id=ga4_id,
            paid_links=paid_links,
            feed_keys=feed_keys,
        ),
        encoding="utf-8",
    )
    (out_dir / "404.html").write_text(
        site.render_not_found(leagues=leagues_summary, base_url=base_url, ga4_id=ga4_id, paid_links=paid_links),
        encoding="utf-8",
    )
    privacy_dir = out_dir / "privacy"
    privacy_dir.mkdir(exist_ok=True)
    (privacy_dir / "index.html").write_text(
        site.render_privacy(base_url=base_url, ga4_id=ga4_id, paid_links=paid_links), encoding="utf-8"
    )
    accessibility_dir = out_dir / "accessibility"
    accessibility_dir.mkdir(exist_ok=True)
    (accessibility_dir / "index.html").write_text(
        site.render_accessibility(base_url=base_url, ga4_id=ga4_id, paid_links=paid_links), encoding="utf-8"
    )
    terms_dir = out_dir / "terms"
    terms_dir.mkdir(exist_ok=True)
    (terms_dir / "index.html").write_text(
        site.render_terms(base_url=base_url, ga4_id=ga4_id, paid_links=paid_links), encoding="utf-8"
    )

    for lg in config.LEAGUES:
        games = games_by_league[lg.slug]
        incomplete = truncated.get(lg.slug, set())
        league_payload = site_data.league_data(lg, games, fetched=api_key_present, possibly_incomplete_teams=incomplete)
        league_payload.update(site_data.provenance(fetched_at))
        league_dir = out_dir / lg.slug
        league_dir.mkdir(exist_ok=True)
        (league_dir / "index.html").write_text(
            site.render_league(
                league=league_payload, base_url=base_url, ga4_id=ga4_id, paid_links=paid_links, feed_keys=feed_keys
            ),
            encoding="utf-8",
        )
        for team in lg.teams:
            team_payload = site_data.team_data(
                team, lg, games, fetched=api_key_present, possibly_incomplete=team.slug in incomplete
            )
            team_payload.update(site_data.provenance(fetched_at))
            team_dir = league_dir / team.slug
            team_dir.mkdir(exist_ok=True)
            (team_dir / "index.html").write_text(
                site.render_team(
                    team=team_payload, base_url=base_url, ga4_id=ga4_id, paid_links=paid_links, feed_keys=feed_keys
                ),
                encoding="utf-8",
            )
            for former in team.former_slugs:
                former_dir = league_dir / former
                former_dir.mkdir(exist_ok=True)
                (former_dir / "index.html").write_text(
                    site.render_moved_team(
                        team_name=team.shown_name,
                        league_name=lg.name,
                        league_slug=lg.slug,
                        team_slug=team.slug,
                        base_url=base_url,
                        ga4_id=ga4_id,
                        paid_links=paid_links,
                        history=site.team_history_text(team_payload),
                    ),
                    encoding="utf-8",
                )

    schedule_dir = out_dir / "schedule"
    schedule_dir.mkdir(exist_ok=True)
    (schedule_dir / "index.html").write_text(
        site.render_schedule(
            schedule=_schedule_payload(games_by_league, api_key_present, truncated, fetched_at),
            leagues=leagues_summary,
            base_url=base_url,
            ga4_id=ga4_id,
            paid_links=paid_links,
        ),
        encoding="utf-8",
    )


def _schedule_payload(
    games_by_league: dict[str, list[Game]],
    api_key_present: bool,
    truncated: dict[str, set[str]],
    fetched_at: datetime | None,
) -> dict[str, object]:
    """The /schedule/ page's payload with its provenance: the page, and its
    sitemap fingerprint, both come from this."""
    payload = site_data.schedule_data(
        list(config.LEAGUES),
        games_by_league,
        fetched=api_key_present,
        fetched_at=fetched_at,
        possibly_incomplete_leagues={slug for slug, teams in truncated.items() if teams},
    )
    payload.update(site_data.provenance(fetched_at))
    return payload


def _write_static(out_dir: Path, *, paid_links: bool = False) -> None:
    (out_dir / "style.css").write_text(site.style_css(paid_links=paid_links), encoding="utf-8")
    for name in STATIC_ASSET_FILES:
        src = ASSETS_DIR / name
        if not src.is_file():
            raise FileNotFoundError(
                f"missing static asset {src} -- run "
                "`uv run python scripts/render_social_assets.py` and commit its output"
            )
        shutil.copyfile(src, out_dir / name)

    # The IndexNow ownership file (indexnow.py): public by design, served from
    # the site root so a search engine can check that the host's owner sent
    # the announcement of new and changed pages.
    indexnow.copy_key_file(ASSETS_DIR, out_dir)

    fonts_dir = out_dir / "fonts"
    fonts_dir.mkdir(exist_ok=True)
    for name in STATIC_FONT_FILES:
        src = ASSETS_DIR / "fonts" / name
        if not src.is_file():
            raise FileNotFoundError(f"missing static font {src} -- see pipeline/assets/fonts/")
        shutil.copyfile(src, fonts_dir / name)


def _pages_kept_out_of_search(
    games_by_league: dict[str, list[Game]],
    api_key_present: bool,
    truncated: dict[str, set[str]],
) -> frozenset[str]:
    """Site paths of the league and team pages rendered noindex
    (site.render_league, site.render_team) and kept out of the sitemap, by
    the same rule (site_data.kept_out_of_search): the build checked
    Ticketmaster and found no game to list, and no verified official ticket
    page exists for the team or league. A page returns on the first build that lists
    a game. A build that fetched nothing has none: not checked is not
    empty."""
    out: set[str] = set()
    for lg in config.LEAGUES:
        games = games_by_league[lg.slug]
        incomplete = truncated.get(lg.slug, set())
        if site_data.kept_out_of_search(
            site_data.league_data(lg, games, fetched=api_key_present, possibly_incomplete_teams=incomplete)
        ):
            out.add(f"/{lg.slug}/")
        for team in lg.teams:
            if site_data.kept_out_of_search(
                site_data.team_data(
                    team, lg, games, fetched=api_key_present, possibly_incomplete=team.slug in incomplete
                )
            ):
                out.add(f"/{lg.slug}/{team.slug}/")
    return frozenset(out)


def _write_sitemap_and_robots(
    out_dir: Path,
    base_url: str,
    state: dict[str, sitemap.PageState],
    *,
    unlisted: frozenset[str] = frozenset(),
) -> None:
    """sitemap.xml (every indexable page; the 404 and the noindex pages in
    `unlisted` are not), robots.txt, and lastmod.json, the state the next
    build compares against. lastmod.json still records an unlisted page, so
    the day a game appears its page is seen as changed and returns to the
    sitemap dated that day."""
    entries: list[tuple[str, str | date | None]] = [
        ("/", state["/"].changed_at),
        (site.PRIVACY_PATH, site.PRIVACY_UPDATED),
        (site.ACCESSIBILITY_PATH, site.ACCESSIBILITY_UPDATED),
        (site.TERMS_PATH, site.TERMS_UPDATED),
        (site.SCHEDULE_PATH, state[site.SCHEDULE_PATH].changed_at),
    ]
    for lg in config.LEAGUES:
        if f"/{lg.slug}/" not in unlisted:
            entries.append((f"/{lg.slug}/", state[f"/{lg.slug}/"].changed_at))
        for team in lg.teams:
            path = f"/{lg.slug}/{team.slug}/"
            if path not in unlisted:
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
        _report_refusal(exc)
        return 1

    _report_build(coverage)
    return 0


def _report_refusal(exc: guard.PublishRefused) -> None:
    """The run log, the error annotations and the job summary for a build the
    publish guard refused. A refused build writes no COVERAGE.txt, which is
    what pages.yml copies into the job summary after a good build, so the
    refusal and every team's vanished games go into the summary here."""
    print(f"BUILD FAILED: {exc}", file=sys.stderr)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        for violation in exc.report.violations:
            print(f"::error title=Publish guard refused the build::{violation.message}", file=sys.stderr)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        body = "\n".join([f"BUILD FAILED: {exc}", "", *guard.render_section(exc.report)])
        with Path(summary_path).open("a", encoding="utf-8") as fh:
            fh.write("## Nightly build refused by the publish guard\n\n```text\n" + body + "\n```\n")


def _report_build(coverage: BuildCoverage) -> None:
    """The run log after a successful build: the publish guard's warnings,
    the coverage report, and any venue time zone fallbacks."""
    github_actions = os.environ.get("GITHUB_ACTIONS") == "true"
    if coverage.publish_guard is not None:
        guard.announce(coverage.publish_guard, github_actions=github_actions)
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
        if github_actions:
            print(f"::warning title=Unknown venue time zone::{message}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
