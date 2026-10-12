"""The all-leagues feed (ics/all.ics, #36).

A subscriber may have the combined feed and a league or team feed at once.
Each game must then be one event under one UID: the combined feed carries
the league feeds' own events, byte for byte, never copies under a new UID.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from icalendar import Calendar, Component

from wsc_pipeline import config, ics, validate_ics
from wsc_pipeline.normalize import normalize_event

from .conftest import BUILD_TIME, make_raw_event
from .fixture_site import build_fixture_site

_VEVENT = re.compile(rb"BEGIN:VEVENT\r\n.*?END:VEVENT\r\n", re.S)
_UID = re.compile(rb"^UID:(.*?)\r$", re.M)


def _raw_events(feed: Path) -> dict[bytes, bytes]:
    """Each VEVENT exactly as written, by UID."""
    out = {}
    for block in _VEVENT.findall(feed.read_bytes()):
        uid = _UID.search(block)
        assert uid is not None
        out[uid.group(1)] = block
    return out


@pytest.fixture
def fixture_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    build_fixture_site(dist)
    return dist


def test_every_event_is_its_league_feeds_event_byte_for_byte(fixture_dist: Path):
    combined = _raw_events(fixture_dist / ics.COMBINED_FEED_PATH)
    league: dict[bytes, bytes] = {}
    for lg in config.LEAGUES:
        league.update(_raw_events(fixture_dist / "ics" / f"{lg.slug}.ics"))
    assert len(combined) == 9  # the fixture's 9 feed events; an empty feed would pass vacuously
    assert combined == league
    assert all(uid.startswith(b"tm-") and b"@" in uid for uid in combined)


def _without_page_link(vevent: Component) -> dict[str, str]:
    """The event's properties, with the description's last line (the link to
    the league or team page the feed belongs to) left out."""
    props = {k: v.to_ical().decode() if hasattr(v, "to_ical") else str(v) for k, v in vevent.items()}
    props["DESCRIPTION"] = str(vevent["description"]).rsplit("\n", 1)[0]
    return props


def test_team_feeds_carry_the_same_events_too(fixture_dist: Path):
    """A team feed's event differs from the league feed's only in which page
    its description links to; UID, start, end, status and summary agree."""
    combined = {
        str(e["uid"]): e
        for e in Calendar.from_ical((fixture_dist / ics.COMBINED_FEED_PATH).read_bytes()).walk("VEVENT")
    }
    seen = 0
    for lg in config.LEAGUES:
        for team in lg.teams:
            feed = Calendar.from_ical((fixture_dist / "ics" / lg.slug / f"{team.slug}.ics").read_bytes())
            for vevent in feed.walk("VEVENT"):
                uid = str(vevent["uid"])
                assert uid in combined
                assert _without_page_link(vevent) == _without_page_link(combined[uid])
                seen += 1
    assert seen == 10  # FX-H2H is in two team feeds


def test_the_combined_feed_links_to_the_home_page_and_validates(fixture_dist: Path):
    body = (fixture_dist / ics.COMBINED_FEED_PATH).read_bytes()
    assert b"\r\nURL:https://nexthomegame.com/\r\n" in body
    assert b"X-WR-CALNAME:All leagues (Next Home Game)" in body
    assert validate_ics.main([str(fixture_dist)]) == 0


def test_a_game_listed_under_two_leagues_is_written_once():
    raw = make_raw_event(event_id="TWICE", name="Indiana Fever vs New York Liberty")
    a = normalize_event(raw, league_slug="wnba", tracked_team_slug="indiana-fever", tracked_team_name="Indiana Fever")
    b = normalize_event(raw, league_slug="nwsl", tracked_team_slug="indiana-fever", tracked_team_name="Indiana Fever")
    assert a is not None and b is not None
    cal = ics.combined_calendar([("wnba", [a], None), ("nwsl", [b], None)], dtstamp=BUILD_TIME)
    assert [str(e["uid"]) for e in cal.walk("VEVENT")] == [ics.make_uid("TWICE")]


# --- the validator refuses a combined feed that would duplicate a game -------------------------------------


def _rewrite(dist: Path, old: bytes, new: bytes) -> None:
    feed = dist / ics.COMBINED_FEED_PATH
    body = feed.read_bytes()
    assert old in body  # the sabotage must actually apply
    feed.write_bytes(body.replace(old, new, 1))


def test_a_league_prefixed_uid_fails_validation(fixture_dist: Path):
    _rewrite(fixture_dist, b"UID:tm-FX-H2H@", b"UID:wnba-tm-FX-H2H@")
    with pytest.raises(validate_ics.FeedError, match="exactly the league feeds' events"):
        validate_ics.validate_dist(fixture_dist)


def test_a_changed_event_fails_validation(fixture_dist: Path):
    _rewrite(fixture_dist, b"SUMMARY:Las Vegas Aces vs Seattle Storm", b"SUMMARY:Las Vegas Aces vs Seattle")
    with pytest.raises(validate_ics.FeedError, match="differs from the same event in its league feed"):
        validate_ics.validate_dist(fixture_dist)


def test_a_dropped_event_fails_validation(fixture_dist: Path):
    feed = fixture_dist / ics.COMBINED_FEED_PATH
    body = feed.read_bytes()
    first = _VEVENT.search(body)
    assert first is not None
    feed.write_bytes(body[: first.start()] + body[first.end() :])
    with pytest.raises(validate_ics.FeedError, match="missing"):
        validate_ics.validate_dist(fixture_dist)


def test_a_missing_combined_feed_fails_validation(fixture_dist: Path):
    (fixture_dist / ics.COMBINED_FEED_PATH).unlink()
    with pytest.raises(validate_ics.FeedError, match="missing"):
        validate_ics.validate_dist(fixture_dist)
