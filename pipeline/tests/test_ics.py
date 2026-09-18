from __future__ import annotations

import pytest
from icalendar import Calendar

from wsc_pipeline.ics import (
    DuplicateUIDError,
    build_calendar,
    check_no_duplicate_uids,
    make_uid,
)
from wsc_pipeline.normalize import normalize_event

from .conftest import make_raw_event


def _game(event_id, **kwargs):
    raw = make_raw_event(event_id=event_id, **kwargs)
    return normalize_event(
        raw, league_slug="wnba", tracked_team_slug="indiana-fever", tracked_team_name="Indiana Fever"
    )


def test_uid_is_stable_across_two_builds():
    """Re-subscribing (or a subscriber's app re-fetching tomorrow's build)
    must not duplicate entries: the same source event id must always yield
    the same UID."""
    assert make_uid("EVT1") == make_uid("EVT1")
    game_a = _game("EVT1")
    game_b = _game("EVT1")
    cal_a = build_calendar([game_a], cal_name="Test A")
    cal_b = build_calendar([game_b], cal_name="Test B")
    uid_a = next(c["uid"] for c in cal_a.walk("VEVENT"))
    uid_b = next(c["uid"] for c in cal_b.walk("VEVENT"))
    assert str(uid_a) == str(uid_b)


def test_different_events_get_different_uids():
    game1, game2 = _game("EVT1"), _game("EVT2")
    cal = build_calendar([game1, game2], cal_name="Test")
    uids = {str(c["uid"]) for c in cal.walk("VEVENT")}
    assert len(uids) == 2


def test_duplicate_uid_check_raises_on_same_event_id_twice():
    game1 = _game("EVT-DUP")
    game2 = _game("EVT-DUP")
    with pytest.raises(DuplicateUIDError):
        check_no_duplicate_uids([game1, game2])


def test_build_calendar_dedupes_repeated_event_id_instead_of_erroring():
    """A team appearing on both sides of the same TM search (e.g. two
    tracked teams both matching one event) must not emit the game twice."""
    game1 = _game("EVT-SAME")
    game2 = _game("EVT-SAME")
    cal = build_calendar([game1, game2], cal_name="Test")
    events = cal.walk("VEVENT")
    assert len(events) == 1


def test_calendar_round_trips_through_icalendar_parser():
    """Validates the emitted bytes are real RFC 5545 by parsing them back."""
    game = _game("EVT1")
    cal = build_calendar([game], cal_name="Indiana Fever")
    raw_bytes = cal.to_ical()
    reparsed = Calendar.from_ical(raw_bytes)
    assert reparsed["x-wr-calname"] is not None
    events = reparsed.walk("VEVENT")
    assert len(events) == 1
    assert str(events[0]["uid"]) == make_uid("EVT1")


def test_date_tbd_game_excluded_from_ics_but_not_erased():
    tbd_raw = make_raw_event(event_id="EVT-TBD2", date_time=None, local_date="2026-08-01", date_tbd=True)
    tbd_game = normalize_event(tbd_raw, league_slug="pwhl", tracked_team_slug="t", tracked_team_name="T")
    normal_game = _game("EVT-NORMAL")
    cal = build_calendar([tbd_game, normal_game], cal_name="Test")
    events = cal.walk("VEVENT")
    assert len(events) == 1
    assert str(events[0]["uid"]) == make_uid("EVT-NORMAL")


def test_no_price_description_says_not_available():
    raw = make_raw_event(event_id="EVT-NOPRICE2", price_ranges=None)
    game = normalize_event(raw, league_slug="wnba", tracked_team_slug="t", tracked_team_name="T")
    cal = build_calendar([game], cal_name="Test")
    desc = str(cal.walk("VEVENT")[0]["description"])
    assert "price not available" in desc
    assert "$" not in desc


def test_price_shown_when_present():
    raw = make_raw_event(
        event_id="EVT-PRICE2",
        price_ranges=[{"type": "standard", "currency": "USD", "min": 10.0, "max": 20.0}],
    )
    game = normalize_event(raw, league_slug="wnba", tracked_team_slug="t", tracked_team_name="T")
    cal = build_calendar([game], cal_name="Test")
    desc = str(cal.walk("VEVENT")[0]["description"])
    assert "USD 10.00-20.00" in desc


def test_timezone_component_included_for_events_with_tzid():
    game = _game("EVT-TZ", timezone="America/Indiana/Indianapolis")
    cal = build_calendar([game], cal_name="Test")
    vtimezones = cal.walk("VTIMEZONE")
    assert len(vtimezones) == 1
    assert str(vtimezones[0]["tzid"]) == "America/Indiana/Indianapolis"


def test_dtstart_present_on_every_included_event():
    game = _game("EVT-DT")
    cal = build_calendar([game], cal_name="Test")
    event = cal.walk("VEVENT")[0]
    assert event.get("dtstart") is not None


def test_team_feed_names_itself_and_links_back_to_its_page():
    from wsc_pipeline.ics import team_calendar

    game = _game("EVT-LINK")
    cal = team_calendar(
        "indiana-fever", "Indiana Fever", [game], base_url="https://nexthomegame.com", league_slug="wnba"
    )
    page = "https://nexthomegame.com/wnba/indiana-fever/"
    assert str(cal["x-wr-calname"]) == "Indiana Fever (Next Home Game)"
    assert str(cal["name"]) == "Indiana Fever (Next Home Game)"
    assert page in str(cal["x-wr-caldesc"]) and page in str(cal["description"])
    assert str(cal["url"]) == page
    assert str(cal["x-published-ttl"]) == "P1D"
    assert cal["refresh-interval"].params["VALUE"] == "DURATION"
    event = cal.walk("VEVENT")[0]
    assert f"More games and calendars: {page}" in str(event["description"])


def test_the_link_back_never_touches_a_uid():
    """Subscribers keep their events across this change: the UID is the
    same with or without a page link, under any base URL."""
    from wsc_pipeline.ics import league_calendar

    game = _game("EVT-STABLE")
    uids = {
        str(league_calendar("wnba", "WNBA", [game], base_url=base).walk("VEVENT")[0]["uid"])
        for base in (None, "https://nexthomegame.com", "https://example.org")
    }
    assert uids == {make_uid("EVT-STABLE")} == {"tm-EVT-STABLE@womens-sports-calendar.invalid"}


def test_an_unfetched_feed_still_says_why_it_is_empty_and_links_back():
    from wsc_pipeline.ics import league_calendar

    cal = league_calendar("wnba", "WNBA", [], fetched=False, base_url="https://nexthomegame.com")
    desc = str(cal["x-wr-caldesc"])
    assert desc.startswith("Not fetched") and "https://nexthomegame.com/wnba/" in desc
