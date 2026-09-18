"""Output encoding of third-party data, and no credential in error output.

Every string on the site and in the calendar feeds comes from Ticketmaster.
These tests feed hostile values through the real normalize -> site_data ->
render / .ics path and assert what reaches the reader is inert
(SECURITY-AND-SUPPLY-CHAIN-STANDARD §5, SEC-20), and that the API key never
appears in an error the build prints (OBSERVABILITY-STANDARD §3, OBS-11).
"""

from __future__ import annotations

import re
from collections.abc import Callable

import httpx
import pytest

from wsc_pipeline.config import LEAGUES
from wsc_pipeline.ics import team_calendar
from wsc_pipeline.normalize import Game, normalize_event, safe_ticket_url
from wsc_pipeline.site import render_league, render_team
from wsc_pipeline.site_data import league_data, team_data
from wsc_pipeline.ticketmaster import DiscoveryClient, TicketmasterFetchError

from .conftest import make_raw_event

LEAGUE = LEAGUES[0]
TEAM = LEAGUE.teams[0]
HOSTILE = '"><script>alert(1)</script><img src=x onerror=alert(2)>'
FAKE_KEY = "k3y-SENTINEL-do-not-print-0123456789"


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        " javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
        "//evil.example/path",
        "https:///no-host",
        "https://",
        "",
        None,
        42,
    ],
)
def test_a_ticket_url_that_is_not_http_is_dropped(url: object) -> None:
    assert safe_ticket_url(url) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://www.ticketmaster.com/event/EVT1",
        "HTTPS://www.ticketmaster.ca/event/EVT1?affiliate=1",
        "http://www.ticketmaster.com/event/EVT1",
    ],
)
def test_an_http_ticket_url_is_kept_verbatim(url: str) -> None:
    assert safe_ticket_url(url) == url


def _hostile_game(**overrides: object) -> Game:
    fields: dict[str, object] = {
        "event_id": "EVT-X",
        "name": f"{HOSTILE} vs Rivals",
        "venue_name": HOSTILE,
        "venue_city": HOSTILE,
        "venue_state": HOSTILE,
        "price_ranges": [{"type": "standard", "currency": HOSTILE, "min": 10.0, "max": 20.0}],
        "url": "javascript:alert(document.domain)",
    }
    fields.update(overrides)
    raw = make_raw_event(**fields)
    game = normalize_event(raw, league_slug=LEAGUE.slug, tracked_team_slug=TEAM.slug, tracked_team_name=TEAM.name)
    assert game is not None
    return game


def _rendered_pages() -> dict[str, str]:
    game = _hostile_game()
    return {
        "league": render_league(league=league_data(LEAGUE, [game]), base_url="https://nexthomegame.com"),
        "team": render_team(team=team_data(TEAM, LEAGUE, [game]), base_url="https://nexthomegame.com"),
    }


def test_hostile_ticketmaster_strings_render_as_text_not_markup() -> None:
    pages = _rendered_pages()
    for name, html in pages.items():
        assert HOSTILE.replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;") in html, name
        # The page's own JSON-LD block is the only <script> allowed, and it
        # escapes "<" and ">", so the hostile "</script><script>" cannot
        # close it and open a new one.
        scripts = re.findall(r"<script\b[^>]*>", html, re.IGNORECASE)
        assert scripts in ([], ['<script type="application/ld+json">']), f"{name}: raw <script> reached the page"
        assert html.count("</script>") == len(scripts), f"{name}: a hostile string closed a <script>"
        assert "<img src=x" not in html, f"{name}: raw <img> reached the page"


SAFE_HREF = re.compile(r"^(https?://|webcal://|/|#)")


def test_a_javascript_ticket_url_never_becomes_a_link() -> None:
    for name, html in _rendered_pages().items():
        assert "javascript:" not in html.lower(), f"{name}: a javascript: URL reached the page"
        hrefs = re.findall(r'href="([^"]*)"', html)
        assert hrefs, f"{name}: no links found; the check examined nothing"
        unsafe = [h for h in hrefs if not SAFE_HREF.match(h)]
        assert not unsafe, f"{name}: links with an unexpected scheme: {unsafe}"


def test_a_javascript_ticket_url_never_reaches_the_calendar_feed() -> None:
    feed = team_calendar(TEAM.slug, TEAM.name, [_hostile_game()]).to_ical().decode()
    assert "javascript:" not in feed.lower()
    assert "URL:" not in feed


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> DiscoveryClient:
    transport = httpx.MockTransport(handler)
    return DiscoveryClient(FAKE_KEY, client=httpx.Client(transport=transport), min_interval=0.0, max_retries=2)


def test_a_transport_error_that_echoes_the_url_does_not_leak_the_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert FAKE_KEY in str(request.url)  # the key really is in the URL
        raise httpx.ConnectError(f"cannot reach {request.url}", request=request)

    with _client(handler) as client, pytest.raises(TicketmasterFetchError) as caught:
        client.search_team_events(TEAM.slug, TEAM.name, ("US",))
    assert FAKE_KEY not in str(caught.value)
    assert "[redacted]" in str(caught.value)


def test_an_error_body_that_echoes_the_key_does_not_leak_it() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f'{{"fault": "Invalid ApiKey {FAKE_KEY}"}}')

    with _client(handler) as client, pytest.raises(TicketmasterFetchError) as caught:
        client.search_team_events(TEAM.slug, TEAM.name, ("US",))
    assert FAKE_KEY not in str(caught.value)
    assert "401" in str(caught.value)
