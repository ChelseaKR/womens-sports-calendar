"""SEC women's basketball, the sixth tracked league (DECISIONS 0023).

The league follows the Big Ten pattern (DECISIONS 0010) with two additions
the 2026-11-02 measurement (DECISIONS 0022) showed it needs:

- "Women's" and "Womens" are the same word to the participant check.
  Ticketmaster's Tennessee attraction is "Tennessee Lady Volunteers Women's
  Basketball" (ticketmaster.com artist 848403), and the keyword "Tennessee
  Lady Volunteers Womens Basketball" matched none of the 27 events it
  returned until the apostrophe was dropped from both sides.
- Another school whose name contains an SEC school's after a direction
  ("Middle Tennessee", "North Alabama") is not that school.

Event names below are constructed in the shapes Ticketmaster uses; none is
claimed to be a live listing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from icalendar import Calendar

from wsc_pipeline import build as build_module
from wsc_pipeline import config, feeds, normalize, official_tickets, site_data
from wsc_pipeline.config import league_by_slug
from wsc_pipeline.normalize import normalize_event, team_is_participant, team_is_participant_as_any
from wsc_pipeline.site_data import records_dir

from .conftest import make_raw_event
from .test_build import _FakeDiscoveryClient

BASE_URL = "https://nexthomegame.com"
SEC = league_by_slug("ncaaw-sec")
TENNESSEE_SLUG = "tennessee-lady-volunteers-womens-basketball"
GEORGIA_SLUG = "georgia-bulldogs-womens-basketball"
ALABAMA_SLUG = "alabama-crimson-tide-womens-basketball"
TENNESSEE_TM = "Tennessee Lady Volunteers Women's Basketball"
HOME_GAME = f"{TENNESSEE_TM} vs Florida Gators Womens Basketball"


def _team(slug: str) -> config.Team:
    return next(t for t in SEC.teams if t.slug == slug)


def _accepts(team: config.Team, name: str) -> bool:
    return team_is_participant_as_any(team.match_names, {"name": name}, team.not_this_team)


# --- the registry ----------------------------------------------------------------------------------------------


def test_the_sec_is_tracked_with_its_sixteen_schools():
    assert SEC.name == "NCAA Women's Basketball (SEC)"
    assert SEC.country_codes == ("US",)
    assert SEC.organization_name == "Southeastern Conference"
    assert (SEC.search_title_name, SEC.search_short_name) == ("SEC women's basketball", "SEC")
    assert len(SEC.teams) == 16
    assert SEC.schedule_source_used is False and "ticketmaster" in SEC.schedule_source_note.lower()
    for team in SEC.teams:
        # The Big Ten shape: keyword "<School> <Mascot> Womens Basketball",
        # title "<School> women's basketball", slug from the keyword.
        assert team.name.endswith(" Womens Basketball"), team.name
        assert team.title_name and team.title_name.endswith(" women's basketball"), team.name
        assert team.display_name is None and team.search_names == ()


def test_georgia_is_searched_as_georgia_bulldogs():
    """On 2026-11-02 the keyword "Georgia Lady Bulldogs Womens Basketball"
    found 2 events and matched none; "Georgia Bulldogs Women's Basketball"
    found 24 and matched all 24 (16 at home)."""
    assert _team(GEORGIA_SLUG).name == "Georgia Bulldogs Womens Basketball"


def test_every_sec_school_but_georgia_links_its_official_ticket_page():
    missing = {t.slug for t in SEC.teams if official_tickets.team_page(SEC.slug, t.slug) is None}
    assert missing == {GEORGIA_SLUG}
    assert official_tickets.league_page(SEC.slug) is None  # each school sells its own
    for team in SEC.teams:
        page = official_tickets.team_page(SEC.slug, team.slug)
        if page is not None:
            assert official_tickets.SEC_CHECKED_ON in page.evidence, team.slug


# --- "Women's" is "Womens" --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        HOME_GAME,
        "Tennessee Lady Volunteers Women’s Basketball vs Florida Gators Womens Basketball",
        "Florida Gators Womens Basketball vs Tennessee Lady Volunteers Women's Basketball",
        "Tennessee Women's Basketball vs Florida",
    ],
)
def test_the_tennessee_keyword_matches_the_name_ticketmaster_uses(name: str):
    assert _accepts(_team(TENNESSEE_SLUG), name)


def test_without_the_apostrophe_rule_tennessee_matches_nothing(monkeypatch: pytest.MonkeyPatch):
    """Negative control: the match above is the apostrophe rule's doing."""
    monkeypatch.setattr(normalize, "_APOSTROPHES", re.compile("(?!)"))
    assert not _accepts(_team(TENNESSEE_SLUG), HOME_GAME)


def test_the_apostrophe_rule_also_holds_for_a_big_ten_keyword():
    nebraska = next(t for t in league_by_slug("ncaaw-big-ten").teams if t.slug.startswith("nebraska"))
    assert team_is_participant(nebraska.name, {"name": "Nebraska Cornhuskers Women's Basketball vs Iowa"})


def test_the_rule_loosens_nothing_but_the_apostrophe():
    """The whole phrase is still needed: a men's or other-sport listing that
    shares only the school and nickname is not this team."""
    assert not _accepts(_team(TENNESSEE_SLUG), "Tennessee Volunteers vs Florida Gators")


# --- other schools with an SEC school's name inside ---------------------------------------------------------------


COLLISIONS = [
    (TENNESSEE_SLUG, "Middle Tennessee Women's Basketball vs Tennessee Tech Women's Basketball"),
    (ALABAMA_SLUG, "North Alabama Women's Basketball vs Samford Women's Basketball"),
    ("texas-am-aggies-womens-basketball", "East Texas A&M Women's Basketball vs Lamar Women's Basketball"),
    ("missouri-tigers-womens-basketball", "Southeast Missouri Women's Basketball vs SIUE Women's Basketball"),
    ("kentucky-wildcats-womens-basketball", "Northern Kentucky Women's Basketball vs Xavier Women's Basketball"),
    ("florida-gators-womens-basketball", "South Florida Women's Basketball vs Rice Women's Basketball"),
    (GEORGIA_SLUG, "West Georgia Women's Basketball vs Lipscomb Women's Basketball"),
]


@pytest.mark.parametrize(("slug", "name"), COLLISIONS)
def test_another_school_with_the_name_inside_is_not_this_school(slug: str, name: str):
    team = _team(slug)
    assert not _accepts(team, name)
    # Negative control: without the exclusions the same event WOULD be
    # accepted, so the assertion above is the exclusion's doing.
    assert team_is_participant_as_any(team.match_names, {"name": name}, ())


def test_a_real_game_against_such_a_school_still_counts():
    tennessee = _team(TENNESSEE_SLUG)
    assert _accepts(tennessee, f"{TENNESSEE_TM} vs Middle Tennessee Women's Basketball")
    assert _accepts(tennessee, f"Middle Tennessee Women's Basketball vs {TENNESSEE_TM}")


# --- the home flag ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "home"),
    [
        (HOME_GAME, True),
        ("Tennessee Women's Basketball vs Florida", True),
        (f"Florida Gators Womens Basketball vs {TENNESSEE_TM}", False),
        ("Middle Tennessee Women's Basketball vs Tennessee", False),
    ],
)
def test_the_home_flag(name: str, home: bool):
    team = _team(TENNESSEE_SLUG)
    game = normalize_event(
        make_raw_event(event_id="SEC-H", name=name),
        league_slug=SEC.slug,
        tracked_team_slug=team.slug,
        tracked_team_name=team.name,
    )
    assert game is not None
    assert site_data.tracked_team_is_home(team, game) is home


# --- the built site -----------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    raw = make_raw_event(
        event_id="SEC-TN-1",
        name=HOME_GAME,
        date_time="2026-12-06T19:00:00Z",
        local_date="2026-12-06",
        local_time="14:00:00",
        venue_name="Food City Center",
        venue_city="Knoxville",
        venue_state="TN",
        timezone="America/New_York",
        url="https://www.ticketmaster.com/event/SEC-TN-1",
    )
    fake = _FakeDiscoveryClient({TENNESSEE_SLUG: [raw]})
    out = tmp_path_factory.mktemp("sec") / "dist"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(build_module, "DiscoveryClient", lambda api_key: fake)
        build_module.build(out_dir=out, base_url=BASE_URL, api_key="fake-key", affiliate_id=None)
    return out


def _sitemap(out: Path) -> str:
    return (out / "sitemap.xml").read_text()


def test_the_league_page_feed_and_atom_feed(built: Path):
    page = (built / "ncaaw-sec" / "index.html").read_text()
    assert "<h1>SEC women&#x27;s basketball 2026 schedule</h1>" in page
    assert f"{BASE_URL}/ncaaw-sec/</loc>" in _sitemap(built)
    cal = Calendar.from_ical((built / "ics" / "ncaaw-sec.ics").read_bytes())
    assert [str(e["summary"]) for e in cal.walk("VEVENT")] == [HOME_GAME]
    atom = (built / feeds.feed_path("ncaaw-sec")).read_text()
    assert "SEC-TN-1" in atom  # a home game is in the league's home-game feed
    assert "SEC-TN-1" in (built / feeds.feed_path(feeds.ALL_KEY)).read_text()


def test_the_team_page_feed_and_data(built: Path):
    page = (built / "ncaaw-sec" / TENNESSEE_SLUG / "index.html").read_text()
    assert "Tennessee women&#x27;s basketball" in page
    assert "utsports.com" in page and "the school&#x27;s official ticket page" in page
    cal = Calendar.from_ical((built / "ics" / "ncaaw-sec" / f"{TENNESSEE_SLUG}.ics").read_bytes())
    assert [str(e["uid"]) for e in cal.walk("VEVENT")] == ["tm-SEC-TN-1@womens-sports-calendar.invalid"]
    data = json.loads((records_dir(built) / "ncaaw-sec" / f"{TENNESSEE_SLUG}.json").read_text())
    assert data["next_home_event_id"] == "SEC-TN-1"


def test_empty_team_pages_follow_the_ticket_link_rule(built: Path):
    """DECISIONS 0020: an empty team page is indexed only when it links an
    official ticket page. Alabama has one; Georgia has none."""
    sitemap_text = _sitemap(built)
    alabama = (built / "ncaaw-sec" / ALABAMA_SLUG / "index.html").read_text()
    georgia = (built / "ncaaw-sec" / GEORGIA_SLUG / "index.html").read_text()
    assert 'content="noindex"' not in alabama and f"/ncaaw-sec/{ALABAMA_SLUG}/</loc>" in sitemap_text
    assert 'content="noindex"' in georgia and f"/ncaaw-sec/{GEORGIA_SLUG}/</loc>" not in sitemap_text
    for team in SEC.teams:
        assert (built / "ics" / "ncaaw-sec" / f"{team.slug}.ics").is_file(), team.slug
