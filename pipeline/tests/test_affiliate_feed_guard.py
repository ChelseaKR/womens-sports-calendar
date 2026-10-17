"""Ticketmaster event URLs that arrive already wrapped in Impact affiliate
tracking (docs/LICENSES-AND-ATTRIBUTION.md §3, DECISIONS 0018).

Ticketmaster wraps the Discovery API's `event.url` in Impact tracking itself,
server-side, once an Impact publisher id is on the developer account. Nothing
in this repository turns that on, so these tests feed the build wrapped URLs
directly:

- No .ics feed ever carries a tracking link: each one carries the decoded
  destination, byte for byte what it would carry for the plain URL, or no
  link at all when there is no plain destination. data/*.json's `ticket_url`
  is the same plain address.
- On the pages a wrapped link is a paid link: rel="sponsored noopener", the
  "Paid link" label, named by its destination (Ticketmaster), and the footer,
  privacy page and style.css disclose it.

Each checker has a negative control that sabotages the build, asserts the
sabotage landed, and asserts the checker then fails.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from urllib.parse import quote

import pytest

from wsc_pipeline import ics, impact, sellers, site, validate_ics
from wsc_pipeline.config import LEAGUES
from wsc_pipeline.normalize import feed_ticket_url, normalize_event
from wsc_pipeline.site import render_team
from wsc_pipeline.site_data import game_to_dict, team_data

from . import fixture_site
from .conftest import BUILD_TIME, make_raw_event
from .fixture_site import build_fixture_site
from .test_affiliate_links import _feeds, _files, _links

TM_EVENT = "https://www.ticketmaster.com/event/X1"

# Tracking hosts of every kind the detector must catch: Impact's shared
# domains, and a brand's own custom domain that names no seller.
TRACKING_LINKS = (
    "https://ticketmaster.evyy.net/c/1234567/264167/4272",
    "https://tm.pxf.io/c/1234567/264167/4272",
    "https://imp.sjv.io/c/1234567/264167/4272",
    "https://go.brandclicks.example/c/1234567/264167/4272",
)

WNBA = next(lg for lg in LEAGUES if lg.slug == "wnba")
ACES = next(t for t in WNBA.teams if t.slug == "las-vegas-aces")


def wrap(url: str, tracking: str = TRACKING_LINKS[0]) -> str:
    return f"{tracking}?u={quote(url, safe='')}"


def _away_game(url: str):
    """An Aces away game: its buy link is the Ticketmaster event URL."""
    raw = make_raw_event(event_id="X1", name="Seattle Storm vs Las Vegas Aces", url=url)
    game = normalize_event(raw, league_slug="wnba", tracked_team_slug=ACES.slug, tracked_team_name=ACES.name)
    assert game is not None
    return game


# ---- recognising a tracking link ---------------------------------------------


@pytest.mark.parametrize("tracking", TRACKING_LINKS)
def test_a_tracking_link_is_recognised_by_its_path_on_any_host(tracking):
    assert impact.is_impact_link(wrap(TM_EVENT, tracking))
    assert impact.is_impact_link(tracking)  # no destination: still a tracking link
    assert impact.plain_url(wrap(TM_EVENT, tracking)) == TM_EVENT


@pytest.mark.parametrize(
    "url",
    [
        "https://seatgeek.pxf.io/AbC12",  # an Impact short link: no path, no `u`
        "https://ticketmaster.evyy.net/anything?u=https%3A%2F%2Fwww.ticketmaster.com%2F",
        "https://PXF.IO/c/1/2/3",
    ],
)
def test_any_address_on_an_impact_shared_domain_is_a_tracking_link(url):
    assert impact.is_impact_link(url)


@pytest.mark.parametrize(
    "url",
    [
        TM_EVENT,
        "https://www.ticketmaster.com/c/abc/event",
        "https://www.ticketmaster.com/c/1/2",
        "https://seatgeek.com/portland-thorns-fc-tickets",
        "https://notpxf.io/x",
        "https://pxf.io.example.com/x",
        "http://[unbalanced",
        "",
        None,
    ],
)
def test_ordinary_links_are_not_tracking_links(url):
    assert not impact.is_impact_link(url)


def test_plain_url_unwraps_nested_links_and_never_guesses():
    assert impact.plain_url(TM_EVENT) == TM_EVENT
    twice = wrap(wrap(TM_EVENT, TRACKING_LINKS[1]), TRACKING_LINKS[3])
    assert impact.plain_url(twice) == TM_EVENT
    too_deep = TM_EVENT
    for _ in range(impact.MAX_HOPS + 1):
        too_deep = wrap(too_deep)
    assert impact.plain_url(too_deep) is None
    for no_destination in (
        TRACKING_LINKS[0],  # no `u`
        "https://seatgeek.pxf.io/AbC12",  # a short link
        TRACKING_LINKS[0] + "?u=",  # an empty `u`
        TRACKING_LINKS[0] + "?u=a&u=b",  # two of them
        wrap("javascript:alert(1)"),  # not a web address
        wrap("https:///no-host"),
        wrap("http://[unbalanced"),
    ):
        assert impact.plain_url(no_destination) is None, no_destination


# ---- the feeds ---------------------------------------------------------------


def _event_lines(game) -> tuple[str | None, list[str]]:
    cal = ics.build_calendar([game], cal_name="t", dtstamp=BUILD_TIME)
    (vevent,) = cal.walk("VEVENT")
    url = vevent.get("url")
    return (str(url) if url is not None else None), str(vevent.get("description")).split("\n")


@pytest.mark.parametrize("tracking", TRACKING_LINKS)
def test_a_feed_carries_the_destination_not_the_tracking_link(tracking):
    wrapped = _away_game(wrap(TM_EVENT, tracking))
    assert wrapped.ticket_url != TM_EVENT  # the game itself keeps what Ticketmaster sent
    assert feed_ticket_url(wrapped) == TM_EVENT
    plain = ics.build_calendar([_away_game(TM_EVENT)], cal_name="t", dtstamp=BUILD_TIME).to_ical()
    assert ics.build_calendar([wrapped], cal_name="t", dtstamp=BUILD_TIME).to_ical() == plain
    assert game_to_dict(wrapped)["ticket_url"] == TM_EVENT


def test_a_tracking_link_with_no_destination_leaves_the_link_out():
    url, lines = _event_lines(_away_game("https://ticketmaster.pxf.io/AbC12"))
    assert url is None
    assert not any(line.startswith("Buy:") for line in lines)
    assert "pxf.io" not in "\n".join(lines)
    assert game_to_dict(_away_game("https://ticketmaster.pxf.io/AbC12"))["ticket_url"] is None


def assert_no_tracking_link_in_feeds(files: dict[str, bytes]) -> int:
    """Every address in every .ics file (folded lines joined) is not an
    Impact tracking link, and no Impact shared domain appears at all.
    Returns how many addresses it checked."""
    checked = 0
    for name, data in files.items():
        if not name.endswith(".ics"):
            continue
        text = data.decode().replace("\r\n ", "")
        for domain in impact.IMPACT_SHARED_DOMAINS:
            assert domain not in text, f"{name} mentions the Impact domain {domain}"
        for url in re.findall(r"[a-z][a-z0-9+.-]*://[^\s\\]+", text, flags=re.IGNORECASE):
            checked += 1
            assert not impact.is_impact_link(url), f"{name} carries the affiliate tracking link {url}"
    return checked


def _wrapped_fixture_events() -> dict[str, list[dict]]:
    """The fixture site's listings with every event URL wrapped, cycling
    through the kinds of tracking host."""
    wrapped = copy.deepcopy(fixture_site.RAW_EVENTS_BY_TEAM)
    n = 0
    for events in wrapped.values():
        for raw in events:
            raw["url"] = wrap(raw["url"], TRACKING_LINKS[n % len(TRACKING_LINKS)])
            n += 1
    return wrapped


def test_no_generated_feed_carries_a_tracking_link_when_ticketmaster_wraps_every_url(tmp_path: Path, monkeypatch):
    build_fixture_site(tmp_path / "plain")
    monkeypatch.setattr(fixture_site, "RAW_EVENTS_BY_TEAM", _wrapped_fixture_events())
    build_fixture_site(tmp_path / "wrapped")
    plain, wrapped = _files(tmp_path / "plain"), _files(tmp_path / "wrapped")

    # The build really was fed tracking links: the pages' buy links carry them.
    aces = json.loads(wrapped["data/wnba/las-vegas-aces.json"])
    assert any(impact.is_impact_link((g["buy"] or {}).get("url")) for g in aces["games"])

    assert assert_no_tracking_link_in_feeds(wrapped) > 50
    # Every feed is what the plain URLs would have produced, byte for byte.
    assert _feeds(wrapped) == _feeds(plain)
    # data/*.json's ticket_url is the plain address too.
    for name in plain:
        if name.startswith("data/") and name != "data/site.json":
            plain_games = json.loads(plain[name]).get("games", [])
            wrapped_games = json.loads(wrapped[name]).get("games", [])
            assert [g["ticket_url"] for g in wrapped_games] == [g["ticket_url"] for g in plain_games], name
    # And the real feed validator, the one pages.yml runs, passes.
    validate_ics.validate_dist(tmp_path / "wrapped")


def test_negative_control_a_feed_that_keeps_the_tracking_link_is_caught(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(fixture_site, "RAW_EVENTS_BY_TEAM", _wrapped_fixture_events())
    monkeypatch.setattr(ics, "feed_ticket_url", lambda game: game.ticket_url)
    build_fixture_site(tmp_path / "site")
    files = _files(tmp_path / "site")
    assert b"evyy.net" in files["ics/wnba.ics"]  # the sabotage landed
    with pytest.raises(AssertionError, match="mentions the Impact domain"):
        assert_no_tracking_link_in_feeds(files)
    # A custom tracking host is caught by its path, folded line or not.
    custom = wrap(TM_EVENT, TRACKING_LINKS[3]).encode()
    folded = {"x.ics": b"BEGIN:VEVENT\r\nURL:" + custom[:40] + b"\r\n " + custom[40:] + b"\r\nEND:VEVENT\r\n"}
    with pytest.raises(AssertionError, match=re.escape("carries the affiliate tracking link https://go.brandclicks")):
        assert_no_tracking_link_in_feeds(folded)
    with pytest.raises(validate_ics.FeedError, match="carries an affiliate tracking link"):
        validate_ics.validate_dist(tmp_path / "site")


# ---- the pages ---------------------------------------------------------------


def test_a_wrapped_ticketmaster_link_is_labelled_by_its_destination_and_marked_paid(monkeypatch):
    game = _away_game(wrap(TM_EVENT, TRACKING_LINKS[3]))
    buy = sellers.buy_link(game)
    assert buy == {"url": wrap(TM_EVENT, TRACKING_LINKS[3]), "seller": "Ticketmaster", "home_team": ""}
    assert sellers.is_affiliate_link(buy["seller"], buy["url"])
    assert not sellers.is_affiliate_link("Ticketmaster", TM_EVENT)
    assert sellers.any_paid_buy_link([game]) and not sellers.any_paid_buy_link([_away_game(TM_EVENT)])
    # A template never wraps a link twice.
    monkeypatch.setitem(sellers.AFFILIATE_LINK_TEMPLATES, "Ticketmaster", "https://seatgeek.pxf.io/c/1/2/3?u={url}")
    assert sellers.with_affiliate(buy["url"], "Ticketmaster") == buy["url"]
    assert sellers.with_affiliate(TM_EVENT, "Ticketmaster") == wrap(TM_EVENT, "https://seatgeek.pxf.io/c/1/2/3")


def test_a_team_page_marks_the_wrapped_link_paid():
    html = render_team(
        team=team_data(ACES, WNBA, [_away_game(wrap(TM_EVENT))]), base_url="https://nexthomegame.com", paid_links=True
    )
    paid = [link for link in _links(html).links if impact.is_impact_link(str(link["attrs"]["href"]))]
    assert len(paid) == 2  # the next-game hero and the table row
    for link in paid:
        assert link["attrs"]["rel"] == "sponsored noopener" and link["labelled"]
        assert str(link["text"]).endswith(" from Ticketmaster") and "evyy" not in str(link["text"])
    assert site.AFFILIATE_NOTE_ACTIVE in html


def test_the_disclosure_follows_what_the_build_found():
    assert site.style_css() == site.STYLE_CSS
    assert site.style_css(paid_links=True) == site.STYLE_CSS + site.PAID_LINK_CSS
    assert site.AFFILIATE_NOTE_INACTIVE in site._footer(analytics_on=True)
    assert site.AFFILIATE_NOTE_ACTIVE in site._footer(analytics_on=True, paid_links=True)
    privacy = site.render_privacy(base_url="https://nexthomegame.com", paid_links=True)
    assert "<h2>Paid links</h2>" in privacy and "is a plain address" not in privacy
    assert "Google Analytics records a click on a paid link" not in privacy  # no GA id here
    with_ga = site.render_privacy(base_url="https://nexthomegame.com", ga4_id="G-TEST12345", paid_links=True)
    assert "Google Analytics records a click on a paid link" in with_ga


def test_a_whole_site_with_wrapped_urls_labels_them_and_discloses_it(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(fixture_site, "RAW_EVENTS_BY_TEAM", _wrapped_fixture_events())
    build_fixture_site(tmp_path / "site")
    files = _files(tmp_path / "site")
    assert files["style.css"] == (site.STYLE_CSS + site.PAID_LINK_CSS).encode()
    for name, data in files.items():
        if not name.endswith(".html"):
            continue
        html = data.decode()
        assert site.AFFILIATE_NOTE_ACTIVE in html, name
        for link in _links(html).links:
            href = str(link["attrs"].get("href") or "")
            if impact.is_impact_link(href):
                assert link["attrs"].get("rel") == "sponsored noopener", (name, href)
                assert link["labelled"], (name, href)
                assert "Buy tickets for " in str(link["text"]), (name, href)
    aces = files["wnba/las-vegas-aces/index.html"].decode()
    assert aces.count(site.PAID_LINK_LABEL) > 0
