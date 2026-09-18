from __future__ import annotations

import re

from wsc_pipeline.config import LEAGUES, LEAGUES_EXAMINED_NOT_INCLUDED
from wsc_pipeline.normalize import normalize_event
from wsc_pipeline.site import render_index, render_league, render_team
from wsc_pipeline.site_data import league_data, team_data
from .conftest import make_raw_event

LEAGUE = LEAGUES[0]  # wnba
TEAM = LEAGUE.teams[0]

SCRIPT_TAG_RE = re.compile(r"<script\b", re.IGNORECASE)


def _game(event_id, **kwargs):
    raw = make_raw_event(event_id=event_id, **kwargs)
    return normalize_event(
        raw, league_slug=LEAGUE.slug, tracked_team_slug=TEAM.slug, tracked_team_name=TEAM.name
    )


def _pages():
    priced = _game("EVT-P", price_ranges=[{"type": "standard", "currency": "USD", "min": 12.0, "max": 34.0}])
    unpriced = _game("EVT-U", price_ranges=None)
    # Same shape as conftest's event_date_tbd fixture: a placeholder local
    # date is published but no exact instant yet, so the game is excluded
    # from the .ics but must still render on the site as "Date TBD" (never
    # silently disappeared). Exercised here, together with the priced and
    # unpriced games above, so the populated-games-table pa11y check in
    # `make a11y` (see pipeline/README.md) covers all three cell shapes.
    date_tbd = _game("EVT-TBD", date_time=None, local_date="2026-08-01", local_time=None, date_tbd=True)
    games = [priced, unpriced, date_tbd]
    league_payload = league_data(LEAGUE, games)
    team_payload = team_data(TEAM, LEAGUE, games)
    leagues_summary = [{"slug": lg.slug, "name": lg.name, "games_count": 2} for lg in LEAGUES]
    return {
        "index": render_index(leagues=leagues_summary, not_included=list(LEAGUES_EXAMINED_NOT_INCLUDED), base_url="https://calendar.chelseakr.com"),
        "league": render_league(league=league_payload, base_url="https://calendar.chelseakr.com"),
        "team": render_team(team=team_payload, base_url="https://calendar.chelseakr.com"),
    }


def test_no_script_tags_on_any_page():
    """With no GA4 measurement ID (the default -- DECISIONS 0012), a page
    carries zero <script> elements at all. With an ID, the one allowed
    script is the guarded GA4 loader, checked in tests/test_analytics.py."""
    for page_name, html in _pages().items():
        assert not SCRIPT_TAG_RE.search(html), f"{page_name} page contains a <script> tag"


def test_no_price_rendered_without_a_ticketmaster_event_on_league_page():
    html = _pages()["league"]
    # The unpriced game's row must say "not available", and must not have
    # a dollar-shaped price anywhere near it. Since only one priced game
    # exists, exactly one price-value span should appear.
    assert html.count('class="price-value"') == 1
    assert html.count('class="price-unavailable"') >= 1
    assert "USD 12.00" in html
    assert "not available" in html


def test_no_price_rendered_without_a_ticketmaster_event_on_team_page():
    html = _pages()["team"]
    assert html.count('class="price-value"') == 1
    assert "not available" in html


def test_table_headers_present_with_scope():
    html = _pages()["league"]
    assert '<th scope="col">Date</th>' in html
    assert '<th scope="col">Price range</th>' in html


def test_buy_link_text_says_where_it_goes():
    """WCAG 2.4.4: link text must make sense out of context -- not bare
    'Buy' or 'click here'."""
    html = _pages()["league"]
    assert re.search(r"Buy tickets for .* from Ticketmaster", html)
    assert ">Buy</a>" not in html
    assert ">click here<" not in html.lower()


def test_canonical_and_og_tags_present():
    for html in _pages().values():
        assert '<link rel="canonical" href=' in html
        assert 'property="og:title"' in html
        assert 'property="og:url"' in html


def test_footer_privacy_note_is_present_and_literal():
    """With no GA4 ID the footer says there is no analytics -- and links the
    privacy page -- rather than claiming a measurement this build never
    does. (The with-ID wording is checked in tests/test_analytics.py.)"""
    for html in _pages().values():
        assert "This site runs no analytics, no scripts, and\nsets no cookies" in html
        assert "the calendar feeds are never tracked" in html
        assert '<a href="/privacy/">Privacy: what this site measures' in html
        assert "Google Analytics" not in html


def test_footer_attribution_names_ticketmaster_terms():
    html = _pages()["index"]
    assert "Ticketmaster Discovery API" in html
    assert "developer.ticketmaster.com/support/terms-of-use" in html


def test_league_page_shows_schedule_source_note():
    html = _pages()["league"]
    assert "not used" in html.lower()


def test_subscribe_block_has_webcal_and_https_and_three_platforms():
    html = _pages()["league"]
    assert "webcal://" in html
    assert "https://calendar.chelseakr.com/ics/wnba.ics" in html
    assert "iPhone" in html
    assert "Google Calendar" in html
    assert "Outlook" in html


def test_lang_attribute_present():
    for html in _pages().values():
        assert '<html lang="en">' in html


def test_index_lists_leagues_not_included_with_reason():
    from html import escape

    html = _pages()["index"]
    for item in LEAGUES_EXAMINED_NOT_INCLUDED:
        assert escape(item["name"]) in html


def test_favicon_links_present_on_every_page():
    for html in _pages().values():
        assert '<link rel="icon" href="/favicon.svg" type="image/svg+xml">' in html
        assert '<link rel="icon" href="/favicon-32.png" sizes="32x32" type="image/png">' in html
        assert '<link rel="apple-touch-icon" href="/apple-touch-icon.png">' in html


def test_og_image_tags_present_and_grounded_in_real_dimensions():
    """The image referenced is the real 1200x630 render (see
    scripts/render_social_assets.py) -- width/height are declared, not
    assumed, and the URL is absolute (base_url + filename), which is what
    every social platform's crawler requires."""
    for page_name, html in _pages().items():
        assert 'property="og:image"' in html, page_name
        assert 'property="og:image:type" content="image/png"' in html, page_name
        assert 'property="og:image:width" content="1200"' in html, page_name
        assert 'property="og:image:height" content="630"' in html, page_name
        assert 'property="og:image:alt" content="' in html, page_name
        assert 'https://calendar.chelseakr.com/og-image' in html, page_name


def test_twitter_card_tags_present():
    for html in _pages().values():
        assert '<meta name="twitter:card" content="summary_large_image">' in html
        assert 'name="twitter:title"' in html
        assert 'name="twitter:description"' in html
        assert 'name="twitter:image"' in html
        assert 'name="twitter:image:alt"' in html


def test_index_uses_the_default_site_wide_og_image():
    html = _pages()["index"]
    assert 'content="https://calendar.chelseakr.com/og-image.png"' in html
    assert "og-image-wnba" not in html


def test_league_and_team_pages_use_their_own_league_og_image():
    """A WNBA page should promise a basketball-glyph card, not the
    generic default or another league's card -- the per-league variant is
    real (see LEAGUE_OG_IMAGES), not a filename swapped without content
    to match."""
    league_html = _pages()["league"]
    team_html = _pages()["team"]
    for html in (league_html, team_html):
        assert 'content="https://calendar.chelseakr.com/og-image-wnba.png"' in html
        assert "basketball" in html
        for other in ("nwsl", "pwhl"):
            assert f"og-image-{other}.png" not in html


def test_og_site_name_present():
    for html in _pages().values():
        assert '<meta property="og:site_name" content="Next Home Game">' in html


def test_titles_use_the_product_name_never_the_repo_slug():
    """The live site's <title> and og:site_name read "womens-sports-calendar"
    (the private repo's slug) while its header said "Next Home Game"."""
    pages = _pages()
    for html in pages.values():
        title = re.search(r"<title>(.*?)</title>", html).group(1)
        assert "Next Home Game" in title
        assert "womens-sports-calendar" not in html
    assert "<title>Minnesota Lynx calendar and tickets | Next Home Game</title>" in pages["team"]


def test_team_description_names_the_team_and_the_league():
    """Brief: a team page's description must name the actual team and
    league, not a generic template repeated everywhere."""
    html = _pages()["team"]
    assert 'name="description" content="Subscribe to the Minnesota Lynx (WNBA) calendar' in html
    assert 'property="og:description" content="Subscribe to the Minnesota Lynx (WNBA) calendar' in html


def test_league_roster_links_use_real_team_names_not_title_cased_slugs():
    ncaa = next(lg for lg in LEAGUES if lg.slug == "ncaaw-big-ten")
    nwsl = next(lg for lg in LEAGUES if lg.slug == "nwsl")
    for league, real, mangled in (
        (ncaa, "UCLA Bruins Womens Basketball", "Ucla Bruins"),
        (nwsl, "Gotham FC", "Gotham Fc"),
    ):
        html = render_league(league=league_data(league, []), base_url="https://nexthomegame.com")
        assert f">{real}</a>" in html
        assert mangled not in html


def test_unsplittable_event_shows_its_real_name_never_tbd_vs_tbd():
    listing = _game("EVT-NAME", name="Washington Spirit Premium Experiences")
    assert listing.home_team is None and listing.away_team is None
    html = render_team(team=team_data(TEAM, LEAGUE, [listing]), base_url="https://nexthomegame.com")
    assert "TBD vs TBD" not in html
    assert "Washington Spirit Premium Experiences" in html
    assert "Buy tickets for Washington Spirit Premium Experiences on" in html
