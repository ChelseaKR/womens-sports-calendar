"""Games with a known date and no announced start time, in the .ics feeds.

They used to be left out, so a subscriber to a team whose schedule was mostly
time-TBA saw almost nothing. They are now all-day events on their local date
(DTSTART;VALUE=DATE), with "(time TBA)" in the title, no end time and no time
shown or implied. The UID is the timed event's UID, so the same event updates
in place when Ticketmaster lists the time. Games with no date at all stay out.

How Apple, Google and Outlook calendars treat an event whose DTSTART changes
from a date to a date-time under the same UID has NOT been tested; nothing
here claims it. What these tests do pin is the UID and the bytes.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from icalendar import Calendar

from wsc_pipeline import build as build_module
from wsc_pipeline import validate_ics
from wsc_pipeline.config import LEAGUES
from wsc_pipeline.coverage import BuildCoverage, compute_league_coverage, render_report
from wsc_pipeline.ics import TIME_TBA_NOTE, TIME_TBA_SUFFIX, build_calendar, make_uid
from wsc_pipeline.normalize import feed_start, normalize_event
from wsc_pipeline.site_data import team_data

from . import rfc5545
from .conftest import BUILD_TIME, make_raw_event
from .fixture_site import build_fixture_site

WNBA = LEAGUES[0]
TEAM_A = WNBA.teams[0]
NAME = f"{TEAM_A.name} vs Visiting Team"


def _game(event_id: str, **kwargs):
    raw = make_raw_event(event_id=event_id, name=NAME, **kwargs)
    game = normalize_event(raw, league_slug=WNBA.slug, tracked_team_slug=TEAM_A.slug, tracked_team_name=TEAM_A.name)
    assert game is not None
    return game


def _tba(event_id: str, **kwargs):
    kwargs = {"date_time": None, "local_date": "2026-06-24", "local_time": None, "time_tba": True, **kwargs}
    return _game(event_id, **kwargs)


def _timed(event_id: str, **kwargs):
    kwargs = {"date_time": "2026-06-24T23:00:00Z", "local_date": "2026-06-24", "local_time": "19:00:00", **kwargs}
    return _game(event_id, **kwargs)


def _bytes(games, **kwargs) -> bytes:
    kwargs.setdefault("game_duration", timedelta(hours=2, minutes=30))
    return build_calendar(games, cal_name="T", dtstamp=BUILD_TIME, **kwargs).to_ical()


def _text(prop) -> str:
    return rfc5545.unescape_text(prop.value)


def test_a_time_tba_game_is_an_all_day_event_on_its_local_date():
    raw = _bytes([_tba("T1")])
    (vevent,) = rfc5545.parse(raw).walk("VEVENT")
    dtstart = vevent.first("DTSTART")
    assert (dtstart.param("VALUE"), dtstart.value, dtstart.param("TZID")) == ("DATE", "20260624", None)
    assert _text(vevent.first("SUMMARY")) == f"{NAME}{TIME_TBA_SUFFIX}" == f"{NAME} (time TBA)"
    assert TIME_TBA_NOTE in _text(vevent.first("DESCRIPTION")).split("\n")
    assert b"DTSTART;VALUE=DATE:20260624\r\n" in raw


def test_no_time_end_or_estimate_is_shown_or_implied_for_it():
    """Never invent a time: no DTEND (even with a game length configured), no
    "end estimated" line, no zone, and no VTIMEZONE for a calendar with
    nothing timed."""
    raw = _bytes([_tba("T2")])
    (vevent,) = rfc5545.parse(raw).walk("VEVENT")
    assert vevent.first("DTEND") is None and vevent.first("DURATION") is None
    description = _text(vevent.first("DESCRIPTION"))
    assert "End time estimated" not in description
    assert b"TZID" not in raw and b"VTIMEZONE" not in raw
    event_block = raw[raw.index(b"BEGIN:VEVENT") :]
    assert b"T1900" not in event_block and b"T2300" not in event_block


def test_the_uid_is_byte_identical_when_a_game_goes_from_time_tba_to_timed():
    """The same Ticketmaster event id, first without a time and then with one:
    one UID, so a subscriber's copy is the same event. Only DTSTART changes,
    from a date to a date-time."""
    before = _bytes([_tba("SAME-1")])
    after = _bytes([_timed("SAME-1")])
    uid = [f"UID:{make_uid('SAME-1')}".encode()]
    assert [ln for ln in before.split(b"\r\n") if ln.startswith(b"UID:")] == uid
    assert [ln for ln in after.split(b"\r\n") if ln.startswith(b"UID:")] == uid
    (a,), (b,) = (rfc5545.parse(x).walk("VEVENT") for x in (before, after))
    assert (a.first("DTSTART").param("VALUE"), a.first("DTSTART").value) == ("DATE", "20260624")
    assert (b.first("DTSTART").param("VALUE"), b.first("DTSTART").value) == (None, "20260624T190000")
    assert b.first("DTSTART").param("TZID") == "America/Indiana/Indianapolis"


def test_a_time_tba_game_with_a_placeholder_datetime_is_still_all_day():
    """Ticketmaster could send timeTBA together with a placeholder dateTime;
    the placeholder is never published as a start."""
    game = _game(
        "PLACEHOLDER-1",
        date_time="2026-06-25T03:59:00Z",
        local_date="2026-06-24",
        local_time="23:59:00",
        time_tba=True,
    )
    assert game.start_utc is not None  # the placeholder really arrived
    raw = _bytes([game])
    (vevent,) = rfc5545.parse(raw).walk("VEVENT")
    assert vevent.first("DTSTART").param("VALUE") == "DATE"
    assert vevent.first("DTSTART").value == "20260624"
    assert vevent.first("DTEND") is None
    assert b"035900" not in raw and b"235900" not in raw


def test_a_game_with_no_date_at_all_is_still_left_out():
    tbd = _game("TBD-1", date_time=None, local_date="2026-08-01", local_time=None, date_tbd=True)
    both = _game("TBD-2", date_time=None, local_date="2026-08-01", local_time=None, date_tbd=True, time_tba=True)
    assert feed_start(tbd) is None and feed_start(both) is None
    assert build_calendar([tbd, both], cal_name="T", dtstamp=BUILD_TIME).walk("VEVENT") == []


def test_a_date_with_a_local_time_but_no_instant_is_still_left_out_as_before():
    """Not announced-time (a local time was sent) and not an exact instant: no
    all-day placeholder claiming the time is TBA."""
    game = _game("ODD-1", date_time=None, local_date="2026-06-24", local_time="18:00:00")
    assert feed_start(game) is None
    assert build_calendar([game], cal_name="T", dtstamp=BUILD_TIME).walk("VEVENT") == []


def test_a_canceled_time_tba_game_says_both():
    (vevent,) = rfc5545.parse(_bytes([_tba("T3", status="cancelled")])).walk("VEVENT")
    assert vevent.first("STATUS").value == "CANCELLED"
    assert _text(vevent.first("SUMMARY")) == f"Canceled: {NAME} (time TBA)"


def test_all_day_and_timed_games_are_in_date_order_and_the_feed_is_valid_rfc5545():
    games = [
        _timed("LATE", date_time="2026-06-30T23:00:00Z", local_date="2026-06-30"),
        _tba("MID"),
        _timed("EARLY", date_time="2026-06-10T23:00:00Z", local_date="2026-06-10"),
    ]
    cal = rfc5545.parse(_bytes(games))
    assert [v.first("UID").value for v in cal.walk("VEVENT")] == [make_uid(x) for x in ("EARLY", "MID", "LATE")]


def test_the_page_says_a_time_tba_game_is_in_the_feed_and_a_date_tbd_game_is_not():
    tba = _tba("PAGE-1")
    tbd = _game("PAGE-2", date_time=None, local_date="2026-08-01", local_time=None, date_tbd=True)
    payload = team_data(TEAM_A, WNBA, [tba, tbd])
    by_id = {g["event_id"]: g for g in payload["games"]}
    assert by_id["PAGE-1"]["in_calendar_feed"] is True and by_id["PAGE-1"]["time_tba"] is True
    assert by_id["PAGE-2"]["in_calendar_feed"] is False


def test_the_coverage_report_counts_all_day_and_every_other_exclusion():
    games = [
        _timed("C-TIMED"),
        _tba("C-TBA-1"),
        _tba("C-TBA-2", local_date="2026-06-25"),
        _game("C-TBD", date_time=None, local_date="2026-08-01", local_time=None, date_tbd=True),
        _game("C-ODD", date_time=None, local_date="2026-06-24", local_time="18:00:00"),
    ]
    lc = compute_league_coverage(WNBA, games, set())
    assert (lc.games_total, lc.games_all_day, lc.games_date_tbd, lc.games_other_excluded) == (5, 2, 1, 1)
    report = render_report(BuildCoverage(leagues=[lc], requests_made=1, bytes_received=1, api_key_present=True))
    assert (
        "date TBD (excluded from .ics): 1; time TBA (all-day in .ics): 2; other games excluded from .ics: 1" in report
    )


# --- a real build and the validator -----------------------------------------


def _built(tmp_path: Path, monkeypatch) -> Path:
    games = [
        _timed("V-TIMED"),
        _tba("V-TBA"),
        _game("V-TBD", date_time=None, local_date="2026-08-01", local_time=None, date_tbd=True),
    ]
    empty = {lg.slug: set() for lg in LEAGUES}
    monkeypatch.setattr(build_module, "fetch_all_games", lambda api_key: (games, empty, empty, 1, 1))
    out_dir = tmp_path / "dist"
    build_module.build(out_dir=out_dir, base_url="https://nexthomegame.com", api_key="fake-key", affiliate_id=None)
    return out_dir


def test_a_build_with_a_time_tba_game_validates_and_carries_it_in_both_feeds(tmp_path: Path, monkeypatch):
    dist = _built(tmp_path, monkeypatch)
    assert validate_ics.main([str(dist)]) == 0
    for feed in (dist / "ics" / "wnba.ics", dist / "ics" / "wnba" / f"{TEAM_A.slug}.ics"):
        by_uid = {v.first("UID").value: v for v in rfc5545.parse(feed.read_bytes()).walk("VEVENT")}
        assert set(by_uid) == {make_uid("V-TIMED"), make_uid("V-TBA")}  # not the TBD-date game
        assert by_uid[make_uid("V-TBA")].first("DTSTART").param("VALUE") == "DATE"
        assert by_uid[make_uid("V-TIMED")].first("DTEND") is not None  # estimated, timed only
        assert by_uid[make_uid("V-TBA")].first("DTEND") is None


def test_the_fixture_sites_time_tba_game_is_an_all_day_entry_in_its_feeds(tmp_path: Path):
    """`make validate-fixture-site` runs validate_ics on this site."""
    dist = tmp_path / "fixture"
    build_fixture_site(dist)
    assert validate_ics.main([str(dist)]) == 0
    for feed in (dist / "ics" / "wnba.ics", dist / "ics" / "wnba" / "las-vegas-aces.ics"):
        by_uid = {v.first("UID").value: v for v in rfc5545.parse(feed.read_bytes()).walk("VEVENT")}
        vevent = by_uid[make_uid("FX-TIME-TBA")]
        assert vevent.first("DTSTART").value == "20260924" and vevent.first("DTSTART").param("VALUE") == "DATE"
        assert _text(vevent.first("SUMMARY")) == "Las Vegas Aces vs Atlanta Dream (time TBA)"
        assert make_uid("FX-DATE-TBD") not in by_uid


def _tamper(dist: Path, uid: str, sabotage) -> None:
    feed = dist / "ics" / WNBA.slug / f"{TEAM_A.slug}.ics"
    cal = Calendar.from_ical(feed.read_bytes())
    (vevent,) = [v for v in cal.walk("VEVENT") if str(v["uid"]) == make_uid(uid)]
    before = vevent.to_ical()
    sabotage(vevent)
    assert vevent.to_ical() != before, "the sabotage did not apply"
    feed.write_bytes(cal.to_ical())


def _give_it_a_made_up_time(vevent) -> None:
    del vevent["dtstart"]
    vevent.add("dtstart", datetime(2026, 6, 24, 0, 0))


def _give_it_an_end(vevent) -> None:
    vevent.add("dtend", date(2026, 6, 25))


def _drop_the_suffix(vevent) -> None:
    vevent["summary"] = str(vevent["summary"]).removesuffix(TIME_TBA_SUFFIX)


def _drop_the_note(vevent) -> None:
    vevent["description"] = str(vevent["description"]).replace(TIME_TBA_NOTE, "")


def _move_the_date(vevent) -> None:
    del vevent["dtstart"]
    vevent.add("dtstart", date(2026, 6, 25))


@pytest.mark.parametrize(
    "sabotage,match",
    [
        (_give_it_a_made_up_time, "never a made-up time"),
        (_give_it_an_end, "has an end time"),
        (_drop_the_suffix, "does not say the time is TBA"),
        (_drop_the_note, "lacks the time-TBA note"),
        (_move_the_date, "never a made-up time"),
    ],
)
def test_a_feed_that_shows_a_time_for_a_game_whose_time_is_not_announced_fails(
    tmp_path: Path, monkeypatch, sabotage, match
):
    dist = _built(tmp_path, monkeypatch)
    _tamper(dist, "V-TBA", sabotage)
    with pytest.raises(validate_ics.FeedError, match=match):
        validate_ics.validate_dist(dist)


def test_a_feed_that_drops_a_time_tba_game_its_page_lists_fails(tmp_path: Path, monkeypatch):
    dist = _built(tmp_path, monkeypatch)
    feed = dist / "ics" / WNBA.slug / f"{TEAM_A.slug}.ics"
    cal = Calendar.from_ical(feed.read_bytes())
    cal.subcomponents = [c for c in cal.subcomponents if str(c.get("uid", "")) != make_uid("V-TBA")]
    feed.write_bytes(cal.to_ical())
    with pytest.raises(validate_ics.FeedError, match="disagree"):
        validate_ics.validate_dist(dist)


def test_a_feed_that_turns_a_timed_game_into_an_all_day_one_fails(tmp_path: Path, monkeypatch):
    dist = _built(tmp_path, monkeypatch)

    def make_all_day(vevent) -> None:
        del vevent["dtstart"]
        vevent.add("dtstart", date(2026, 6, 24))

    _tamper(dist, "V-TIMED", make_all_day)
    with pytest.raises(validate_ics.FeedError, match="exact start on its page but an all-day DTSTART"):
        validate_ics.validate_dist(dist)
