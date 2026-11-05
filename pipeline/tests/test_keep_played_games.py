"""Played games stay in the feeds for history.KEEP_PLAYED_DAYS, and a changed
event keeps its UID with SEQUENCE and LAST-MODIFIED moved (DECISIONS 0027).

Each scenario is two or three nightly builds in a row: the later build reads
the earlier one's real feeds over a mock transport, as it reads the live site.
Every clock is pinned, so nothing depends on today's date.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from icalendar import Calendar, Event

from wsc_pipeline import build as build_module
from wsc_pipeline import config, guard, history, validate_ics
from wsc_pipeline.ics import make_uid
from wsc_pipeline.site_data import records_dir

from .conftest import REAL_FETCH_PREVIOUS_PUBLISH, make_raw_event
from .test_build import _FakeDiscoveryClient

NIGHT_1 = datetime(2026, 6, 1, 8, 13, tzinfo=UTC)
NIGHT_2 = NIGHT_1 + timedelta(days=1)
NIGHT_3 = NIGHT_2 + timedelta(days=1)
BASE_URL = "https://nexthomegame.com"
FEVER = "indiana-fever"
LIBERTY = "new-york-liberty"
FEVER_FEED = f"ics/wnba/{FEVER}.ics"
LEAGUE_FEED = "ics/wnba.ics"
ALL_FEED = "ics/all.ics"


def _raw(event_id: str, start: datetime, *, opponent: str = "Chicago Sky", home: str = "Indiana Fever", **kw) -> dict:
    return make_raw_event(
        event_id=event_id,
        name=f"{home} vs {opponent}",
        date_time=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        local_date=start.strftime("%Y-%m-%d"),
        url=f"https://www.ticketmaster.com/event/{event_id}",
        **kw,
    )


def _liberty(n: int = 8) -> list[dict]:
    """Another team's later games, so a Fever-only change stays far from the
    publish guard's limits."""
    return [_raw(f"L{i}", NIGHT_1 + timedelta(days=20 + i), home="New York Liberty") for i in range(n)]


def _serve(dist: Path) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        target = dist / request.url.path.lstrip("/")
        return httpx.Response(200, content=target.read_bytes()) if target.is_file() else httpx.Response(404)

    return handler


def _read_live(dist: Path) -> guard.PreviousPublish:
    with httpx.Client(transport=httpx.MockTransport(_serve(dist))) as client:
        return REAL_FETCH_PREVIOUS_PUBLISH(BASE_URL, client=client)


def _build(out: Path, fever: list[dict], monkeypatch, *, now: datetime, previous_from: Path | None = None) -> None:
    responses = {FEVER: fever, LIBERTY: _liberty()}
    monkeypatch.setattr(build_module, "DiscoveryClient", lambda api_key: _FakeDiscoveryClient(responses))
    previous = _read_live(previous_from) if previous_from is not None else None
    build_module.build(
        out_dir=out, base_url=BASE_URL, api_key="fake-key", affiliate_id=None, previous_publish=previous, now=now
    )
    validate_ics.validate_dist(out)  # every scenario's output passes the deploy gate


def _events(dist: Path, feed: str) -> dict[str, Event]:
    cal = Calendar.from_ical((dist / feed).read_bytes())
    return {str(e["uid"]): e for e in cal.walk("VEVENT")}


def _without_dtstamp(vevent: Event) -> bytes:
    return b"\r\n".join(line for line in vevent.to_ical().split(b"\r\n") if not line.startswith(b"DTSTAMP"))


# --- played games are kept --------------------------------------------------------------------------------


def test_a_played_game_ticketmaster_delisted_stays_in_every_feed_as_published(tmp_path: Path, monkeypatch):
    played = _raw("P1", NIGHT_1 + timedelta(hours=12), opponent="Atlanta Dream")  # tips off after night 1
    later = [_raw(f"G{i}", NIGHT_1 + timedelta(days=5 + i)) for i in range(3)]
    night1, night2 = tmp_path / "n1", tmp_path / "n2"
    _build(night1, [played, *later], monkeypatch, now=NIGHT_1)
    _build(night2, later, monkeypatch, now=NIGHT_2, previous_from=night1)  # Ticketmaster dropped P1

    uid = make_uid("P1")
    for feed in (FEVER_FEED, LEAGUE_FEED, ALL_FEED):
        before, after = _events(night1, feed)[uid], _events(night2, feed)[uid]
        assert _without_dtstamp(after) == _without_dtstamp(before), feed  # nothing re-derived
        assert after.decoded("dtstamp") == NIGHT_2  # only the copy's stamp moves
        assert after.get("sequence") is None and "Canceled" not in str(after["summary"])
    # The atlanta-dream feed never had it (Atlanta was not the tracked side),
    # and the Fever's record names it as kept, for validate_ics.
    record = json.loads((records_dir(night2) / "wnba" / f"{FEVER}.json").read_text())
    assert record[history.KEPT_PLAYED_KEY] == ["P1"]
    assert "P1" not in {g["event_id"] for g in record["games"]}


def test_the_team_page_still_lists_only_what_ticketmaster_lists(tmp_path: Path, monkeypatch):
    """The deliberate choice: played games live in the feeds, not the pages."""
    played = _raw("P1", NIGHT_1 + timedelta(hours=12), opponent="Harbor Comets")  # a name no page links
    later = [_raw("G1", NIGHT_1 + timedelta(days=5))]
    night1, night2 = tmp_path / "n1", tmp_path / "n2"
    _build(night1, [played, *later], monkeypatch, now=NIGHT_1)
    _build(night2, later, monkeypatch, now=NIGHT_2, previous_from=night1)
    assert "Harbor Comets" in (night1 / "wnba" / FEVER / "index.html").read_text()
    assert "Harbor Comets" not in (night2 / "wnba" / FEVER / "index.html").read_text()
    assert make_uid("P1") in _events(night2, FEVER_FEED)


def test_a_kept_game_is_kept_again_the_next_night_with_its_bytes(tmp_path: Path, monkeypatch):
    played = _raw("P1", NIGHT_1 + timedelta(hours=12))
    later = [_raw("G1", NIGHT_1 + timedelta(days=5))]
    n1, n2, n3 = tmp_path / "n1", tmp_path / "n2", tmp_path / "n3"
    _build(n1, [played, *later], monkeypatch, now=NIGHT_1)
    _build(n2, later, monkeypatch, now=NIGHT_2, previous_from=n1)
    _build(n3, later, monkeypatch, now=NIGHT_3, previous_from=n2)
    uid = make_uid("P1")
    assert _without_dtstamp(_events(n3, FEVER_FEED)[uid]) == _without_dtstamp(_events(n1, FEVER_FEED)[uid])


def test_a_canceled_game_whose_date_passed_stays_marked_canceled(tmp_path: Path, monkeypatch):
    cancelled = _raw("C1", NIGHT_1 + timedelta(hours=12), status="cancelled")
    later = [_raw("G1", NIGHT_1 + timedelta(days=5))]
    night1, night2 = tmp_path / "n1", tmp_path / "n2"
    _build(night1, [cancelled, *later], monkeypatch, now=NIGHT_1)
    _build(night2, later, monkeypatch, now=NIGHT_2, previous_from=night1)
    kept = _events(night2, FEVER_FEED)[make_uid("C1")]
    assert str(kept["status"]) == "CANCELLED"
    assert str(kept["summary"]).startswith("Canceled: ")
    assert str(kept["description"]).startswith("Canceled: Ticketmaster lists this game as canceled.")


def test_a_delisted_game_that_has_not_started_is_not_kept(tmp_path: Path, monkeypatch):
    """Not played yet: keeping it would show a game that may be off as on."""
    soon = _raw("S1", NIGHT_2 + timedelta(hours=3))
    later = [_raw(f"G{i}", NIGHT_1 + timedelta(days=5 + i)) for i in range(3)]
    night1, night2 = tmp_path / "n1", tmp_path / "n2"
    _build(night1, [soon, *later], monkeypatch, now=NIGHT_1)
    _build(night2, later, monkeypatch, now=NIGHT_2, previous_from=night1)
    assert make_uid("S1") not in _events(night2, FEVER_FEED)


def test_a_removed_event_is_never_kept(tmp_path: Path, monkeypatch):
    played = _raw("R1", NIGHT_1 + timedelta(hours=12))
    later = [_raw("G1", NIGHT_1 + timedelta(days=5))]
    night1, night2 = tmp_path / "n1", tmp_path / "n2"
    _build(night1, [played, *later], monkeypatch, now=NIGHT_1)
    removal = config.EventRemoval(event_id="R1", recorded=date(2026, 6, 1), reason="test: removed on request")
    monkeypatch.setattr(config, "REMOVED_EVENTS", (removal,))
    _build(night2, later, monkeypatch, now=NIGHT_2, previous_from=night1)
    assert make_uid("R1") not in _events(night2, FEVER_FEED)
    assert make_uid("R1") not in _events(night2, ALL_FEED)


def test_a_game_ticketmaster_still_lists_is_written_fresh_not_kept(tmp_path: Path, monkeypatch):
    """A game still listed after it started (or a removed one still listed)
    is this build's to write; keeping is only for what Ticketmaster dropped."""
    started = _raw("P1", NIGHT_1 + timedelta(hours=12))
    night1, night2 = tmp_path / "n1", tmp_path / "n2"
    _build(night1, [started], monkeypatch, now=NIGHT_1)
    _build(night2, [started], monkeypatch, now=NIGHT_2, previous_from=night1)
    record = json.loads((records_dir(night2) / "wnba" / f"{FEVER}.json").read_text())
    assert record[history.KEPT_PLAYED_KEY] == []
    assert "P1" in {g["event_id"] for g in record["games"]}


def test_no_previous_publish_keeps_nothing_and_writes_no_revision_fields(tmp_path: Path, monkeypatch):
    out = tmp_path / "n1"
    _build(out, [_raw("G1", NIGHT_1 + timedelta(days=5))], monkeypatch, now=NIGHT_1)
    text = (out / FEVER_FEED).read_text()
    assert "SEQUENCE" not in text and "LAST-MODIFIED" not in text


# --- the keep window --------------------------------------------------------------------------------------


def _vevent(event_id: str, start: datetime | date) -> Event:
    event = Event()
    event.add("uid", make_uid(event_id))
    event.add("dtstamp", NIGHT_1)
    event.add("dtstart", start)
    event.add("summary", f"Game {event_id}")
    return event


def _kept_ids(events: list[Event], now: datetime, **kw) -> list[str | None]:
    kw.setdefault("listed_event_ids", frozenset())
    kw.setdefault("removed_event_ids", frozenset())
    return [history.event_id_of(e) for e in history.kept_played(events, now=now, **kw)]


def test_a_played_game_is_kept_for_120_days_and_then_drops_off():
    assert history.KEEP_PLAYED_DAYS == 120
    events = [
        _vevent("in", NIGHT_2 - timedelta(days=120)),  # exactly at the edge: kept
        _vevent("out", NIGHT_2 - timedelta(days=120, seconds=1)),
        _vevent("recent", NIGHT_2 - timedelta(hours=10)),
        _vevent("now", NIGHT_2),  # tipping off at the build: started
        _vevent("ahead", NIGHT_2 + timedelta(seconds=1)),
    ]
    assert _kept_ids(events, NIGHT_2) == ["in", "recent", "now"]


def test_an_all_day_game_is_kept_once_its_date_is_over():
    events = [
        _vevent("yesterday", NIGHT_2.date() - timedelta(days=1)),
        _vevent("today", NIGHT_2.date()),  # may be played later today, or not at all
        _vevent("edge", (NIGHT_2 - timedelta(days=120)).date()),
        _vevent("old", (NIGHT_2 - timedelta(days=121)).date()),
    ]
    assert _kept_ids(events, NIGHT_2) == ["yesterday", "edge"]


def test_listed_removed_and_foreign_events_are_not_kept():
    past = NIGHT_2 - timedelta(days=1)
    foreign = _vevent("x", past)
    foreign["UID"] = "someone-else@example.com"
    events = [_vevent("listed", past), _vevent("removed", past), foreign, _vevent("kept", past)]
    kept = _kept_ids(events, NIGHT_2, listed_event_ids=frozenset({"listed"}), removed_event_ids=frozenset({"removed"}))
    assert kept == ["kept"]


# --- revisions: same UID, SEQUENCE and LAST-MODIFIED ---------------------------------------------------------


def test_a_moved_game_keeps_its_uid_and_gets_sequence_1_and_last_modified(tmp_path: Path, monkeypatch):
    start = NIGHT_1 + timedelta(days=5)
    n1, n2, n3 = tmp_path / "n1", tmp_path / "n2", tmp_path / "n3"
    _build(n1, [_raw("G1", start), _raw("G2", start + timedelta(days=2))], monkeypatch, now=NIGHT_1)
    moved = [_raw("G1", start + timedelta(hours=2)), _raw("G2", start + timedelta(days=2)), _raw("G3", start)]
    _build(n2, moved, monkeypatch, now=NIGHT_2, previous_from=n1)

    for feed in (FEVER_FEED, LEAGUE_FEED, ALL_FEED):
        events = _events(n2, feed)
        g1, g2, g3 = (events[make_uid(i)] for i in ("G1", "G2", "G3"))
        assert int(g1["sequence"]) == 1 and g1.decoded("last-modified") == NIGHT_2, feed
        # Unchanged since a publish that recorded no LAST-MODIFIED: none is guessed.
        assert g2.get("sequence") is None and g2.get("last-modified") is None, feed
        # First published tonight, with every previous feed read: new now.
        assert g3.get("sequence") is None and g3.decoded("last-modified") == NIGHT_2, feed

    _build(n3, moved, monkeypatch, now=NIGHT_3, previous_from=n2)  # nothing changes on night 3
    g1 = _events(n3, FEVER_FEED)[make_uid("G1")]
    assert int(g1["sequence"]) == 1 and g1.decoded("last-modified") == NIGHT_2


def test_a_game_newly_canceled_raises_sequence(tmp_path: Path, monkeypatch):
    start = NIGHT_1 + timedelta(days=5)
    n1, n2 = tmp_path / "n1", tmp_path / "n2"
    others = [_raw(f"G{i}", start + timedelta(days=i)) for i in range(1, 4)]
    _build(n1, [_raw("C1", start), *others], monkeypatch, now=NIGHT_1)
    _build(n2, [_raw("C1", start, status="cancelled"), *others], monkeypatch, now=NIGHT_2, previous_from=n1)
    c1 = _events(n2, FEVER_FEED)[make_uid("C1")]
    assert str(c1["status"]) == "CANCELLED" and int(c1["sequence"]) == 1
    assert c1.decoded("last-modified") == NIGHT_2


def _event_with(**props: object) -> Event:
    event = _vevent("E", datetime(2026, 6, 10, 23, 0, tzinfo=UTC))
    for key, value in props.items():
        event.pop(key, None)
        event.add(key, value)
    return event


def test_a_text_only_change_moves_last_modified_but_not_sequence():
    before = _event_with(summary="Fever vs Sky", sequence=2)
    revisions = history.Revisions.from_previous([before], now=NIGHT_2, complete=True)
    after = _event_with(summary="Fever vs Sky (renamed)")
    revisions(after)
    assert int(after["sequence"]) == 2 and after.decoded("last-modified") == NIGHT_2


def test_the_same_instant_in_another_zone_is_not_a_change():
    from zoneinfo import ZoneInfo

    instant = datetime(2026, 6, 10, 23, 0, tzinfo=UTC)
    before = _event_with(dtstart=instant)
    revisions = history.Revisions.from_previous([before], now=NIGHT_2, complete=True)
    after = _event_with(dtstart=instant.astimezone(ZoneInfo("America/Chicago")))
    revisions(after)
    assert after.get("sequence") is None and after.get("last-modified") is None


def test_an_incompletely_read_previous_publish_calls_no_game_new():
    revisions = history.Revisions.from_previous([], now=NIGHT_2, complete=False)
    event = _vevent("NEW", NIGHT_2 + timedelta(days=3))
    revisions(event)
    assert event.get("last-modified") is None and event.get("sequence") is None


def test_the_highest_sequence_any_previous_feed_gave_wins():
    low, high = _event_with(sequence=1), _event_with(sequence=3, summary="later copy")
    revisions = history.Revisions.from_previous([low, high], now=NIGHT_2, complete=True)
    after = _event_with(sequence=0, summary="later copy")
    after.pop("sequence")
    revisions(after)
    assert int(after["sequence"]) == 3


def test_the_previous_publish_reads_the_league_feeds_too(tmp_path: Path, monkeypatch):
    night1 = tmp_path / "n1"
    _build(night1, [_raw("G1", NIGHT_1 + timedelta(days=5))], monkeypatch, now=NIGHT_1)
    previous = _read_live(night1)
    assert previous.fully_read
    assert {f"ics/{lg.slug}.ics" for lg in config.LEAGUES} <= set(previous.feeds)
    assert [str(e["uid"]) for e in previous.feeds[LEAGUE_FEED]] == [make_uid("G1")] + [
        make_uid(f"L{i}") for i in range(8)
    ]


def test_an_unreadable_league_feed_is_recorded_and_the_publish_is_not_fully_read(tmp_path: Path):
    night1 = tmp_path / "n1"
    serve = _serve(night1)
    night1.mkdir()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503) if request.url.path == f"/{LEAGUE_FEED}" else serve(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        previous = REAL_FETCH_PREVIOUS_PUBLISH(BASE_URL, client=client)
    assert previous.unreadable_feeds[LEAGUE_FEED] == "HTTP 503"
    assert not previous.fully_read


# --- validate_ics holds kept games to the rule ----------------------------------------------------------------


def _two_nights(tmp_path: Path, monkeypatch, **raw_kw) -> Path:
    played = _raw("P1", NIGHT_1 + timedelta(hours=12), **raw_kw)
    later = [_raw("G1", NIGHT_1 + timedelta(days=5))]
    night1, night2 = tmp_path / "n1", tmp_path / "n2"
    _build(night1, [played, *later], monkeypatch, now=NIGHT_1)
    _build(night2, later, monkeypatch, now=NIGHT_2, previous_from=night1)
    return night2


def _record(dist: Path) -> Path:
    return records_dir(dist) / "wnba" / f"{FEVER}.json"


def test_validate_refuses_a_kept_game_its_record_does_not_name(tmp_path: Path, monkeypatch):
    dist = _two_nights(tmp_path, monkeypatch)
    payload = json.loads(_record(dist).read_text())
    payload[history.KEPT_PLAYED_KEY] = []
    _record(dist).write_text(json.dumps(payload))
    with pytest.raises(validate_ics.FeedError, match="in the feed but not the page's data"):
        validate_ics.validate_dist(dist)


def test_validate_refuses_a_kept_game_older_than_the_window(tmp_path: Path, monkeypatch):
    dist = _two_nights(tmp_path, monkeypatch)
    payload = json.loads(_record(dist).read_text())
    payload["fetched_at"] = (NIGHT_2 + timedelta(days=history.KEEP_PLAYED_DAYS + 1)).isoformat()
    _record(dist).write_text(json.dumps(payload))
    with pytest.raises(validate_ics.FeedError, match="more than 120 days ago"):
        validate_ics.validate_feed(dist / FEVER_FEED, _record(dist), f"/wnba/{FEVER}/")


def test_validate_refuses_a_kept_game_that_has_not_started(tmp_path: Path, monkeypatch):
    dist = _two_nights(tmp_path, monkeypatch)
    payload = json.loads(_record(dist).read_text())
    payload["fetched_at"] = NIGHT_1.isoformat()  # before P1's start
    _record(dist).write_text(json.dumps(payload))
    with pytest.raises(validate_ics.FeedError, match="has not started"):
        validate_ics._check_kept_played(
            dist / FEVER_FEED,
            _events(dist, FEVER_FEED),
            {make_uid("P1")},
            payload["fetched_at"],
        )


def test_validate_refuses_a_kept_canceled_game_that_lost_its_marker(tmp_path: Path, monkeypatch):
    dist = _two_nights(tmp_path, monkeypatch, status="cancelled")
    feed = dist / FEVER_FEED
    text = feed.read_bytes()
    assert b"SUMMARY:Canceled: " in text
    feed.write_bytes(text.replace(b"SUMMARY:Canceled: ", b"SUMMARY:"))
    with pytest.raises(validate_ics.FeedError, match="SUMMARY or DESCRIPTION drops it"):
        validate_ics.validate_feed(feed, _record(dist), f"/wnba/{FEVER}/")


def test_validate_refuses_a_kept_game_that_was_removed_on_request(tmp_path: Path, monkeypatch):
    dist = _two_nights(tmp_path, monkeypatch)
    removal = config.EventRemoval(event_id="P1", recorded=date(2026, 6, 2), reason="test: removed on request")
    monkeypatch.setattr(config, "REMOVED_EVENTS", (removal,))
    with pytest.raises(validate_ics.FeedError, match="removed on request"):
        validate_ics.validate_feed(dist / FEVER_FEED, _record(dist), f"/wnba/{FEVER}/")


def test_validate_refuses_a_game_both_kept_and_listed(tmp_path: Path, monkeypatch):
    dist = _two_nights(tmp_path, monkeypatch)
    payload = json.loads(_record(dist).read_text())
    payload[history.KEPT_PLAYED_KEY] = ["P1", "G1"]
    _record(dist).write_text(json.dumps(payload))
    with pytest.raises(validate_ics.FeedError, match="also one of its page's games"):
        validate_ics.validate_feed(dist / FEVER_FEED, _record(dist), f"/wnba/{FEVER}/")


def test_the_guard_does_not_count_a_kept_game_as_upcoming(tmp_path: Path, monkeypatch):
    """Night 3 reads night 2's feed, which keeps P1: P1 is in the past, so
    when it later drops off nothing is called vanished."""
    played = _raw("P1", NIGHT_1 + timedelta(hours=12))
    later = [_raw(f"G{i}", NIGHT_1 + timedelta(days=5 + i)) for i in range(3)]
    n1, n2 = tmp_path / "n1", tmp_path / "n2"
    _build(n1, [played, *later], monkeypatch, now=NIGHT_1)
    _build(n2, later, monkeypatch, now=NIGHT_2, previous_from=n1)
    previous = _read_live(n2)
    report = guard.evaluate(previous, [], {}, now=NIGHT_2 + timedelta(days=200), overrides=())
    assert all(v.event_id != "P1" for v in report.vanished)
