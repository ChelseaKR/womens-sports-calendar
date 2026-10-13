"""Affiliate links (DECISIONS 0018): the SeatGeek buy links and the Fanatics
team-shop link, each driven by one Impact tracking link in sellers.py.

- With neither link set, the site is exactly what it was: no label, no rel,
  no shop link, no extra CSS, and the plain-link disclosure.
- With them set, exactly the intended links change: buy links that already
  go to SeatGeek, and the shop link on team pages with a confirmed Fanatics
  store. Each such link carries rel="sponsored noopener" and is followed by
  a visible "Paid link" label, and no other link carries either.
- The .ics feeds never change.

Each checker below has a negative control that sabotages the build, asserts
the sabotage really landed, and asserts the checker then fails.
"""

from __future__ import annotations

import json
import re
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import pytest

from wsc_pipeline import sellers, site, team_shops
from wsc_pipeline.config import LEAGUES
from wsc_pipeline.normalize import normalize_event
from wsc_pipeline.site import render_team
from wsc_pipeline.site_data import team_data

from .conftest import (
    COMMITTED_AFFILIATE_LINK_TEMPLATES,
    COMMITTED_FANATICS_IMPACT_LINK,
    COMMITTED_FANATICS_TEMPLATE,
    COMMITTED_SEATGEEK_IMPACT_LINK,
    make_raw_event,
    set_affiliate_links,
)
from .fixture_site import build_fixture_site

# Shaped like real Impact tracking links; the ids are made up.
SEATGEEK_LINK = "https://seatgeek.pxf.io/c/1234567/890123/45678"
FANATICS_LINK = "https://fanatics.93n6tx.net/c/1234567/612734/9663"
TRACKING_PREFIXES = (SEATGEEK_LINK + "?", FANATICS_LINK + "?")

NWSL = next(lg for lg in LEAGUES if lg.slug == "nwsl")
THORNS = next(t for t in NWSL.teams if t.slug == "portland-thorns")
BAY = next(t for t in NWSL.teams if t.slug == "bay-fc")
WNBA = next(lg for lg in LEAGUES if lg.slug == "wnba")
ACES = next(t for t in WNBA.teams if t.slug == "las-vegas-aces")

THORNS_SEATGEEK = sellers.PRIMARY_SELLERS[("nwsl", "portland-thorns")].team_page_url
# Strings that exist only because an affiliate link is on the page.
AFFILIATE_MARKERS = ("Paid link", "paid-link", "sponsored", "Team shop", "fanatics", "pxf.io", "93n6tx", "Impact")


# ---- parsing a page ----------------------------------------------------------


class _Links(HTMLParser):
    """Every <a> on a page with its text, and whether the next element after
    it (whitespace aside) is the "Paid link" label."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, object]] = []
        self.labels = 0
        self._open: dict[str, object] | None = None
        self._last_closed: dict[str, object] | None = None
        self._in_label = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "span" and attributes.get("class") == "paid-link":
            self._in_label = True
            self.labels += 1
            if self._last_closed is not None:
                self._last_closed["labelled"] = True
            self._last_closed = None
            return
        self._last_closed = None
        if tag == "a":
            self._open = {"attrs": attributes, "text": "", "labelled": False}

    def handle_data(self, data: str) -> None:
        if self._open is not None:
            self._open["text"] = str(self._open["text"]) + data
        elif self._in_label:
            assert data == site.PAID_LINK_TEXT, data
        elif data.strip():
            self._last_closed = None

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._in_label:
            self._in_label = False
        if tag == "a" and self._open is not None:
            self.links.append(self._open)
            self._last_closed, self._open = self._open, None
        elif tag != "a":
            self._last_closed = None


def _links(html: str) -> _Links:
    parser = _Links()
    parser.feed(html)
    return parser


def _href(link: dict[str, object]) -> str:
    attrs = link["attrs"]
    assert isinstance(attrs, dict)
    return str(attrs.get("href") or "")


def _destination(href: str) -> str:
    """Where a tracking link forwards to (Impact's `u` parameter)."""
    values = parse_qs(urlparse(href).query)["u"]
    assert len(values) == 1
    return values[0]


def assert_affiliate_links_are_exactly_the_intended_ones(html: str) -> int:
    """Every link through a tracking link goes to a SeatGeek team page that
    PRIMARY_SELLERS names, or to a Fanatics store team_shops.py names; carries
    rel="sponsored noopener"; and is followed by the label. No other link has
    a rel of sponsored or a label. Returns how many affiliate links it saw."""
    parsed = _links(html)
    seatgeek_pages = {s.team_page_url for s in sellers.PRIMARY_SELLERS.values() if s.name == sellers.SEATGEEK}
    shops = set(team_shops.FANATICS_TEAM_SHOPS.values())
    affiliate = 0
    for link in parsed.links:
        href = _href(link)
        attrs = link["attrs"]
        assert isinstance(attrs, dict)
        if href.startswith(TRACKING_PREFIXES):
            affiliate += 1
            destination = _destination(href)
            if href.startswith(SEATGEEK_LINK):
                assert destination in seatgeek_pages, f"a SeatGeek tracking link goes to {destination}"
                # The link text names the seller, not the tracking host.
                assert " from SeatGeek, the official seller for " in str(link["text"]), link["text"]
            else:
                assert destination in shops, f"a Fanatics tracking link goes to {destination}"
            assert attrs.get("rel") == "sponsored noopener", f"affiliate link without rel: {href}"
            assert link["labelled"], f"affiliate link without its Paid link label: {href}"
        else:
            assert "sponsored" not in str(attrs.get("rel") or ""), f"plain link marked sponsored: {href}"
            assert not link["labelled"], f"plain link carries a Paid link label: {href}"
            assert urlparse(href).hostname not in {"seatgeek.pxf.io", "fanatics.93n6tx.net"}, href
    assert parsed.labels == affiliate, f"{parsed.labels} labels for {affiliate} affiliate links"
    return affiliate


def assert_no_affiliate_trace(name: str, text: str) -> None:
    for marker in AFFILIATE_MARKERS:
        assert marker not in text, f"{name} contains {marker!r} with no affiliate link configured"


# ---- the settings ------------------------------------------------------------


def test_impact_template_accepts_only_a_bare_tracking_link():
    assert sellers.impact_template("", setting="X") is None
    assert sellers.impact_template(SEATGEEK_LINK, setting="X") == SEATGEEK_LINK + "?u={url}"
    for bad in (
        "http://seatgeek.pxf.io/c/1/2/3",  # not https
        SEATGEEK_LINK + "/",  # trailing path
        SEATGEEK_LINK + "?subId1=abc",  # a sub-id could carry something per reader
        SEATGEEK_LINK + "#x",
        "https://seatgeek.pxf.io/c/1/2",  # missing the program id
        "https://seatgeek.pxf.io/c/1/2/{url}",
        "https://seatgeek.com/portland-thorns-fc-tickets",  # a destination, not a tracking link
        " " + SEATGEEK_LINK,
    ):
        with pytest.raises(ValueError, match="X must be an Impact tracking link"):
            sellers.impact_template(bad, setting="X")


def test_the_seatgeek_setting_only_ever_creates_a_seatgeek_template(monkeypatch):
    monkeypatch.setattr(sellers, "SEATGEEK_IMPACT_LINK", "")
    assert sellers._affiliate_templates() == {}
    monkeypatch.setattr(sellers, "SEATGEEK_IMPACT_LINK", SEATGEEK_LINK)
    assert sellers._affiliate_templates() == {"SeatGeek": SEATGEEK_LINK + "?u={url}"}
    monkeypatch.setattr(sellers, "SEATGEEK_IMPACT_LINK", "https://seatgeek.com/x")
    with pytest.raises(ValueError, match=re.escape("sellers.SEATGEEK_IMPACT_LINK")):
        sellers._affiliate_templates()


def test_the_committed_settings_are_valid_and_consistent(monkeypatch):
    """Whatever is committed parses (import would have failed otherwise),
    and what sellers.py derived from it matches it."""
    set_affiliate_links(monkeypatch, seatgeek=COMMITTED_SEATGEEK_IMPACT_LINK, fanatics=COMMITTED_FANATICS_IMPACT_LINK)
    assert sellers.AFFILIATE_LINK_TEMPLATES == COMMITTED_AFFILIATE_LINK_TEMPLATES
    assert set(COMMITTED_AFFILIATE_LINK_TEMPLATES) <= {sellers.SEATGEEK}
    assert sellers.FANATICS_TEMPLATE == COMMITTED_FANATICS_TEMPLATE


def test_privacy_date_moves_when_paid_links_go_live():
    """The PR that sets a link changes /privacy/, so its date must move too."""
    if COMMITTED_SEATGEEK_IMPACT_LINK or COMMITTED_FANATICS_IMPACT_LINK:
        assert date(2026, 10, 13) <= site.PRIVACY_UPDATED


def test_only_seatgeek_team_pages_can_carry_the_seatgeek_template():
    """The template is keyed by seller name. Every seller of that name is the
    official seller on seatgeek.com, and no Ticketmaster-event label can
    take that name, so a resale or Ticketmaster link never gets it."""
    named = [s for s in sellers.PRIMARY_SELLERS.values() if s.name == sellers.SEATGEEK]
    assert len(named) == 3
    for seller in named:
        assert urlparse(seller.team_page_url).hostname == sellers.SEATGEEK_HOST
    assert sellers.SEATGEEK not in sellers._HOST_LABELS.values()
    assert sellers.seller_label_for_url("https://seatgeek.com/some-event") == "seatgeek.com"


# ---- SeatGeek buy links ------------------------------------------------------


def _thorns_game(name: str, event_id: str, url: str):
    raw = make_raw_event(event_id=event_id, name=name, url=url, venue_name="Providence Park", venue_city="Portland")
    return normalize_event(raw, league_slug="nwsl", tracked_team_slug=THORNS.slug, tracked_team_name=THORNS.name)


def _thorns_page() -> str:
    home = _thorns_game("Portland Thorns FC vs Seattle Reign FC", "T1", "https://www.ticketmaster.com/event/T1")
    away = normalize_event(
        make_raw_event(
            event_id="T2",
            name="Angel City FC vs Portland Thorns FC",
            date_time="2026-06-20T23:00:00Z",
            local_date="2026-06-20",
            url="https://www.ticketmaster.com/event/T2",
        ),
        league_slug="nwsl",
        tracked_team_slug=THORNS.slug,
        tracked_team_name=THORNS.name,
    )
    return render_team(team=team_data(THORNS, NWSL, [home, away]), base_url="https://nexthomegame.com")


def test_seatgeek_links_get_the_tracking_link_rel_and_label(monkeypatch):
    set_affiliate_links(monkeypatch, seatgeek=SEATGEEK_LINK)
    html = _thorns_page()
    expected = f"{SEATGEEK_LINK}?u={quote(THORNS_SEATGEEK, safe='')}"
    assert expected == SEATGEEK_LINK + "?u=https%3A%2F%2Fseatgeek.com%2Fportland-thorns-fc-tickets"
    parsed = _links(html)
    tracked = [link for link in parsed.links if _href(link) == expected]
    assert len(tracked) == 2  # the hero and the home row
    # The away game (sold by Angel City's seller) keeps its plain Ticketmaster link.
    assert any(_href(link) == "https://www.ticketmaster.com/event/T2" for link in parsed.links)
    assert assert_affiliate_links_are_exactly_the_intended_ones(html) == 2
    # The label sits right after the link, in the hero and in the table.
    assert 'rel="sponsored noopener">Buy tickets for' in html
    assert html.count(f"home games</a> {site.PAID_LINK_LABEL}") == 2
    assert site.AFFILIATE_NOTE_ACTIVE in html


def test_the_seller_a_game_links_to_never_changes(monkeypatch):
    """Same seller, same destination, with or without the id: only the
    wrapping differs, and only for SeatGeek."""
    games = [
        _thorns_game("Portland Thorns FC vs Seattle Reign FC", "T1", "https://www.ticketmaster.com/event/T1"),
        _thorns_game("Angel City FC vs Portland Thorns FC", "T2", "https://www.ticketmaster.com/event/T2"),
        normalize_event(
            make_raw_event(event_id="A1", name="Las Vegas Aces vs Seattle Storm"),
            league_slug="wnba",
            tracked_team_slug=ACES.slug,
            tracked_team_name=ACES.name,
        ),
    ]
    set_affiliate_links(monkeypatch)
    plain = [sellers.buy_link(g) for g in games]
    set_affiliate_links(monkeypatch, seatgeek=SEATGEEK_LINK)
    paid = [sellers.buy_link(g) for g in games]
    for before, after in zip(plain, paid, strict=True):
        assert before is not None and after is not None
        assert before["seller"] == after["seller"] and before["home_team"] == after["home_team"]
        if before["seller"] == "SeatGeek":
            assert _destination(after["url"]) == before["url"]
        else:
            assert after == before
    assert [b["seller"] for b in paid if b] == ["SeatGeek", "Ticketmaster", "AXS"]


def test_axs_and_ticketmaster_pages_are_untouched_by_the_seatgeek_link(monkeypatch):
    set_affiliate_links(monkeypatch)
    game = normalize_event(
        make_raw_event(event_id="A1", name="Las Vegas Aces vs Seattle Storm"),
        league_slug="wnba",
        tracked_team_slug=ACES.slug,
        tracked_team_name=ACES.name,
    )
    before = render_team(team=team_data(ACES, WNBA, [game]), base_url="https://nexthomegame.com")
    set_affiliate_links(monkeypatch, seatgeek=SEATGEEK_LINK)
    after = render_team(team=team_data(ACES, WNBA, [game]), base_url="https://nexthomegame.com")
    # Only the disclosure and the label's CSS can change on a page with no
    # SeatGeek link; the links themselves do not.
    assert before.replace(site.AFFILIATE_NOTE_INACTIVE, site.AFFILIATE_NOTE_ACTIVE) == after
    assert assert_affiliate_links_are_exactly_the_intended_ones(after) == 0


# ---- the Fanatics shop link --------------------------------------------------


def test_every_team_shop_is_a_tracked_team_on_fanatics():
    tracked = {(lg.slug, t.slug) for lg in LEAGUES for t in lg.teams}
    assert len(team_shops.FANATICS_TEAM_SHOPS) == 25
    for key, url in team_shops.FANATICS_TEAM_SHOPS.items():
        assert key in tracked, key
        parsed = urlparse(url)
        assert (parsed.scheme, parsed.hostname, parsed.query) == ("https", "www.fanatics.com", ""), url
        assert parsed.path.startswith(f"/{key[0]}/"), url
    leagues = {league for league, _team in team_shops.FANATICS_TEAM_SHOPS}
    assert leagues == {"wnba", "nwsl"}


@pytest.mark.parametrize(
    "bad",
    [
        "http://www.fanatics.com/nwsl/x/o-1",
        "https://fanatics.example/nwsl/x/o-1",
        "https://www.fanatics.com/wnba/x/o-1",
        "https://www.fanatics.com/nwsl/x/o-1?_s=aff",
    ],
)
def test_check_team_shops_rejects_a_bad_entry(monkeypatch, bad):
    monkeypatch.setitem(team_shops.FANATICS_TEAM_SHOPS, ("nwsl", "bay-fc"), bad)
    with pytest.raises(ValueError, match="nwsl/bay-fc"):
        team_shops.check_team_shops()


def test_shop_link_only_with_an_id_and_a_confirmed_store(monkeypatch):
    set_affiliate_links(monkeypatch)
    assert team_shops.team_shop_url("nwsl", "portland-thorns") is None
    set_affiliate_links(monkeypatch, fanatics=FANATICS_LINK)
    url = team_shops.team_shop_url("nwsl", "portland-thorns")
    assert url is not None
    assert _destination(url) == team_shops.FANATICS_TEAM_SHOPS[("nwsl", "portland-thorns")]
    assert url.startswith(FANATICS_LINK + "?u=https%3A%2F%2Fwww.fanatics.com%2Fnwsl%2Fportland-thorns-fc%2F")
    assert team_shops.team_shop_url("nwsl", "bay-fc") is None
    assert team_shops.team_shop_url("pwhl", "minnesota-frost") is None


def test_team_page_shop_link_has_rel_and_label(monkeypatch):
    set_affiliate_links(monkeypatch, fanatics=FANATICS_LINK)
    html = _thorns_page()
    assert '<h2 id="team-shop-heading">Team shop</h2>' in html
    assert f"Shop Portland Thorns gear at Fanatics</a> {site.PAID_LINK_LABEL}" in html
    # Only the shop link is paid: the SeatGeek buy links stay plain.
    assert assert_affiliate_links_are_exactly_the_intended_ones(html) == 1
    assert f'href="{THORNS_SEATGEEK}"' in html
    # A team with no confirmed store gets no shop section at all.
    bay = render_team(team=team_data(BAY, NWSL, []), base_url="https://nexthomegame.com")
    assert "Team shop" not in bay and "fanatics" not in bay
    assert site.AFFILIATE_NOTE_ACTIVE in bay  # the site-wide disclosure still says some links are paid


# ---- disclosure --------------------------------------------------------------


def test_disclosure_follows_the_settings(monkeypatch):
    set_affiliate_links(monkeypatch)
    privacy = site.render_privacy(base_url="https://nexthomegame.com")
    assert site.AFFILIATE_NOTE_INACTIVE in privacy and "Paid links" not in privacy
    assert "is a plain address" in privacy and "no advertising, and no form" in privacy

    set_affiliate_links(monkeypatch, fanatics=FANATICS_LINK)
    privacy = site.render_privacy(base_url="https://nexthomegame.com")
    assert site.AFFILIATE_NOTE_ACTIVE in privacy and "<h2>Paid links</h2>" in privacy
    # Ticket links are still plain when only the shop link is paid.
    assert "is a plain address" in privacy
    assert "no advertising other than the paid links marked above" in privacy

    set_affiliate_links(monkeypatch, seatgeek=SEATGEEK_LINK)
    privacy = site.render_privacy(base_url="https://nexthomegame.com")
    assert "is a plain address" not in privacy
    assert "first passes through the seller's\naffiliate network, Impact" in privacy
    assert site.AFFILIATE_NOTE_ACTIVE in site._footer(analytics_on=True)


def test_style_css_gains_the_label_rule_only_with_an_affiliate_link(monkeypatch):
    set_affiliate_links(monkeypatch)
    assert site.style_css() == site.STYLE_CSS
    assert ".paid-link" not in site.STYLE_CSS
    set_affiliate_links(monkeypatch, seatgeek=SEATGEEK_LINK)
    assert site.style_css() == site.STYLE_CSS + site.PAID_LINK_CSS


# ---- whole-site builds -------------------------------------------------------


def _files(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _feeds(files: dict[str, bytes]) -> dict[str, bytes]:
    """The .ics feeds with each event's DTSTAMP (the build's fetch time)
    blanked, so two builds compare byte for byte."""
    fetched = json.loads(files["data/site.json"])["fetched_at"]
    stamp = b"DTSTAMP:" + fetched.replace("-", "").replace(":", "")[:15].encode() + b"Z\r\n"
    out = {}
    for name, data in files.items():
        if name.endswith(".ics"):
            assert stamp in data or b"BEGIN:VEVENT" not in data, name
            out[name] = data.replace(stamp, b"DTSTAMP:<build>\r\n")
    return out


def test_whole_site_with_no_ids_carries_no_affiliate_trace(tmp_path):
    build_fixture_site(tmp_path / "site")
    files = _files(tmp_path / "site")
    assert files["style.css"] == site.STYLE_CSS.encode()
    for name, data in files.items():
        if name.endswith((".html", ".css", ".json", ".ics", ".xml", ".txt")):
            assert_no_affiliate_trace(name, data.decode())
    # The fixture really has a SeatGeek game, so "no trace" compared a real link.
    thorns = files["nwsl/portland-thorns/index.html"].decode()
    assert f'href="{THORNS_SEATGEEK}"' in thorns


def test_whole_site_with_ids_marks_exactly_the_intended_links(tmp_path, monkeypatch):
    set_affiliate_links(monkeypatch)
    build_fixture_site(tmp_path / "plain")
    set_affiliate_links(monkeypatch, seatgeek=SEATGEEK_LINK, fanatics=FANATICS_LINK)
    build_fixture_site(tmp_path / "paid")
    plain, paid = _files(tmp_path / "plain"), _files(tmp_path / "paid")
    assert plain.keys() == paid.keys()

    # The feeds never change.
    assert _feeds(plain) == _feeds(paid)
    assert len(_feeds(paid)) > 50
    for name, data in _feeds(paid).items():
        assert_no_affiliate_trace(name, data.decode())

    counts = {
        name: assert_affiliate_links_are_exactly_the_intended_ones(data.decode())
        for name, data in paid.items()
        if name.endswith(".html")
    }
    # The Thorns home game: the team page's hero and row plus its shop link,
    # its row on the NWSL page and on the daily schedule page.
    assert counts["nwsl/portland-thorns/index.html"] == 3
    assert counts["nwsl/index.html"] == 1
    # Aces (AXS) and Sceptres (PWHL, no store): only the Aces shop link.
    assert counts["wnba/las-vegas-aces/index.html"] == 1
    assert counts["pwhl/toronto-sceptres/index.html"] == 0
    assert counts["index.html"] == 0 and counts["privacy/index.html"] == 0
    # Every page with a Fanatics store gets exactly one shop link.
    for league, team in team_shops.FANATICS_TEAM_SHOPS:
        assert paid[f"{league}/{team}/index.html"].decode().count("Team shop</h2>") == 1


# ---- negative controls -------------------------------------------------------


def test_negative_control_a_missing_label_is_caught(monkeypatch):
    set_affiliate_links(monkeypatch, seatgeek=SEATGEEK_LINK)
    monkeypatch.setattr(site, "PAID_LINK_LABEL", "")
    html = _thorns_page()
    # The sabotage landed: the links are still rewritten, the label is gone.
    assert html.count(f'href="{SEATGEEK_LINK}?u=') == 2
    assert "Paid link" not in html.replace(site.AFFILIATE_NOTE_ACTIVE, "")
    with pytest.raises(AssertionError, match="without its Paid link label"):
        assert_affiliate_links_are_exactly_the_intended_ones(html)


def test_negative_control_a_template_on_a_non_seatgeek_seller_is_caught(monkeypatch):
    set_affiliate_links(monkeypatch, seatgeek=SEATGEEK_LINK)
    monkeypatch.setitem(sellers.AFFILIATE_LINK_TEMPLATES, "AXS", SEATGEEK_LINK + "?u={url}")
    game = normalize_event(
        make_raw_event(event_id="A1", name="Las Vegas Aces vs Seattle Storm"),
        league_slug="wnba",
        tracked_team_slug=ACES.slug,
        tracked_team_name=ACES.name,
    )
    html = render_team(team=team_data(ACES, WNBA, [game]), base_url="https://nexthomegame.com")
    # The sabotage landed: an AXS page now goes through the tracking link.
    assert f'href="{SEATGEEK_LINK}?u=https%3A%2F%2Fwww.axs.com' in html
    with pytest.raises(AssertionError, match=re.escape("a SeatGeek tracking link goes to https://www.axs.com")):
        assert_affiliate_links_are_exactly_the_intended_ones(html)


def test_negative_control_a_sponsored_plain_link_is_caught(monkeypatch):
    set_affiliate_links(monkeypatch)
    html = _thorns_page().replace(f'href="{THORNS_SEATGEEK}"', f'href="{THORNS_SEATGEEK}" rel="sponsored noopener"', 1)
    assert 'rel="sponsored noopener"' in html  # the sabotage landed
    with pytest.raises(AssertionError, match="plain link marked sponsored"):
        assert_affiliate_links_are_exactly_the_intended_ones(html)


def test_negative_control_a_trace_with_no_ids_is_caught(monkeypatch):
    set_affiliate_links(monkeypatch)
    monkeypatch.setattr(sellers, "FANATICS_TEMPLATE", FANATICS_LINK + "?u={url}")
    html = _thorns_page()
    assert "Team shop" in html  # the sabotage landed: a shop link with "no id"
    with pytest.raises(AssertionError, match="with no affiliate link configured"):
        assert_no_affiliate_trace("thorns", html)
