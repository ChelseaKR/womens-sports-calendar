"""A ticket link is an https address on a listed host, or it is left out
(DECISIONS 0044).

The link comes from Ticketmaster's Discovery API and is shown on the pages,
in the structured data and in every calendar feed. These tests put links on
other hosts through the real path (normalize -> pages, records and feeds,
and a feed's kept played games) and check that the game is still listed and
the link is gone. Each negative control first shows its link differs from
the listed one.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import pytest
from icalendar import Calendar, Event

from wsc_pipeline import build as build_module
from wsc_pipeline import coverage, history, ics, official_tickets, sellers, ticket_hosts, validate_ics
from wsc_pipeline.config import LEAGUES
from wsc_pipeline.normalize import feed_ticket_url, normalize_event, safe_ticket_url
from wsc_pipeline.site import render_team
from wsc_pipeline.site_data import game_to_dict, records_dir, team_data
from wsc_pipeline.structured_data import event_offer_url

from .conftest import BUILD_TIME, make_raw_event
from .test_build import _FakeDiscoveryClient
from .test_keep_played_games import BASE_URL, FEVER, FEVER_FEED, LEAGUE_FEED, LIBERTY, NIGHT_1, _liberty, _read_live

WNBA = next(lg for lg in LEAGUES if lg.slug == "wnba")
ACES = next(t for t in WNBA.teams if t.slug == "las-vegas-aces")
LISTED = "https://www.ticketmaster.com/event/X1"
ELSEWHERE = "https://tickets.example.org/event/X1"

# The hosts the live league feeds carried on 2026-11-17 (619 events).
LIVE_HOSTS = ("www.ticketmaster.com", "www.ticketmaster.ca")


def _away_game(url: str | None):
    """An Aces away game: its ticket link is the event's own."""
    raw = make_raw_event(event_id="X1", name="Seattle Storm vs Las Vegas Aces", url=url)
    game = normalize_event(raw, league_slug="wnba", tracked_team_slug=ACES.slug, tracked_team_name=ACES.name)
    assert game is not None
    return game


# ---- the list ----------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        LISTED,
        "https://www.ticketmaster.ca/event/X1?lang=en-ca",
        "https://ticketmaster.com/event/X1",
        "https://am.ticketmaster.com/mizzou/buy/mizzouwomensbasketball",
        "https://concerts.livenation.com/event/X1",
        "https://www.gofevo.com/event/abc",
        "HTTPS://WWW.TICKETMASTER.COM/event/X1",
        "https://www.ticketmaster.com:443/event/X1",
        # A team's recorded seller, and a team's own ticket page.
        "https://www.axs.com/teams/1104736/las-vegas-aces-tickets",
        "https://seatgeek.com/portland-thorns-fc-tickets",
        "https://www.seatgeek.com/portland-thorns-fc-tickets",
        "https://gophersports.evenue.net/list/WBB",
    ],
)
def test_an_https_link_on_a_listed_host_is_kept_as_it_is(url: str) -> None:
    assert safe_ticket_url(url) == url
    assert ticket_hosts.is_listed_https(url)


@pytest.mark.parametrize(
    "url",
    [
        ELSEWHERE,
        "http://www.ticketmaster.com/event/X1",  # not https
        "https://ticketmaster.com.example.org/event/X1",
        "https://notticketmaster.com/event/X1",
        "https://www.ticketmaster.co/event/X1",
        "https://www.ticketmaster.com.mx/event/X1",  # not a listed domain
        "https://www.universe.com/events/x",
        "https://example.org/?next=https://www.ticketmaster.com/event/X1",
        "https://www.ticketmaster.com@example.org/event/X1",
        "https://user:pw@www.ticketmaster.com/event/X1",
        "https://www.ticketmaster.com:8443/event/X1",
        "https://www.ticketmaster.com:x/event/X1",
        "https://example.org\\.ticketmaster.com/event/X1",
        "https://example.org\\@www.ticketmaster.com/event/X1",
        "https://www.ticketmaster.com/event/X1\n",
        " https://www.ticketmaster.com/event/X1",
        "https://www.ticket\tmaster.com/event/X1",
        "https://www.ticketmaster.com./event/X1",
        "https://www.t\u0131cketmaster.com/event/X1",  # a dotless i
        "https://[::1]/event/X1",
        # A seller's other hosts are not the recorded one.
        "https://evil.evenue.net/list/WBB",
        "https://tickets.axs.com.example.org/x",
        "//www.ticketmaster.com/event/X1",
        "www.ticketmaster.com/event/X1",
        "",
        None,
        42,
        ["https://www.ticketmaster.com/event/X1"],
    ],
)
def test_any_other_link_is_left_out(url: object) -> None:
    assert url != LISTED  # the sabotage applied
    assert safe_ticket_url(url) is None
    assert not ticket_hosts.is_listed_https(url)


def test_the_hosts_in_the_live_feeds_today_are_listed() -> None:
    for host in LIVE_HOSTS:
        assert ticket_hosts.host_is_listed(host), host
        url = f"https://{host}/indiana-fever-vs-chicago-sky/event/05006123ABCD"
        assert safe_ticket_url(url) == url


def test_every_host_this_repository_records_is_listed_and_https() -> None:
    """Nothing the site already links for tickets is dropped: each recorded
    seller page, official ticket page and labelled Discovery host passes."""
    pages = [s.team_page_url for s in sellers.PRIMARY_SELLERS.values()]
    pages += [p.url for p in official_tickets.OFFICIAL_TEAM_TICKETS.values()]
    pages += [p.url for p in official_tickets.OFFICIAL_LEAGUE_TICKETS.values()]
    assert len(pages) > 100
    for url in pages:
        assert ticket_hosts.is_listed_https(url), url
    for domain in sellers._HOST_LABELS:
        assert domain in ticket_hosts.LISTED_DOMAINS, domain
        assert ticket_hosts.is_listed_https(f"https://www.{domain}/event/X1")
    # The recorded hosts are exact: no other host of a seller's domain.
    recorded = ticket_hosts.recorded_seller_hosts()
    assert "gophersports.evenue.net" in recorded
    assert "evenue.net" not in recorded
    assert all(host and not host.startswith("www.") for host in recorded)


# ---- tracking links ----------------------------------------------------------


def _wrap(url: str, tracking: str) -> str:
    return f"{tracking}?u={quote(url, safe='')}"


def test_a_tracking_link_is_judged_by_where_it_goes_and_what_it_is_on() -> None:
    impact = "https://ticketmaster.evyy.net/c/1234567/264167/4272"
    kept = _wrap(LISTED, impact)
    assert safe_ticket_url(kept) == kept
    for bad in (
        _wrap(ELSEWHERE, impact),  # goes somewhere not listed
        _wrap("http://www.ticketmaster.com/event/X1", impact),  # goes to http
        _wrap(LISTED, "https://go.brandclicks.example/c/1234567/264167/4272"),  # a host that is not Impact's
        _wrap(LISTED, "http://ticketmaster.evyy.net/c/1234567/264167/4272"),  # not https itself
        "https://ticketmaster.pxf.io/AbC12",  # nowhere to read where it goes
        impact,
        # A listed host with a tracking-link path that goes elsewhere.
        _wrap(ELSEWHERE, "https://www.ticketmaster.com/c/1/2/3"),
    ):
        assert bad != kept  # the sabotage applied
        assert safe_ticket_url(bad) is None, bad
    # The label never names a site the link does not go to.
    game = _away_game(_wrap(LISTED, "https://go.brandclicks.example/c/1234567/264167/4272"))
    assert sellers.buy_link(game) is None


# ---- pages, records and feeds --------------------------------------------------


def _event(game) -> Event:
    (vevent,) = ics.build_calendar([game], cal_name="t", dtstamp=BUILD_TIME).walk("VEVENT")
    return vevent


def test_a_game_with_a_link_elsewhere_is_listed_everywhere_without_it() -> None:
    listed, elsewhere = _away_game(LISTED), _away_game(ELSEWHERE)
    # The control: the listed link reaches each place.
    assert sellers.buy_link(listed) == {"url": LISTED, "seller": "Ticketmaster", "home_team": ""}
    assert str(_event(listed)["url"]) == LISTED
    assert f"Buy: {LISTED}" in str(_event(listed)["description"])
    assert game_to_dict(listed)["ticket_url"] == LISTED
    assert listed.ticket_link_left_out is False
    # The same game with a link on another host.
    assert elsewhere.ticket_url is None
    assert elsewhere.ticket_link_left_out is True
    assert sellers.buy_link(elsewhere) is None
    vevent = _event(elsewhere)
    assert vevent.get("url") is None
    assert "Buy:" not in str(vevent["description"])
    assert str(vevent["summary"]) == str(_event(listed)["summary"]), "the game is still in the feed"
    record = game_to_dict(elsewhere)
    assert record["ticket_url"] is None
    assert event_offer_url(record) is None
    assert event_offer_url(game_to_dict(listed)) == LISTED
    page = render_team(team=team_data(ACES, WNBA, [elsewhere]), base_url=BASE_URL)
    assert "Seattle Storm" in page, "the game is still on the page"
    assert "example.org" not in page


def test_a_game_built_another_way_cannot_carry_a_link_elsewhere() -> None:
    """The feed and the buy link check the host again, so a Game that did
    not come through normalize_event is held to the same list."""
    forged = dataclasses.replace(_away_game(LISTED), ticket_url=ELSEWHERE)
    assert forged.ticket_url == ELSEWHERE  # the sabotage applied
    assert feed_ticket_url(forged) is None
    assert sellers.buy_link(forged) is None
    assert _event(forged).get("url") is None
    http = dataclasses.replace(_away_game(LISTED), ticket_url="http://www.ticketmaster.com/event/X1")
    assert feed_ticket_url(http) is None


def test_the_coverage_report_counts_links_left_out() -> None:
    games = [_away_game(LISTED), dataclasses.replace(_away_game(ELSEWHERE), event_id="X2")]
    league = coverage.compute_league_coverage(WNBA, games, set())
    assert league.ticket_links_left_out == 1
    report = coverage.render_report(
        coverage.BuildCoverage(leagues=[league], requests_made=1, bytes_received=1, api_key_present=True)
    )
    assert "1 game(s) are listed with no ticket link" in report
    assert "example.org" not in report, "the report gives a count, not the address"
    none_left_out = coverage.compute_league_coverage(WNBA, [_away_game(LISTED)], set())
    assert "no ticket link" not in coverage.render_report(
        coverage.BuildCoverage(leagues=[none_left_out], requests_made=1, bytes_received=1, api_key_present=True)
    )
    # A game Ticketmaster sent no link for is not counted as left out.
    assert _away_game(None).ticket_link_left_out is False


# ---- a feed's kept played games --------------------------------------------------


def _kept(url: str | None, buy_line: str | None) -> Event:
    """A played game as an earlier build published it, run through
    history.kept_played."""
    vevent = Event()
    vevent.add("uid", ics.make_uid("P1"))
    vevent.add("dtstamp", NIGHT_1)
    vevent.add("dtstart", NIGHT_1 - timedelta(days=3))
    vevent.add("summary", "Indiana Fever vs Chicago Sky")
    if url is not None:
        vevent.add("url", url)
    lines = ["League: WNBA", *([buy_line] if buy_line else []), f"More games and calendars: {BASE_URL}/wnba/"]
    vevent.add("description", "\n".join(lines))
    (kept,) = history.kept_played([vevent], listed_event_ids=frozenset(), removed_event_ids=frozenset(), now=NIGHT_1)
    return kept


def test_a_kept_game_keeps_a_listed_link_and_loses_any_other() -> None:
    ok = _kept(LISTED, f"Buy: {LISTED}")
    assert str(ok["url"]) == LISTED
    assert f"Buy: {LISTED}" in str(ok["description"])
    for url, line in (
        (ELSEWHERE, f"Buy: {ELSEWHERE}"),
        ("http://www.ticketmaster.com/event/P1", "Buy: http://www.ticketmaster.com/event/P1"),
        ("https://ticketmaster.evyy.net/c/1/2/3?u=" + quote(LISTED, safe=""), None),
    ):
        assert url != LISTED  # the sabotage applied
        kept = _kept(url, line)
        assert kept.get("url") is None, url
        description = str(kept["description"])
        assert "Buy:" not in description, url
        # Nothing else about the game changes.
        assert str(kept["summary"]) == "Indiana Fever vs Chicago Sky"
        assert description.split("\n") == ["League: WNBA", f"More games and calendars: {BASE_URL}/wnba/"]
    # A link only in the description is taken out the same way.
    only_line = _kept(None, f"Buy: {ELSEWHERE}")
    assert "example.org" not in only_line.to_ical().decode()


def _tamper(dist: Path, old: str, new: str) -> None:
    """Rewrite one address in every published feed, as a build before this
    rule could have published it."""
    changed = 0
    for feed in (dist / "ics").rglob("*.ics"):
        text = feed.read_bytes()
        if old.encode() in text:
            feed.write_bytes(text.replace(old.encode(), new.encode()))
            changed += 1
    assert changed, "the sabotage applied"


def _raw(event_id: str, start: datetime) -> dict:
    return make_raw_event(
        event_id=event_id,
        name="Indiana Fever vs Chicago Sky",
        date_time=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        local_date=start.strftime("%Y-%m-%d"),
        url=f"https://www.ticketmaster.com/event/{event_id}",
    )


def _build(out: Path, fever: list[dict], monkeypatch, *, now: datetime, previous_from: Path | None = None) -> None:
    responses = {FEVER: fever, LIBERTY: _liberty()}
    monkeypatch.setattr(build_module, "DiscoveryClient", lambda api_key: _FakeDiscoveryClient(responses))
    previous = _read_live(previous_from) if previous_from is not None else None
    build_module.build(
        out_dir=out, base_url=BASE_URL, api_key="fake-key", affiliate_id=None, previous_publish=previous, now=now
    )


def test_a_played_game_published_with_a_link_elsewhere_is_kept_without_it(tmp_path: Path, monkeypatch) -> None:
    """Two nightly builds. The first night's feeds are then changed to carry
    a link on another host for the game that is played by the second night,
    as a build before this rule could have published. The second build keeps
    the played game, without that link, and passes the deploy gate."""
    played = _raw("P1", NIGHT_1 + timedelta(hours=6))
    later = _raw("F1", NIGHT_1 + timedelta(days=9))
    first, second = tmp_path / "night1", tmp_path / "night2"
    _build(first, [played, later], monkeypatch, now=NIGHT_1)
    _tamper(first, "https://www.ticketmaster.com/event/P1", "https://tickets.example.org/event/P1")
    _build(second, [later], monkeypatch, now=NIGHT_1 + timedelta(days=1), previous_from=first)
    validate_ics.validate_dist(second)
    uid = ics.make_uid("P1")
    for feed in (FEVER_FEED, LEAGUE_FEED, "ics/all.ics"):
        events = {str(e["uid"]): e for e in Calendar.from_ical((second / feed).read_bytes()).walk("VEVENT")}
        assert uid in events, f"{feed}: the played game is still in the feed"
        assert events[uid].get("url") is None, feed
        assert b"example.org" not in (second / feed).read_bytes(), feed
        assert str(events[ics.make_uid("F1")]["url"]) == "https://www.ticketmaster.com/event/F1", feed
    assert "P1" in json.loads((records_dir(second) / "wnba" / f"{FEVER}.json").read_text())[history.KEPT_PLAYED_KEY]


def test_the_deploy_gate_refuses_a_feed_with_a_link_elsewhere(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "dist"
    _build(out, [_raw("F1", NIGHT_1 + timedelta(days=9))], monkeypatch, now=NIGHT_1)
    validate_ics.validate_dist(out)  # the control: the build as written passes
    _tamper(out, "https://www.ticketmaster.com/event/F1", "https://tickets.example.org/event/F1")
    with pytest.raises(validate_ics.FeedError, match="not an https address on a listed host") as refused:
        validate_ics.validate_dist(out)
    assert "example.org" not in str(refused.value), "the message names the event, not the address"
    # http on a listed host is refused the same way.
    _tamper(out, "https://tickets.example.org/event/F1", "http://www.ticketmaster.com/event/F1")
    with pytest.raises(validate_ics.FeedError, match="not an https address on a listed host"):
        validate_ics.validate_dist(out)
