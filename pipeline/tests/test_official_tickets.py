"""The "Get <team> tickets" link to each team's and league's official ticket
page (official_tickets.py).

- Every entry names a real team or league, every registry team has one
  except the ones listed here on purpose, and every URL is a plain https
  address with recorded evidence.
- Team pages carry the section whether or not a game is listed; a team with
  no verified page gets no section at all, never a guessed link.
- With no affiliate template the link is plain: no rel, no "Paid link", and
  the footer still says links are plain. With one, exactly the links to its
  host are wrapped and labelled, and the disclosure turns on.
- A click on one sends ticket_click with official: true; the .ics feeds and
  data files never carry these links.

Each checker has a negative control that sabotages the input and asserts
the checker then fails.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import pytest

from wsc_pipeline import analytics, official_tickets, sellers, site
from wsc_pipeline.analytics import ga4_head_snippet
from wsc_pipeline.config import LEAGUES
from wsc_pipeline.site import render_league, render_team
from wsc_pipeline.site_data import league_data, team_data

from .fixture_site import build_fixture_site
from .test_analytics import _LOADED, BASE_URL, TEST_ID, _link, _run_snippet, _scenarios

# Teams with no verified official ticket page, and why (official_tickets.py).
NO_OFFICIAL_PAGE = {("ncaaw-big-ten", "rutgers-scarlet-knights-womens-basketball")}

WNBA = next(lg for lg in LEAGUES if lg.slug == "wnba")
MERCURY = next(t for t in WNBA.teams if t.slug == "phoenix-mercury")
BIG_TEN = next(lg for lg in LEAGUES if lg.slug == "ncaaw-big-ten")
RUTGERS = next(t for t in BIG_TEN.teams if t.slug == "rutgers-scarlet-knights-womens-basketball")
MERCURY_URL = "https://mercury.wnba.com/tickets/"
TEMPLATE = "https://tickets.example-network.com/r/123?url={url}"


def _empty_team_page(league, team) -> str:
    return render_team(team=team_data(team, league, []), base_url=BASE_URL)


# ---- the registry ------------------------------------------------------------


def test_every_entry_is_a_registry_team_and_every_team_but_the_listed_ones_has_one():
    registry = {(lg.slug, t.slug) for lg in LEAGUES for t in lg.teams}
    entries = set(official_tickets.OFFICIAL_TEAM_TICKETS)
    assert entries <= registry, entries - registry
    assert registry - entries == NO_OFFICIAL_PAGE
    assert set(official_tickets.OFFICIAL_LEAGUE_TICKETS) <= {lg.slug for lg in LEAGUES}


def test_every_url_is_plain_https_with_evidence():
    pages = [*official_tickets.OFFICIAL_TEAM_TICKETS.values(), *official_tickets.OFFICIAL_LEAGUE_TICKETS.values()]
    for page in pages:
        assert page.url.startswith("https://") and "?" not in page.url and "#" not in page.url, page.url
        assert official_tickets.CHECKED_ON in page.evidence or "fetched" in page.evidence, page.url
    official_tickets._check()


@pytest.mark.parametrize(
    "bad",
    [
        "http://mercury.wnba.com/tickets/",
        "https://mercury.wnba.com/tickets/?utm_source=x",
        "https://mercury.wnba.com/tickets/#seats",
    ],
)
def test_control_a_url_that_is_not_plain_https_fails_the_check(bad: str, monkeypatch: pytest.MonkeyPatch):
    sabotaged = dict(official_tickets.OFFICIAL_TEAM_TICKETS)
    sabotaged[("wnba", "phoenix-mercury")] = official_tickets.OfficialTicketPage(bad, "evidence")
    monkeypatch.setattr(official_tickets, "OFFICIAL_TEAM_TICKETS", sabotaged)
    assert official_tickets.team_page("wnba", "phoenix-mercury").url == bad  # the sabotage landed
    with pytest.raises(ValueError):
        official_tickets._check()


@pytest.mark.parametrize(
    "bad", ["http://x.example.com/?u={url}", "https://x.example.com/r?u=", "https://x.example.com/{url}/{id}"]
)
def test_control_a_malformed_affiliate_template_fails_the_check(bad: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(official_tickets, "AFFILIATE_TEMPLATES", {"mercury.wnba.com": bad})
    with pytest.raises(ValueError):
        official_tickets._check()


# ---- pages -------------------------------------------------------------------


def test_a_team_page_with_no_game_listed_still_links_the_official_ticket_page():
    html = _empty_team_page(WNBA, MERCURY)
    assert '<h2 id="official-tickets-heading">Get Phoenix Mercury tickets</h2>' in html
    assert (
        f'<a href="{MERCURY_URL}">Phoenix Mercury tickets at mercury.wnba.com, '
        "the team&#x27;s official ticket page</a>." in html
    )


def test_a_big_ten_page_names_the_school_and_uses_the_searched_name():
    nebraska = next(t for t in BIG_TEN.teams if t.slug == "nebraska-cornhuskers-womens-basketball")
    html = _empty_team_page(BIG_TEN, nebraska)
    assert "Get Nebraska women&#x27;s basketball tickets" in html
    assert "the school&#x27;s official ticket page" in html
    assert "Add the Nebraska women&#x27;s basketball schedule to your calendar" in html


def test_a_team_with_no_verified_page_gets_no_section_and_no_guess():
    html = _empty_team_page(BIG_TEN, RUTGERS)
    assert "official-tickets" not in html
    assert "scarletknights" not in html


def test_league_pages_link_the_leagues_own_ticket_page_and_the_big_ten_has_none():
    wnba = render_league(league=league_data(WNBA, []), base_url=BASE_URL)
    assert '<a href="https://www.wnba.com/tickets">WNBA tickets at wnba.com' in wnba
    big_ten = render_league(league=league_data(BIG_TEN, []), base_url=BASE_URL)
    assert "official-tickets" not in big_ten


def test_with_no_template_the_link_is_plain_and_the_footer_says_so():
    html = _empty_team_page(WNBA, MERCURY)
    assert official_tickets.AFFILIATE_TEMPLATES == {}
    assert not sellers.affiliate_links_active()
    assert "sponsored" not in html and "Paid link" not in html
    assert site.AFFILIATE_NOTE_INACTIVE in html


def test_a_template_wraps_only_its_hosts_links_and_labels_them(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(official_tickets, "AFFILIATE_TEMPLATES", {"mercury.wnba.com": TEMPLATE})
    official_tickets._check()
    html = _empty_team_page(WNBA, MERCURY)
    wrapped = TEMPLATE.format(url=quote(MERCURY_URL, safe=""))
    assert f'href="{wrapped}" rel="sponsored noopener"' in html
    assert '</a> <span class="paid-link">Paid link</span>' in html
    assert sellers.affiliate_links_active()
    assert site.AFFILIATE_NOTE_ACTIVE in html
    # Another team's link is untouched.
    aces = next(t for t in WNBA.teams if t.slug == "las-vegas-aces")
    other = _empty_team_page(WNBA, aces)
    assert '<a href="https://aces.wnba.com/tickets/">' in other


# ---- clicks and feeds ----------------------------------------------------------


def _official(href: str, *, in_main: bool = True) -> dict:
    return {**_link(href, in_main=in_main), "inOfficial": True}


def test_a_click_on_an_official_ticket_page_is_a_ticket_click(tmp_path: Path):
    official = _official(MERCURY_URL)
    footer = _official(MERCURY_URL, in_main=False)
    lookalike = _link("https://mercury.wnba.com/news/")
    results = _run_snippet(
        tmp_path, ga4_head_snippet(TEST_ID, base_url=BASE_URL), _scenarios(_LOADED[:1], [official, footer, lookalike])
    )
    got = [c["pushed"] for c in results["no-signal"]["clicks"]]
    assert got == [
        [["event", "ticket_click", {"link_url": MERCURY_URL, "link_domain": "mercury.wnba.com", "official": True}]],
        [],
        [],
    ]


def test_the_rendered_section_is_the_one_the_click_listener_looks_for():
    html = _empty_team_page(WNBA, MERCURY)
    assert f'<section class="{official_tickets.OFFICIAL_SECTION_CLASS}"' in html
    assert f'a.closest("{official_tickets.OFFICIAL_SECTION_SELECTOR}")' in ga4_head_snippet(TEST_ID, base_url=BASE_URL)


def test_control_a_listener_looking_for_another_section_misses_the_click(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(analytics, "OFFICIAL_SECTION_SELECTOR", ".somewhere-else")
    snippet = ga4_head_snippet(TEST_ID, base_url=BASE_URL)
    assert ".somewhere-else" in snippet  # the sabotage landed
    results = _run_snippet(tmp_path, snippet, _scenarios(_LOADED[:1], [_official(MERCURY_URL)]))
    assert results["no-signal"]["clicks"][0]["pushed"] == []


def test_feeds_and_data_never_carry_an_official_ticket_link(tmp_path: Path):
    out = tmp_path / "dist"
    build_fixture_site(out)
    pages = [*official_tickets.OFFICIAL_TEAM_TICKETS.values(), *official_tickets.OFFICIAL_LEAGUE_TICKETS.values()]
    urls = {p.url for p in pages}
    carried = [
        path.name
        for path in [*out.rglob("*.ics"), *out.rglob("*.json")]
        if any(u in path.read_text(encoding="utf-8") for u in urls)
    ]
    assert carried == []
    # Control: the same check finds the links in the HTML pages.
    html = [p for p in out.rglob("*.html") if any(u in p.read_text(encoding="utf-8") for u in urls)]
    assert html
