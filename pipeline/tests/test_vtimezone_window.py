"""A feed's VTIMEZONE blocks cover the years its games fall in, not 1970 to
2038.

icalendar's Timezone.from_tzid defaults to every clock change from 1970 to
2038: about 2.7 KB per zone, written into every feed once per venue zone. On
2026-11-15 the live Ottawa Charge feed was 24.6 KB for 23 games, about 8 KB of
it its three time-zone blocks. The block now spans a year before the
first start in that zone to two years after the last, which still covers
every DTSTART and DTEND, and the TZID is still the IANA name.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from icalendar import Calendar

from wsc_pipeline.ics import build_calendar

from .conftest import BUILD_TIME
from .test_venue_time_zone import _game


def _zones(cal: Calendar) -> dict[str, list[datetime]]:
    """TZID -> every transition onset (DTSTART and RDATE) its block lists."""
    out: dict[str, list[datetime]] = {}
    for tz in cal.walk("VTIMEZONE"):
        onsets: list[datetime] = []
        for sub in tz.subcomponents:
            onsets.append(sub.decoded("dtstart"))
            rdates = sub.get("rdate")
            for rdate in rdates if isinstance(rdates, list) else [rdates] if rdates else []:
                onsets.extend(p.dt for p in rdate.dts)
        out[str(tz["tzid"])] = sorted(onsets)
    return out


def test_a_zone_block_spans_its_games_years_and_no_more():
    games = [
        _game("A", timezone="America/New_York", date_time="2026-12-06T19:00:00Z"),
        _game("B", timezone="America/New_York", date_time="2027-03-20T23:00:00Z"),
    ]
    cal = build_calendar(games, cal_name="x", dtstamp=BUILD_TIME, game_duration=timedelta(hours=2, minutes=30))
    onsets = _zones(cal)["America/New_York"]
    assert onsets[0].year == 2025
    assert onsets[-1].year == 2029
    raw = cal.to_ical()
    assert b"19700101" not in raw
    assert len(raw) < 2500


def test_every_event_time_falls_inside_its_zone_block():
    """Each DTSTART and DTEND, as written in the venue's zone, is after the
    block's first onset and before the year after its last."""
    games = [
        _game("NY", timezone="America/New_York", date_time="2027-01-01T01:00:00Z"),
        _game("LA", timezone="America/Los_Angeles", date_time="2026-12-31T22:00:00Z"),
    ]
    cal = build_calendar(games, cal_name="x", dtstamp=BUILD_TIME, game_duration=timedelta(hours=2, minutes=30))
    zones = _zones(cal)
    for event in cal.walk("VEVENT"):
        for prop in ("dtstart", "dtend"):
            value = event[prop]
            tzid = str(value.params["TZID"])
            local = value.dt.replace(tzinfo=None)
            onsets = zones[tzid]
            assert onsets[0] <= local, (tzid, prop)
            assert local.year <= onsets[-1].year, (tzid, prop)


def test_two_zones_get_one_block_each():
    games = [
        _game("E", timezone="America/New_York", date_time="2026-12-06T19:00:00Z"),
        _game("W", timezone="America/Los_Angeles", date_time="2026-12-07T03:00:00Z"),
        _game("E2", timezone="America/New_York", date_time="2026-12-09T00:00:00Z"),
    ]
    cal = build_calendar(games, cal_name="x", dtstamp=BUILD_TIME)
    assert sorted(_zones(cal)) == ["America/Los_Angeles", "America/New_York"]


def test_a_kept_played_event_widens_the_block():
    """A kept event from an earlier year (history.kept_played) is in the
    window too, so its DTSTART still has its transitions."""
    last_night = build_calendar(
        [_game("OLD", timezone="America/New_York", date_time="2026-12-30T23:00:00Z")],
        cal_name="x",
        dtstamp=BUILD_TIME,
    )
    kept = last_night.walk("VEVENT")
    tonight = build_calendar(
        [_game("NEW", timezone="America/New_York", date_time="2029-02-01T00:00:00Z")],
        cal_name="x",
        dtstamp=datetime(2029, 1, 15, tzinfo=UTC),
        kept=kept,
    )
    (block,) = _zones(tonight).values()
    assert block[0].year == 2025
    assert block[-1].year == 2031
