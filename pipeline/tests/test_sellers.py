"""sellers.py: where each "Buy tickets" link goes, and the single affiliate
config point (DECISIONS 0013)."""

from __future__ import annotations

from html.parser import HTMLParser

import pytest

from wsc_pipeline import sellers, site
from wsc_pipeline.config import LEAGUES
from wsc_pipeline.normalize import normalize_event
from wsc_pipeline.site import render_team
from wsc_pipeline.site_data import team_data

from .conftest import make_raw_event

WNBA = next(lg for lg in LEAGUES if lg.slug == "wnba")
ACES = next(t for t in WNBA.teams if t.slug == "las-vegas-aces")


def _aces_game(name: str, url: str = "https://www.ticketmaster.com/event/X1"):
    raw = make_raw_event(event_id="X1", name=name, url=url)
    return normalize_event(raw, league_slug="wnba", tracked_team_slug=ACES.slug, tracked_team_name=ACES.name)


def test_every_primary_seller_names_a_tracked_team_and_https_page():
    tracked = {(lg.slug, t.slug) for lg in LEAGUES for t in lg.teams}
    for key, seller in sellers.PRIMARY_SELLERS.items():
        assert key in tracked, key
        assert seller.team_page_url.startswith("https://"), seller
        assert seller.evidence, key


def test_home_game_links_to_the_home_teams_primary_seller():
    buy = sellers.buy_link(_aces_game("Las Vegas Aces vs Seattle Storm"))
    assert buy == {
        "url": "https://www.axs.com/teams/1104736/las-vegas-aces-tickets",
        "seller": "AXS",
        "home_team": "Las Vegas Aces",
    }


def test_away_game_keeps_the_ticketmaster_event_link():
    """An Aces game in Seattle is sold by Seattle's seller, not AXS."""
    buy = sellers.buy_link(_aces_game("Seattle Storm vs Las Vegas Aces"))
    assert buy == {"url": "https://www.ticketmaster.com/event/X1", "seller": "Ticketmaster", "home_team": ""}


def test_seller_label_follows_the_actual_link_host():
    """Some Discovery event URLs point at gofevo.com; the link must not say
    Ticketmaster for those."""
    buy = sellers.buy_link(_aces_game("Seattle Storm vs Las Vegas Aces", url="https://www.gofevo.com/event/abc"))
    assert buy["seller"] == "FEVO"
    assert sellers.seller_label_for_url("https://tickets.example.org/x") == "tickets.example.org"


def test_no_affiliate_ids_ship_and_links_are_plain():
    assert sellers.AFFILIATE_LINK_TEMPLATES == {}
    assert sellers.affiliate_links_active() is False
    for seller in sellers.PRIMARY_SELLERS.values():
        assert sellers.with_affiliate(seller.team_page_url, seller.name) == seller.team_page_url


def test_affiliate_template_is_the_single_config_point(monkeypatch):
    monkeypatch.setitem(sellers.AFFILIATE_LINK_TEMPLATES, "AXS", "https://aff.example/c/123?u={url}")
    buy = sellers.buy_link(_aces_game("Las Vegas Aces vs Seattle Storm"))
    assert (
        buy["url"] == "https://aff.example/c/123?u=https%3A%2F%2Fwww.axs.com%2Fteams%2F1104736%2Flas-vegas-aces-tickets"
    )
    # Ticketmaster links are untouched unless Ticketmaster gets its own entry.
    assert (
        sellers.buy_link(_aces_game("Seattle Storm vs Las Vegas Aces"))["url"]
        == "https://www.ticketmaster.com/event/X1"
    )


def test_footer_and_privacy_disclosure_follow_the_affiliate_config(monkeypatch):
    for analytics_on in (False, True):
        footer = site._footer(analytics_on=analytics_on)
        assert site.AFFILIATE_NOTE_INACTIVE in footer
        assert "commission" not in footer
    privacy = site.render_privacy(base_url="https://nexthomegame.com", ga4_id="G-TEST1234")
    assert site.AFFILIATE_NOTE_INACTIVE in privacy and "commission" not in privacy
    monkeypatch.setitem(sellers.AFFILIATE_LINK_TEMPLATES, "AXS", "https://aff.example/c/123?u={url}")
    assert site.AFFILIATE_NOTE_ACTIVE in site._footer(analytics_on=True)
    assert site.AFFILIATE_NOTE_ACTIVE in site.render_privacy(base_url="https://nexthomegame.com")


def test_team_page_link_text_says_it_goes_to_the_sellers_team_page():
    game = _aces_game("Las Vegas Aces vs Seattle Storm")
    html = render_team(team=team_data(ACES, WNBA, [game]), base_url="https://nexthomegame.com")
    assert 'href="https://www.axs.com/teams/1104736/las-vegas-aces-tickets"' in html
    assert "from AXS, the official seller for Las Vegas Aces home games</a>" in html
    assert "ticketmaster.com/event/X1" not in html


def test_team_page_leads_with_the_calendar():
    html = render_team(
        team=team_data(ACES, WNBA, [_aces_game("Las Vegas Aces vs Seattle Storm")]), base_url="https://nexthomegame.com"
    )
    assert html.index('class="subscribe"') < html.index('class="next-game"') < html.index('class="games-table"')


AFFILIATE_TEMPLATE = "https://aff.example/c/123?u={url}"


class _TicketAnchors(HTMLParser):
    """Every "Buy tickets for ..." anchor on a page, as (attributes, text)."""

    def __init__(self) -> None:
        super().__init__()
        self.anchors: list[tuple[dict[str, str | None], str]] = []
        self._open: dict[str, str | None] | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._open, self._text = dict(attrs), []

    def handle_data(self, data):
        if self._open is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._open is not None:
            text = "".join(self._text)
            if text.startswith("Buy tickets for"):
                self.anchors.append((self._open, text))
            self._open = None


def _ticket_anchors(html: str) -> list[dict[str, str | None]]:
    parser = _TicketAnchors()
    parser.feed(html)
    return [attrs for attrs, _text in parser.anchors]


def _aces_page_with_a_home_and_an_away_game() -> str:
    """One Aces home game (AXS's team page: the hero and one table row) and
    one Aces away game (the Ticketmaster event link: one more table row)."""
    home = _aces_game("Las Vegas Aces vs Seattle Storm")
    away = normalize_event(
        make_raw_event(
            event_id="X2",
            name="Seattle Storm vs Las Vegas Aces",
            date_time="2026-06-20T23:00:00Z",
            local_date="2026-06-20",
            url="https://www.ticketmaster.com/event/X2",
        ),
        league_slug="wnba",
        tracked_team_slug=ACES.slug,
        tracked_team_name=ACES.name,
    )
    return render_team(team=team_data(ACES, WNBA, [home, away]), base_url="https://nexthomegame.com")


def _assert_affiliate_links_are_sponsored(html: str) -> None:
    """Every anchor that goes through the affiliate template carries
    rel="sponsored noopener", and no other ticket anchor has a rel at all.
    Raises AssertionError otherwise (the negative control below relies on it)."""
    anchors = _ticket_anchors(html)
    affiliate = [a for a in anchors if (a["href"] or "").startswith("https://aff.example/")]
    plain = [a for a in anchors if a not in affiliate]
    assert len(affiliate) == 2, f"expected the hero and one table row, found {len(affiliate)}"
    assert len(plain) == 1, f"expected one Ticketmaster row, found {len(plain)}"
    assert any(a.get("class") == "next-game-cta" for a in affiliate), "the hero link is not an affiliate link"
    for a in affiliate:
        assert a.get("rel") == "sponsored noopener", a
    for a in plain:
        assert "rel" not in a, a


def test_affiliate_links_carry_rel_sponsored_in_the_hero_and_the_table(monkeypatch):
    monkeypatch.setitem(sellers.AFFILIATE_LINK_TEMPLATES, "AXS", AFFILIATE_TEMPLATE)
    html = _aces_page_with_a_home_and_an_away_game()
    _assert_affiliate_links_are_sponsored(html)
    # The relationship stays disclosed to the reader, on the same page.
    assert site.AFFILIATE_NOTE_ACTIVE in html
    assert site.AFFILIATE_NOTE_INACTIVE not in html


def test_no_ticket_link_has_a_rel_when_no_template_is_set():
    assert sellers.AFFILIATE_LINK_TEMPLATES == {}
    html = _aces_page_with_a_home_and_an_away_game()
    anchors = _ticket_anchors(html)
    assert len(anchors) == 3  # the hero and the home row, and the away row
    for a in anchors:
        assert "rel" not in a, a
        assert set(a) <= {"class", "href"}, a
    assert "sponsored" not in html
    assert site.AFFILIATE_NOTE_INACTIVE in html


def test_only_the_seller_with_a_template_is_marked(monkeypatch):
    """A template for Ticketmaster marks the away row, not the AXS ones."""
    monkeypatch.setitem(sellers.AFFILIATE_LINK_TEMPLATES, "Ticketmaster", AFFILIATE_TEMPLATE)
    marked = {
        a["href"].startswith("https://aff.example/"): a.get("rel")
        for a in _ticket_anchors(_aces_page_with_a_home_and_an_away_game())
    }
    assert marked == {True: "sponsored noopener", False: None}


def test_is_affiliate_link_follows_the_config_and_treats_an_empty_template_as_none(monkeypatch):
    assert sellers.is_affiliate_link("AXS") is False
    monkeypatch.setitem(sellers.AFFILIATE_LINK_TEMPLATES, "AXS", AFFILIATE_TEMPLATE)
    assert sellers.is_affiliate_link("AXS") is True
    assert sellers.is_affiliate_link("SeatGeek") is False
    # with_affiliate treats an empty template as "no template"; so must this.
    monkeypatch.setitem(sellers.AFFILIATE_LINK_TEMPLATES, "AXS", "")
    assert sellers.is_affiliate_link("AXS") is False
    assert sellers.with_affiliate("https://x.example/", "AXS") == "https://x.example/"


def test_negative_control_the_rel_check_fails_when_the_marking_is_removed(monkeypatch):
    """Sabotage the render step so an affiliate link is rewritten but not
    marked, assert the sabotage landed (the anchors still point at the
    affiliate host), and assert the check rejects the page."""
    monkeypatch.setitem(sellers.AFFILIATE_LINK_TEMPLATES, "AXS", AFFILIATE_TEMPLATE)
    monkeypatch.setattr(site, "is_affiliate_link", lambda seller: False)
    html = _aces_page_with_a_home_and_an_away_game()
    anchors = _ticket_anchors(html)
    assert sum((a["href"] or "").startswith("https://aff.example/") for a in anchors) == 2
    assert not any("rel" in a for a in anchors)
    with pytest.raises(AssertionError, match="sponsored noopener"):
        _assert_affiliate_links_are_sponsored(html)
