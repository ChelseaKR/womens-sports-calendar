"""What a searcher and a subscriber see on the league and team pages: the
title, description and H1 name the schedule and its season, the subscribe
buttons reach Google, Apple and Outlook, the next home game is the real one,
and dates are shown and machine-marked only as far as they are known."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from wsc_pipeline import site
from wsc_pipeline.config import LEAGUES
from wsc_pipeline.normalize import display_start, normalize_event
from wsc_pipeline.site_data import season_label, team_data

from .conftest import make_raw_event
from .fixture_site import BASE_URL, build_fixture_site

WNBA = LEAGUES[0]
ACES = next(t for t in WNBA.teams if t.slug == "las-vegas-aces")


@pytest.fixture(scope="module")
def fixture_dist(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("pages") / "dist"
    build_fixture_site(out)
    return out


def _aces(event_id: str, name: str, **kw):
    game = normalize_event(
        make_raw_event(event_id=event_id, name=name, **kw),
        league_slug="wnba",
        tracked_team_slug=ACES.slug,
        tracked_team_name=ACES.name,
    )
    assert game is not None
    return game


def _meta(html: str, name: str) -> str:
    return re.search(rf'<meta name="{name}" content="([^"]*)">', html).group(1)


# ---------------------------------------------------------------------------
# Titles, descriptions, headings
# ---------------------------------------------------------------------------


def test_team_page_title_description_and_h1(fixture_dist: Path):
    html = (fixture_dist / "wnba/las-vegas-aces/index.html").read_text()
    assert "<title>Las Vegas Aces 2026 schedule: add to your calendar | Next Home Game</title>" in html
    assert "<h1>Las Vegas Aces 2026 schedule</h1>" in html
    description = _meta(html, "description")
    assert description.startswith("Las Vegas Aces 2026 schedule (WNBA): add every game to Google Calendar")
    # The next HOME game: not the earlier away game, not the cancelled one.
    assert description.endswith("Next home game: Sat, Sep 19, 2026, 6:00 PM PDT vs Seattle Storm.")


def test_league_page_title_and_h1_name_the_season(fixture_dist: Path):
    html = (fixture_dist / "pwhl/index.html").read_text()
    assert "<h1>PWHL 2026 schedule</h1>" in html
    assert "<title>PWHL 2026 schedule: add to your calendar | Next Home Game</title>" in html
    # A league with no listed games claims no season.
    ausl = (fixture_dist / "ausl/index.html").read_text()
    assert "<h1>AUSL schedule</h1>" in ausl


def test_home_page_title_names_the_calendar_apps(fixture_dist: Path):
    html = (fixture_dist / "index.html").read_text()
    assert (
        "<title>Next Home Game: women&#x27;s sports schedules for Google, Apple and Outlook calendars</title>" in html
    )
    assert "WNBA, NWSL, PWHL, AUSL or NCAA Women&#x27;s Basketball (Big Ten)" in _meta(html, "description")


@pytest.mark.parametrize(
    "dates,expected",
    [
        ([], None),
        ([date(2026, 9, 19)], "2026"),
        ([date(2026, 11, 21), date(2027, 3, 1)], "2026-27"),
        ([date(2026, 1, 1), date(2028, 1, 1)], "2026-2028"),
    ],
)
def test_season_label_comes_from_the_listed_dates(dates, expected):
    games = [_aces(f"E{i}", "Las Vegas Aces vs X", local_date=d.isoformat()) for i, d in enumerate(dates)]
    assert season_label(games) == expected


def test_a_date_tbd_game_does_not_set_the_season():
    tbd = _aces("E1", "Las Vegas Aces vs X", date_time=None, local_date="2027-01-01", local_time=None, date_tbd=True)
    assert season_label([tbd]) is None


# ---------------------------------------------------------------------------
# Subscribe buttons
# ---------------------------------------------------------------------------


def test_subscribe_buttons_reach_google_apple_and_outlook(fixture_dist: Path):
    html = (fixture_dist / "wnba/las-vegas-aces/index.html").read_text()
    feed = f"{BASE_URL}/ics/wnba/las-vegas-aces.ics"
    webcal = feed.replace("https://", "webcal://")
    hrefs = dict(
        re.findall(r'<a class="subscribe-cta" href="([^"]+)">Add to ([^<]+)</a>', html)[i][::-1] for i in range(4)
    )
    google = urlparse(hrefs["Google Calendar"].replace("&amp;", "&"))
    assert google.netloc == "calendar.google.com" and google.path == "/calendar/u/0/r"
    assert parse_qs(google.query) == {"cid": [webcal]}
    assert hrefs["Apple Calendar"] == webcal
    for label, host in (("Outlook.com", "outlook.live.com"), ("Outlook for work or school", "outlook.office.com")):
        url = urlparse(hrefs[label].replace("&amp;", "&"))
        assert url.netloc == host and url.path == "/calendar/0/addfromweb/"
        assert parse_qs(url.query) == {"url": [webcal], "name": ["Las Vegas Aces (Next Home Game)"]}
    # The raw feed address is still on the page for any other app.
    assert f'<a href="{feed}">{feed}</a>' in html
    assert unquote(hrefs["Google Calendar"]).count("webcal://") == 1


def test_subscribe_buttons_come_before_the_hero_and_the_table(fixture_dist: Path):
    html = (fixture_dist / "wnba/las-vegas-aces/index.html").read_text()
    assert html.index("<h1>") < html.index('class="subscribe"') < html.index('class="next-game"')
    assert html.index('class="next-game"') < html.index('class="games-table"') < html.index('class="other-apps"')
    assert html.index('class="other-apps"') < html.index('class="about-schedule"')


# ---------------------------------------------------------------------------
# Next home game, home/away, dates
# ---------------------------------------------------------------------------


def test_hero_is_the_next_home_game_with_venue_and_time(fixture_dist: Path):
    html = (fixture_dist / "wnba/las-vegas-aces/index.html").read_text()
    hero = html[html.index('<section class="next-game"') : html.index("</section>", html.index('class="next-game"'))]
    assert '<h2 id="next-game-heading" class="next-game-label">Next home game</h2>' in hero
    assert "Las Vegas Aces vs Seattle Storm" in hero
    assert '<time datetime="2026-09-19T18:00:00-07:00">Sat, Sep 19, 2026, 6:00 PM PDT</time>' in hero
    assert "Michelob Ultra Arena, Las Vegas, NV" in hero
    assert "Los Angeles Sparks" not in hero  # the cancelled home game is skipped


def test_hero_says_so_when_no_home_game_is_listed():
    away = _aces("E1", "Seattle Storm vs Las Vegas Aces")
    html = site.render_team(team=team_data(ACES, WNBA, [away]), base_url=BASE_URL)
    assert '<h2 id="next-game-heading" class="next-game-label">Next game, away</h2>' in html
    assert "No Las Vegas Aces home game is listed by Ticketmaster right now." in html
    assert "Next home game:" not in _meta(html, "description")


def test_home_and_away_are_labelled_only_when_known(fixture_dist: Path):
    html = (fixture_dist / "wnba/las-vegas-aces/index.html").read_text()
    rows = {m.group(1).strip(): m.group(0) for m in re.finditer(r"<tr><td>.*?</td><td>([^<]+).*?</tr>", html)}
    assert 'home-away--away">Away' in rows["Seattle Storm vs Las Vegas Aces"]
    assert 'home-away--home">Home' in rows["Las Vegas Aces vs Seattle Storm"]
    assert 'home-away--away">Away' in rows["Phoenix Mercury vs Las Vegas Aces"]
    attraction_row = rows["Las Vegas Aces vs Phoenix Mercury"]  # from the attraction list: unknown
    assert "home-away" not in attraction_row
    # ...so no team's seller is assumed either: the event's own listing.
    assert 'href="https://www.ticketmaster.com/event/FX-ATTRACTIONS"' in attraction_row
    assert "home-away" not in rows["Las Vegas Aces Premium Experiences"]
    # League pages never label a side.
    assert "home-away" not in (fixture_dist / "wnba/index.html").read_text()


def test_dates_are_machine_marked_only_as_far_as_known(fixture_dist: Path):
    html = (fixture_dist / "wnba/las-vegas-aces/index.html").read_text()
    assert (
        '<time datetime="2026-09-24">Thu, Sep 24, 2026 (time TBA)</time></span> (not yet in the calendar feed)' in html
    )
    assert '<span class="game-date">Date TBD</span> (date TBD &mdash; not yet in the calendar feed)' in html
    assert '<time datetime="2026-10-01">' not in html  # the TBD game's placeholder date is never marked


def test_display_start_formats():
    assert display_start(_aces("E1", "A vs B")) == "Mon, Jun 15, 2026, 7:00 PM EDT"
    assert display_start(_aces("E2", "A vs B", timezone=None)) == "Mon, Jun 15, 2026, 7:00 PM local time"
    tba = _aces("E3", "A vs B", date_time=None, local_time=None, time_tba=True)
    assert display_start(tba) == "Mon, Jun 15, 2026 (time TBA)"


def test_a_time_tba_game_sorts_among_its_own_date():
    """Sorted by local date first: a time-TBA game on the 18th comes before
    a timed game on the 20th, so it can be the next home game."""
    later = _aces("E1", "Las Vegas Aces vs A", date_time="2026-09-21T01:00:00Z", local_date="2026-09-20")
    tba = _aces("E2", "Las Vegas Aces vs B", date_time=None, local_date="2026-09-18", local_time=None, time_tba=True)
    payload = team_data(ACES, WNBA, [later, tba])
    assert [g["event_id"] for g in payload["games"]] == ["E2", "E1"]
    assert payload["next_home_event_id"] == "E2"
