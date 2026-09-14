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
    games = [priced, unpriced]
    league_payload = league_data(LEAGUE, games)
    team_payload = team_data(TEAM, LEAGUE, games)
    leagues_summary = [{"slug": lg.slug, "name": lg.name, "games_count": 2} for lg in LEAGUES]
    return {
        "index": render_index(leagues=leagues_summary, not_included=list(LEAGUES_EXAMINED_NOT_INCLUDED), base_url="https://calendar.chelseakr.com"),
        "league": render_league(league=league_payload, base_url="https://calendar.chelseakr.com"),
        "team": render_team(team=team_payload, base_url="https://calendar.chelseakr.com"),
    }


def test_no_script_tags_on_any_page():
    """DECISIONS 0002 / brief: no JavaScript that contacts anyone but us --
    the simplest and strongest guarantee is zero <script> elements at all."""
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
    html = _pages()["index"]
    assert "Nothing leaves your browser" in html
    assert "no tracking cookie" in html


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
