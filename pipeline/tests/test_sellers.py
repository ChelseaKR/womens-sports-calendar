"""sellers.py: where each "Buy tickets" link goes, and the single affiliate
config point (DECISIONS 0013)."""

from __future__ import annotations

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
