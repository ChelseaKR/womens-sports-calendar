"""A team's URL slug, display name and search names are separate (#24).

Subscribers' calendar apps hold each team's feed URL, and a static host cannot
redirect an `.ics` request, so a slug that has been published must never move
and an event UID must never change (either duplicates or drops events in a real
person's calendar). The first half of this file pins what is published today.
The second half covers the fields that let a team be renamed without moving.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from icalendar import Calendar

from wsc_pipeline import build as build_module
from wsc_pipeline import config, site, validate_ics, validate_seo
from wsc_pipeline.config import League, Team, check_registry
from wsc_pipeline.ics import make_uid
from wsc_pipeline.normalize import team_is_participant_as_any
from wsc_pipeline.ticketmaster import CrawlBudget, DiscoveryClient

from .conftest import make_raw_event
from .fixture_site import build_fixture_site

BASE_URL = "https://nexthomegame.com"

# Every league and team slug published at nexthomegame.com on 2026-09-19: each
# has a page, a feed at /ics/<league>/<slug>.ics and a data file, all checked
# live (HTTP 200) when this list was written. A slug is a URL people have
# saved and a feed URL calendar apps poll; it may be added to this list but
# never changed or removed. To rename a team, keep its slug (docs/DECISIONS.md
# 0015).
PUBLISHED_SLUGS: dict[str, tuple[str, ...]] = {
    "wnba": (
        "minnesota-lynx",
        "golden-state-valkyries",
        "las-vegas-aces",
        "atlanta-dream",
        "indiana-fever",
        "new-york-liberty",
        "washington-mystics",
        "dallas-wings",
        "portland-fire",
        "chicago-sky",
        "los-angeles-sparks",
        "phoenix-mercury",
        "toronto-tempo",
        "connecticut-sun",
        "seattle-storm",
    ),
    "nwsl": (
        "angel-city",
        "bay-fc",
        "boston-legacy",
        "chicago-stars",
        "denver-summit",
        "gotham-fc",
        "houston-dash",
        "kansas-city-current",
        "north-carolina-courage",
        "orlando-pride",
        "portland-thorns",
        "racing-louisville",
        "san-diego-wave",
        "seattle-reign",
        "utah-royals",
        "washington-spirit",
    ),
    "pwhl": (
        "boston-fleet",
        "pwhl-detroit",
        "pwhl-hamilton",
        "pwhl-las-vegas",
        "minnesota-frost",
        "montreal-victoire",
        "new-york-sirens",
        "ottawa-charge",
        "pwhl-san-jose",
        "seattle-torrent",
        "toronto-sceptres",
        "vancouver-goldeneyes",
    ),
    "ausl": (
        "chicago-bandits",
        "carolina-blaze",
        "portland-cascade",
        "oklahoma-city-spark",
        "utah-talons",
        "texas-volts",
    ),
    "ncaaw-big-ten": (
        "illinois-fighting-illini-womens-basketball",
        "indiana-hoosiers-womens-basketball",
        "iowa-hawkeyes-womens-basketball",
        "maryland-terrapins-womens-basketball",
        "michigan-wolverines-womens-basketball",
        "michigan-state-spartans-womens-basketball",
        "minnesota-golden-gophers-womens-basketball",
        "nebraska-cornhuskers-womens-basketball",
        "northwestern-wildcats-womens-basketball",
        "ohio-state-buckeyes-womens-basketball",
        "oregon-ducks-womens-basketball",
        "penn-state-nittany-lions-womens-basketball",
        "purdue-boilermakers-womens-basketball",
        "rutgers-scarlet-knights-womens-basketball",
        "ucla-bruins-womens-basketball",
        "usc-trojans-womens-basketball",
        "washington-huskies-womens-basketball",
        "wisconsin-badgers-womens-basketball",
    ),
}

# The UIDs in every non-empty feed of the fixture site (tests/fixture_site.py),
# taken from a build of the code as it was before this change. A UID is
# tm-<Ticketmaster event id>@<opaque domain> and nothing about a team's name,
# slug or display name may reach it.
GOLDEN_FEED_UIDS: dict[str, list[str]] = {
    "ics/nwsl/portland-thorns.ics": ["tm-FX-THORNS@womens-sports-calendar.invalid"],
    "ics/nwsl.ics": ["tm-FX-THORNS@womens-sports-calendar.invalid"],
    "ics/pwhl/toronto-sceptres.ics": ["tm-FX-SCEPTRES@womens-sports-calendar.invalid"],
    "ics/pwhl.ics": ["tm-FX-SCEPTRES@womens-sports-calendar.invalid"],
    "ics/wnba/las-vegas-aces.ics": [
        "tm-FX-AT@womens-sports-calendar.invalid",
        "tm-FX-ATTRACTIONS@womens-sports-calendar.invalid",
        "tm-FX-AWAY@womens-sports-calendar.invalid",
        "tm-FX-CANCELLED@womens-sports-calendar.invalid",
        "tm-FX-H2H@womens-sports-calendar.invalid",
        "tm-FX-PACKAGE@womens-sports-calendar.invalid",
    ],
    "ics/wnba/seattle-storm.ics": ["tm-FX-H2H@womens-sports-calendar.invalid"],
    "ics/wnba.ics": [
        "tm-FX-AT@womens-sports-calendar.invalid",
        "tm-FX-ATTRACTIONS@womens-sports-calendar.invalid",
        "tm-FX-AWAY@womens-sports-calendar.invalid",
        "tm-FX-CANCELLED@womens-sports-calendar.invalid",
        "tm-FX-H2H@womens-sports-calendar.invalid",
        "tm-FX-PACKAGE@womens-sports-calendar.invalid",
    ],
}


# --- what is published today must not move -------------------------------------------------------------


def test_every_published_league_and_team_slug_is_still_configured():
    """Fails if any existing slug changes or disappears (a renamed team whose
    slug was re-derived from its new name, a changed slugify rule, a removed
    team). New teams may be added."""
    configured = {lg.slug: {t.slug for t in lg.teams} for lg in config.LEAGUES}
    missing_leagues = set(PUBLISHED_SLUGS) - set(configured)
    assert not missing_leagues, f"published league slugs no longer configured: {sorted(missing_leagues)}"
    for league_slug, published in PUBLISHED_SLUGS.items():
        gone = set(published) - configured[league_slug]
        assert not gone, f"{league_slug}: published team slugs no longer configured: {sorted(gone)}"


def test_the_published_slug_list_has_every_team_configured_today():
    """So a slug that is configured but was never pinned cannot slip through:
    add it to PUBLISHED_SLUGS the day it first publishes."""
    configured = {lg.slug: {t.slug for t in lg.teams} for lg in config.LEAGUES}
    assert {k: set(v) for k, v in PUBLISHED_SLUGS.items()} == configured
    assert sum(len(v) for v in PUBLISHED_SLUGS.values()) == 67


def test_every_published_slug_still_gets_a_feed_a_page_and_a_data_file(tmp_path: Path):
    out = tmp_path / "dist"
    build_fixture_site(out)
    for league_slug, slugs in PUBLISHED_SLUGS.items():
        assert (out / "ics" / f"{league_slug}.ics").is_file()
        for slug in slugs:
            assert (out / "ics" / league_slug / f"{slug}.ics").is_file(), f"feed {league_slug}/{slug}"
            assert (out / "data" / league_slug / f"{slug}.json").is_file(), f"data {league_slug}/{slug}"
            assert (out / league_slug / slug / "index.html").is_file(), f"page {league_slug}/{slug}"


def test_the_fixture_site_publishes_exactly_the_uids_it_always_did(tmp_path: Path):
    out = tmp_path / "dist"
    build_fixture_site(out)
    actual: dict[str, list[str]] = {}
    for feed in sorted((out / "ics").rglob("*.ics")):
        uids = sorted(str(e["uid"]) for e in Calendar.from_ical(feed.read_bytes()).walk("VEVENT"))
        if uids:
            actual[feed.relative_to(out).as_posix()] = uids
    assert actual == GOLDEN_FEED_UIDS
    assert make_uid("FX-H2H") == "tm-FX-H2H@womens-sports-calendar.invalid"


def test_the_fields_default_to_the_old_behavior():
    team = Team(slug="indiana-fever", name="Indiana Fever")
    assert team.shown_name == "Indiana Fever"
    assert team.all_names == ("Indiana Fever",)
    assert team.search_names == () and team.former_slugs == () and team.display_name is None


# --- the registry cannot publish two things at one path -----------------------------------------------


def _league(*teams: Team, slug: str = "demo") -> League:
    return League(
        slug=slug,
        name="Demo League",
        country_codes=("US",),
        teams=teams,
        sport="Basketball",
        organization_name="Demo League",
    )


def test_the_committed_registry_passes_its_own_check():
    check_registry(config.LEAGUES)


@pytest.mark.parametrize(
    "teams, message",
    [
        ((Team("a", "A"), Team("a", "B")), "already used"),
        ((Team("a", "A"), Team("b", "B", former_slugs=("a",))), "already used"),
        ((Team("a", "A", former_slugs=("x",)), Team("b", "B", former_slugs=("x",))), "already used"),
        ((Team("a", "A", former_slugs=("a",)),), "already used"),
        ((Team("A B", "A"),), "not a plain URL segment"),
        ((Team("a", "A", former_slugs=("../b",)),), "not a plain URL segment"),
        ((Team("", "A"),), "not a plain URL segment"),
    ],
)
def test_a_registry_that_would_overwrite_a_feed_is_refused(teams, message):
    with pytest.raises(ValueError, match=message):
        check_registry((_league(*teams),))


def test_a_duplicate_league_slug_is_refused():
    with pytest.raises(ValueError, match="used twice"):
        check_registry((_league(Team("a", "A")), _league(Team("b", "B"))))


# --- a renamed team keeps its feed ---------------------------------------------------------------------


def _fake_client(events_by_keyword: dict[str, list[dict[str, Any]]], calls: list[str] | None = None):
    """A real DiscoveryClient over a mock transport, answering by keyword, so
    the crawl budget is the real one."""

    def handler(request: httpx.Request) -> httpx.Response:
        keyword = request.url.params["keyword"]
        if calls is not None:
            calls.append(keyword)
        events = events_by_keyword.get(keyword, [])
        body: dict[str, Any] = {"page": {"totalPages": 1, "totalElements": len(events)}}
        if events:
            body["_embedded"] = {"events": events}
        return httpx.Response(200, json=body)

    def factory(api_key: str) -> DiscoveryClient:
        return DiscoveryClient(api_key, client=httpx.Client(transport=httpx.MockTransport(handler)), min_interval=0.0)

    return factory


def _build(out: Path, monkeypatch, league: League, events_by_keyword, calls: list[str] | None = None):
    monkeypatch.setattr(config, "LEAGUES", (league,))
    monkeypatch.setattr(build_module, "DiscoveryClient", _fake_client(events_by_keyword, calls))
    return build_module.build(out_dir=out, base_url=BASE_URL, api_key="fake-key", affiliate_id=None)


def _renamed_team() -> Team:
    """Renamed from "Old Name" to "New Name" (display "New Name FC") with the
    slug kept on the old one, plus a second team to sit beside it."""
    return Team(slug="old-name", name="New Name", display_name="New Name FC", search_names=("Old Name",))


RENAME_EVENTS = {
    "New Name": [make_raw_event(event_id="E1", name="New Name vs Rival One", date_time="2026-06-15T23:00:00Z")],
    "Old Name": [
        make_raw_event(event_id="E1", name="New Name vs Rival One", date_time="2026-06-15T23:00:00Z"),
        make_raw_event(event_id="E2", name="Old Name vs Rival Two", date_time="2026-06-22T23:00:00Z"),
    ],
}


def test_a_team_with_a_former_slug_serves_the_same_feed_at_both_paths(tmp_path: Path, monkeypatch):
    team = Team(slug="new-name", name="New Name", former_slugs=("old-name",))
    events = {"New Name": RENAME_EVENTS["New Name"]}
    out = tmp_path / "dist"
    _build(out, monkeypatch, _league(team), events)

    current = (out / "ics" / "demo" / "new-name.ics").read_bytes()
    former = (out / "ics" / "demo" / "old-name.ics").read_bytes()
    assert former == current
    uids = {str(e["uid"]) for e in Calendar.from_ical(former).walk("VEVENT")}
    assert uids == {make_uid("E1")}
    # The feed's own URL is the current page, on both paths.
    assert str(Calendar.from_ical(former)["url"]) == f"{BASE_URL}/demo/new-name/"


def test_the_old_page_points_to_the_new_one_and_stays_out_of_the_sitemap(tmp_path: Path, monkeypatch):
    team = Team(slug="new-name", name="New Name", display_name="New Name FC", former_slugs=("old-name",))
    out = tmp_path / "dist"
    _build(out, monkeypatch, _league(team), {"New Name": RENAME_EVENTS["New Name"]})

    old_page = (out / "demo" / "old-name" / "index.html").read_text()
    assert '<meta name="robots" content="noindex">' in old_page
    assert '<meta http-equiv="refresh" content="0; url=/demo/new-name/">' in old_page
    assert 'href="/demo/new-name/"' in old_page
    assert "New Name FC has a new page address" in old_page
    assert 'rel="canonical"' not in old_page  # a noindex notice claims no canonical

    sitemap_xml = (out / "sitemap.xml").read_text()
    assert f"{BASE_URL}/demo/new-name/" in sitemap_xml
    assert "old-name" not in sitemap_xml
    assert "old-name" not in (out / "lastmod.json").read_text()
    # No data file at the old slug: the data path is not a subscribed URL.
    assert not (out / "data" / "demo" / "old-name.json").exists()


def test_the_validators_accept_a_site_with_a_former_slug_and_reject_a_diverged_feed(tmp_path: Path, monkeypatch):
    team = Team(slug="new-name", name="New Name", former_slugs=("old-name",))
    out = tmp_path / "dist"
    _build(out, monkeypatch, _league(team), {"New Name": RENAME_EVENTS["New Name"]})

    feeds, _events = validate_ics.validate_dist(out)
    assert feeds == 3  # the league feed, the team feed and the former-slug feed
    pages, _ = validate_seo.validate_dist(out)
    assert pages == 5  # home, league, team, privacy, accessibility: the old-slug notice is not indexable
    # Negative control: a former-slug feed that differs from the current one is refused.
    (out / "ics" / "demo" / "old-name.ics").write_bytes((out / "ics" / "demo" / "new-name.ics").read_bytes() + b" ")
    with pytest.raises(validate_ics.FeedError, match=r"does not parse|differs"):
        validate_ics.validate_dist(out)


def test_a_former_slug_page_that_is_not_noindex_fails_the_seo_validator(tmp_path: Path, monkeypatch):
    """The old path must never become a second listing of the team."""
    team = Team(slug="new-name", name="New Name", former_slugs=("old-name",))
    out = tmp_path / "dist"
    _build(out, monkeypatch, _league(team), {"New Name": RENAME_EVENTS["New Name"]})
    (out / "demo" / "old-name" / "index.html").write_text((out / "demo" / "new-name" / "index.html").read_text())
    with pytest.raises(validate_seo.SeoError, match="must be noindex"):
        validate_seo.validate_dist(out)


def test_a_missing_former_feed_fails_the_feed_validator(tmp_path: Path, monkeypatch):
    team = Team(slug="new-name", name="New Name", former_slugs=("old-name",))
    out = tmp_path / "dist"
    _build(out, monkeypatch, _league(team), {"New Name": RENAME_EVENTS["New Name"]})
    (out / "ics" / "demo" / "old-name.ics").unlink()
    with pytest.raises(validate_ics.FeedError, match="missing"):
        validate_ics.validate_dist(out)


def test_a_former_slug_notice_page_is_renderable_on_its_own():
    html = site.render_moved_team(
        team_name="New Name", league_name="Demo League", league_slug="demo", team_slug="new-name", base_url=BASE_URL
    )
    assert "<h1>New Name has a new page address</h1>" in html
    assert html.count("<h1>") == 1


# --- a display name changes what is shown, never what is searched -----------------------------------------


def test_a_display_name_is_shown_everywhere_but_the_keyword_is_unchanged(tmp_path: Path, monkeypatch):
    team = Team(slug="old-name", name="New Name", display_name="New Name FC")
    out = tmp_path / "dist"
    calls: list[str] = []
    _build(out, monkeypatch, _league(team), {"New Name": RENAME_EVENTS["New Name"]}, calls)

    assert calls == ["New Name"]  # the keyword sent to Ticketmaster is `name`
    page = (out / "demo" / "old-name" / "index.html").read_text()
    assert "<title>New Name FC " in page
    assert "<h1>New Name FC " in page
    assert "the New Name FC schedule" in page
    league_page = (out / "demo" / "index.html").read_text()
    assert ">New Name FC</a>" in league_page
    team_json = json.loads((out / "data" / "demo" / "old-name.json").read_text())
    assert team_json["team_name"] == "New Name FC" and team_json["team_slug"] == "old-name"
    league_json = json.loads((out / "data" / "demo.json").read_text())
    assert league_json["team_names"] == {"old-name": "New Name FC"}
    feed = Calendar.from_ical((out / "ics" / "demo" / "old-name.ics").read_bytes())
    assert str(feed["x-wr-calname"]) == "New Name FC (Next Home Game)"
    assert "New Name FC" in str(feed["x-wr-caldesc"])
    # The slug, and so the URL and the feed path, did not follow the display name.
    assert str(feed["url"]) == f"{BASE_URL}/demo/old-name/"


def test_without_a_display_name_the_name_is_shown(tmp_path: Path, monkeypatch):
    out = tmp_path / "dist"
    _build(out, monkeypatch, _league(Team("new-name", "New Name")), {"New Name": RENAME_EVENTS["New Name"]})
    assert "<title>New Name " in (out / "demo" / "new-name" / "index.html").read_text()


# --- search names are queried, accepted and counted ---------------------------------------------------------


def test_search_names_are_queried_accepted_and_counted_in_the_crawl_budget(monkeypatch):
    monkeypatch.setattr(config, "LEAGUES", (_league(_renamed_team()),))
    calls: list[str] = []
    monkeypatch.setattr(build_module, "DiscoveryClient", _fake_client(RENAME_EVENTS, calls))

    games, _truncated, mismatched, requests_made, _bytes = build_module.fetch_all_games("fake-key")

    assert calls == ["New Name", "Old Name"]  # the keyword first, then the search name
    assert requests_made == 2  # one country, one page each: the extra query is in the budget
    assert sorted(g.event_id for g in games) == ["E1", "E2"]  # E1 came back twice, kept once
    assert mismatched["demo"] == set()
    assert all(g.tracked_team_slug == "old-name" for g in games)


def test_a_team_without_search_names_makes_one_request(monkeypatch):
    monkeypatch.setattr(config, "LEAGUES", (_league(Team("new-name", "New Name")),))
    monkeypatch.setattr(build_module, "DiscoveryClient", _fake_client(RENAME_EVENTS))
    *_rest, requests_made, _bytes = build_module.fetch_all_games("fake-key")
    assert requests_made == 1


def test_an_event_under_the_former_name_is_accepted_only_through_a_search_name():
    event = make_raw_event(event_id="E2", name="Old Name vs Rival Two")
    assert not team_is_participant_as_any(("New Name",), event)
    assert team_is_participant_as_any(("New Name", "Old Name"), event)
    assert team_is_participant_as_any(_renamed_team().all_names, event)
    # Still rejects an unrelated event.
    assert not team_is_participant_as_any(_renamed_team().all_names, make_raw_event(name="Somebody vs Else"))


def test_the_crawl_budget_counts_the_extra_queries_by_keyword():
    budget = CrawlBudget()
    handler_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        handler_calls.append(request.url.params["keyword"])
        return httpx.Response(200, json={"page": {"totalPages": 1}})

    client = DiscoveryClient("k", client=httpx.Client(transport=httpx.MockTransport(handler)), min_interval=0.0)
    for name in _renamed_team().all_names:
        client.search_team_events("old-name", name, ("US",))
    assert client.budget.requests_by_team == {"New Name": 1, "Old Name": 1}
    assert budget.requests_made == 0 and client.budget.requests_made == 2


def test_the_home_flag_recognizes_the_former_name(tmp_path: Path, monkeypatch):
    """A game billed under the former name is still known as this team's home
    game (site_data.tracked_team_is_home uses every name)."""
    out = tmp_path / "dist"
    _build(out, monkeypatch, _league(_renamed_team()), RENAME_EVENTS)
    games = {g["event_id"]: g for g in json.loads((out / "data" / "demo" / "old-name.json").read_text())["games"]}
    assert games["E1"]["tracked_team_is_home"] is True
    assert games["E2"]["tracked_team_is_home"] is True  # "Old Name vs Rival Two": the former name is the home side
