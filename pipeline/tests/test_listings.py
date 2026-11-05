"""Doubleheaders, season tickets and men's games on team pages and feeds.

Every listing below is a real Ticketmaster event from the live build of
2026-11-05 (nexthomegame.com's league feeds): its event id, name, venue,
local date and time, and ticket URL are copied from the published feed. The
feeds do not carry Ticketmaster's attraction list, so the attractions given
to the two event listings are the teams their own schedules name
(kuathletics.com, gophersports.com, utsports.com, vucommodores.com); they
only decide which team searches return the event, as they do live.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from icalendar import Calendar

from wsc_pipeline import build as build_module
from wsc_pipeline import listings, validate_ics
from wsc_pipeline.config import LEAGUES, league_by_slug
from wsc_pipeline.normalize import Game, normalize_event
from wsc_pipeline.site_data import game_to_dict, records_dir

from .conftest import make_raw_event

BIG_TEN = league_by_slug("ncaaw-big-ten")
SEC = league_by_slug("ncaaw-sec")
NEBRASKA = "nebraska-cornhuskers-womens-basketball"
PENN_STATE = "penn-state-nittany-lions-womens-basketball"
TENNESSEE = "tennessee-lady-volunteers-womens-basketball"
VANDERBILT = "vanderbilt-commodores-womens-basketball"

_PENTAGON = {
    "venue_name": "Sanford Pentagon",
    "venue_city": "Sioux Falls",
    "venue_state": "SD",
    "timezone": "America/Chicago",
}
_BRIDGESTONE = {
    "venue_name": "Bridgestone Arena",
    "venue_city": "Nashville",
    "venue_state": "TN",
    "timezone": "America/Chicago",
}

# Starts at 1:00 PM CT, Minnesota and Kansas State's slot; Nebraska plays
# Kansas at 3:30 PM CT (kuathletics.com).
MARKETBEAT = make_raw_event(
    event_id="vvG1bZ_C-7KX6i",
    name="MarketBeat Invitational Women's Basketball",
    date_time="2026-11-14T19:00:00Z",
    local_date="2026-11-14",
    local_time="13:00:00",
    attractions=[
        "Kansas Jayhawks Womens Basketball",
        "Nebraska Cornhuskers Womens Basketball",
        "Minnesota Golden Gophers Womens Basketball",
        "Kansas State Wildcats Womens Basketball",
    ],
    url="https://www.ticketmaster.com/marketbeat-invitational-womens-basketball-sioux-falls-south-dakota-11-14-2026/event/060064E8444FE1EC",
    **_PENTAGON,
)
# Starts at 5:00 PM CT, Tennessee and Baylor's slot (utsports.com: 6 PM ET);
# Vanderbilt plays Belmont at 7:30 PM CT (vucommodores.com).
DOUBLEHEADER = make_raw_event(
    event_id="G5viZ_58LMXYN",
    name="The Bad Boys Mower Series: Women's College Basketball Doubleheader",
    date_time="2026-12-18T23:00:00Z",
    local_date="2026-12-18",
    local_time="17:00:00",
    attractions=[
        "Tennessee Lady Volunteers Womens Basketball",
        "Baylor Lady Bears Basketball",
        "Vanderbilt Commodores Womens Basketball",
        "Belmont Bruins Womens Basketball",
    ],
    url="https://www.ticketmaster.com/the-bad-boys-mower-series-womens-nashville-tennessee-12-18-2026/event/1B0064B41FDFEC23",
    **_BRIDGESTONE,
)
# Vanderbilt's own listing for the same night; Ticketmaster lists no time.
VANDERBILT_BELMONT = make_raw_event(
    event_id="Z7r9jZ1A7Pvqv",
    name="Vanderbilt Commodores Womens Basketball vs. Belmont Bruins Womens Basketball",
    date_time=None,
    local_date="2026-12-18",
    local_time=None,
    time_tba=True,
    url="https://www.ticketmaster.com/event/Z7r9jZ1A7Pvqv",
    **_BRIDGESTONE,
)
SEASON_TICKETS = make_raw_event(
    event_id="G5viZ_KhLQpM1",
    name="Tennessee Volunteers Women's Basketball Season Tickets",
    date_time="2026-09-22T03:59:00Z",
    local_date="2026-09-21",
    local_time="23:59:00",
    venue_name="Food City Center",
    venue_city="Knoxville",
    venue_state="TN",
    timezone="America/New_York",
    url="https://am.ticketmaster.com/allvols/buy/ism/TDI2",
)
MENS_GAME = make_raw_event(
    event_id="Z7r9jZ1A7JFAp",
    name="Pittsburgh Panthers Mens Basketball vs. Penn State Nittany Lions Womens Basketball",
    date_time="2026-11-09T01:00:00Z",
    local_date="2026-11-08",
    local_time="20:00:00",
    venue_name="Palestra",
    venue_city="Philadelphia",
    venue_state="PA",
    timezone="America/New_York",
    url="https://www.ticketmaster.com/event/Z7r9jZ1A7JFAp",
)
# Penn State's real game at UCLA: kept, unchanged.
PENN_STATE_AT_UCLA = make_raw_event(
    event_id="Z7r9jZ1AA7kGp",
    name="UCLA Bruins Womens Basketball vs. Penn State Nittany Lions Womens Basketball",
    date_time="2027-01-16T03:00:00Z",
    local_date="2027-01-15",
    local_time="19:00:00",
    venue_name="Pauley Pavilion-UCLA",
    venue_city="Los Angeles",
    venue_state="CA",
    timezone="America/Los_Angeles",
    url="https://www.ticketmaster.com/event/Z7r9jZ1AA7kGp",
)

# What each team's search returned on 2026-11-05.
LIVE = [
    ("ncaaw-big-ten", NEBRASKA, MARKETBEAT),
    ("ncaaw-big-ten", PENN_STATE, MENS_GAME),
    ("ncaaw-big-ten", PENN_STATE, PENN_STATE_AT_UCLA),
    ("ncaaw-sec", TENNESSEE, SEASON_TICKETS),
    ("ncaaw-sec", TENNESSEE, DOUBLEHEADER),
    ("ncaaw-sec", VANDERBILT, DOUBLEHEADER),
    ("ncaaw-sec", VANDERBILT, VANDERBILT_BELMONT),
]

FETCHED_AT = datetime(2026, 11, 5, 8, 25, tzinfo=UTC)


def _game(league_slug: str, team_slug: str, raw: dict) -> Game:
    league = league_by_slug(league_slug)
    team = next(t for t in league.teams if t.slug == team_slug)
    game = normalize_event(raw, league_slug=league_slug, tracked_team_slug=team_slug, tracked_team_name=team.name)
    assert game is not None
    return game


def _live_games() -> list[Game]:
    return [_game(lg, team, raw) for lg, team, raw in LIVE]


def _ids(games: list[Game], team_slug: str) -> list[str]:
    return [g.event_id for g in games if g.tracked_team_slug == team_slug]


def test_only_games_drops_the_non_games_and_the_duplicate():
    kept, dropped = listings.only_games(_live_games())

    assert _ids(kept, NEBRASKA) == ["vvG1bZ_C-7KX6i"]
    assert _ids(kept, PENN_STATE) == ["Z7r9jZ1AA7kGp"]
    assert _ids(kept, TENNESSEE) == ["G5viZ_58LMXYN"]
    assert _ids(kept, VANDERBILT) == ["Z7r9jZ1A7Pvqv"]
    assert sorted((d.team_slug, d.event_id, d.reason) for d in dropped) == [
        (PENN_STATE, "Z7r9jZ1A7JFAp", "names a men's team"),
        (TENNESSEE, "G5viZ_KhLQpM1", "a ticket product, not a game"),
        (VANDERBILT, "G5viZ_58LMXYN", "an event listing for a game the team's own listing already covers"),
    ]


def test_the_event_listing_is_kept_when_the_team_has_no_listing_of_its_own():
    """Negative control: without Vanderbilt's own listing the doubleheader is
    not a duplicate, so it stays for Vanderbilt too (labeled as the event's
    start)."""
    games = [g for g in _live_games() if g.event_id != "Z7r9jZ1A7Pvqv"]
    kept, _dropped = listings.only_games(games)
    assert _ids(kept, VANDERBILT) == ["G5viZ_58LMXYN"]


def test_a_matchup_on_another_day_or_at_another_venue_is_not_a_duplicate():
    other_day = dict(
        VANDERBILT_BELMONT, dates={**VANDERBILT_BELMONT["dates"], "start": {"localDate": "2026-12-19", "timeTBA": True}}
    )
    games = [_game("ncaaw-sec", VANDERBILT, DOUBLEHEADER), _game("ncaaw-sec", VANDERBILT, other_day)]
    kept, _dropped = listings.only_games(games)
    assert sorted(_ids(kept, VANDERBILT)) == ["G5viZ_58LMXYN", "Z7r9jZ1A7Pvqv"]

    elsewhere = make_raw_event(
        event_id="EVT-ELSEWHERE",
        name="Vanderbilt Commodores Womens Basketball vs. Belmont Bruins Womens Basketball",
        local_date="2026-12-18",
        venue_name="Vanderbilt Memorial Gym",
    )
    games = [_game("ncaaw-sec", VANDERBILT, DOUBLEHEADER), _game("ncaaw-sec", VANDERBILT, elsewhere)]
    kept, _dropped = listings.only_games(games)
    assert sorted(_ids(kept, VANDERBILT)) == ["EVT-ELSEWHERE", "G5viZ_58LMXYN"]


@pytest.mark.parametrize(
    "name",
    [
        "Tennessee Volunteers Women's Basketball Season Tickets",
        "PARKING: Seattle Storm vs. Las Vegas Aces",
        "Minnesota Lynx Suites - 2027 Season",
        "Indiana Fever 2027 Season Ticket Deposit",
        "Big Ten Women's Basketball Tournament All-Session Pass",
        "Chicago Stars FC Flex Plan",
    ],
)
def test_ticket_products_are_not_games(name: str):
    game = _game("ncaaw-sec", TENNESSEE, make_raw_event(name=name))
    assert listings._non_game_reason(game) == "a ticket product, not a game"


@pytest.mark.parametrize(
    "name",
    [
        "Vanderbilt Commodores Womens Basketball vs. Belmont Bruins Womens Basketball",
        "Tennessee Lady Volunteers Women's Basketball vs. Florida Gators Womens Basketball",
        "Chicago Sky: Capital One Arena VIP Seating",
        "Seattle Storm vs Las Vegas Aces - Game 2 (If Necessary)",
        "Passaic Women's Basketball Classic",
        "Men's and Women's Basketball Doubleheader",
    ],
)
def test_real_games_are_kept(name: str):
    game = _game("ncaaw-sec", TENNESSEE, make_raw_event(name=name))
    assert listings._non_game_reason(game) is None


@pytest.mark.parametrize(
    "name",
    [
        "Pittsburgh Panthers Mens Basketball vs. Penn State Nittany Lions Womens Basketball",
        "Penn State Nittany Lions Womens Basketball vs. Pittsburgh Panthers Men's Basketball",
        "Penn State Men's Basketball Exhibition",
    ],
)
def test_a_mens_team_is_not_a_womens_game(name: str):
    game = _game("ncaaw-big-ten", PENN_STATE, make_raw_event(name=name))
    assert listings._non_game_reason(game) == "names a men's team"


def test_the_event_start_is_labeled_and_a_matchup_time_is_not():
    games = {g.event_id: g for g in _live_games()}
    marketbeat = game_to_dict(games["vvG1bZ_C-7KX6i"])
    assert marketbeat["start_display"] == "Sat, Nov 14, 2026, 1:00 PM CST (event start; game time not listed)"
    assert marketbeat["event_start_only"] is True

    ucla = game_to_dict(games["Z7r9jZ1AA7kGp"])
    assert ucla["start_display"] == "Fri, Jan 15, 2027, 7:00 PM PST"
    assert "event_start_only" not in ucla
    # An event listing with no announced time claims no time at all.
    belmont = game_to_dict(games["Z7r9jZ1A7Pvqv"])
    assert belmont["start_display"] == "Fri, Dec 18, 2026 (time TBA)"


def _build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    games = _live_games()
    empty = {lg.slug: set() for lg in LEAGUES}
    monkeypatch.setattr(
        build_module, "fetch_all_games", lambda api_key: (games, empty, {k: set() for k in empty}, 7, 700)
    )
    out_dir = tmp_path / "dist"
    build_module.build(
        out_dir=out_dir, base_url="https://nexthomegame.com", api_key="fake-key", affiliate_id=None, now=FETCHED_AT
    )
    return out_dir


def _feed(out_dir: Path, path: str) -> dict[str, object]:
    cal = Calendar.from_ical((out_dir / "ics" / path).read_bytes())
    return {str(ev["uid"]): ev for ev in cal.walk("VEVENT")}


def test_the_built_site_lists_each_game_once_with_an_honest_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    out_dir = _build(tmp_path, monkeypatch)

    nebraska = _feed(out_dir, f"ncaaw-big-ten/{NEBRASKA}.ics")
    event = nebraska["tm-vvG1bZ_C-7KX6i@womens-sports-calendar.invalid"]
    assert str(event["summary"]) == "MarketBeat Invitational Women's Basketball (event start; game time not listed)"
    assert listings.EVENT_START_NOTE in str(event["description"])
    assert event.decoded("dtstart").isoformat() == "2026-11-14T13:00:00-06:00"  # the event's, and says so

    vanderbilt = _feed(out_dir, f"ncaaw-sec/{VANDERBILT}.ics")
    assert list(vanderbilt) == ["tm-Z7r9jZ1A7Pvqv@womens-sports-calendar.invalid"]  # once, not twice
    assert str(vanderbilt["tm-Z7r9jZ1A7Pvqv@womens-sports-calendar.invalid"]["summary"]).endswith("(time TBA)")

    tennessee = _feed(out_dir, f"ncaaw-sec/{TENNESSEE}.ics")
    assert list(tennessee) == ["tm-G5viZ_58LMXYN@womens-sports-calendar.invalid"]  # no season tickets

    penn_state = _feed(out_dir, f"ncaaw-big-ten/{PENN_STATE}.ics")
    assert list(penn_state) == ["tm-Z7r9jZ1AA7kGp@womens-sports-calendar.invalid"]  # no men's game
    assert str(penn_state["tm-Z7r9jZ1AA7kGp@womens-sports-calendar.invalid"]["summary"]) == (
        "UCLA Bruins Womens Basketball vs. Penn State Nittany Lions Womens Basketball"
    )

    # The league feed still has the doubleheader once, by its same UID.
    sec = _feed(out_dir, "ncaaw-sec.ics")
    assert sorted(sec) == [
        "tm-G5viZ_58LMXYN@womens-sports-calendar.invalid",
        "tm-Z7r9jZ1A7Pvqv@womens-sports-calendar.invalid",
    ]

    penn_html = (out_dir / "ncaaw-big-ten" / PENN_STATE / "index.html").read_text()
    assert "Pittsburgh Panthers Mens" not in penn_html
    tennessee_html = (out_dir / "ncaaw-sec" / TENNESSEE / "index.html").read_text()
    assert "Season Tickets" not in tennessee_html
    assert "(event start; game time not listed)" in tennessee_html
    record = json.loads((records_dir(out_dir) / "ncaaw-sec" / f"{VANDERBILT}.json").read_text())
    assert [g["event_id"] for g in record["games"]] == ["Z7r9jZ1A7Pvqv"]

    report = (out_dir / "COVERAGE.txt").read_text()
    assert "left out 2 team listing(s)" in report  # SEC: season tickets, the duplicate
    assert "G5viZ_KhLQpM1" in report and "Z7r9jZ1A7JFAp" in report

    validate_ics.validate_dist(out_dir)


def test_the_feed_validator_refuses_an_unlabeled_event_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Negative control: the validator catches a feed that drops the label."""
    monkeypatch.setattr("wsc_pipeline.ics.EVENT_START_SUFFIX", "")
    out_dir = _build(tmp_path, monkeypatch)
    with pytest.raises(validate_ics.FeedError, match="does not say so"):
        validate_ics.validate_dist(out_dir)
