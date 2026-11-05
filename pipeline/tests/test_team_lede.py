"""A team page's first sentence answers the search: the next home game, in
the name a fan searches, or that none is listed, with the date Ticketmaster
was checked (DECISIONS 0025).

The home-game case uses the USC page as the live site had it on 2026-11-04
(USC Trojans Womens Basketball vs Utah State Aggies Womens Basketball, Galen
Center, Los Angeles, Sun, Nov 8, 2026, 5:00 PM PST). Pages are read with
html.parser, never a regex over markup.
"""

from __future__ import annotations

from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

import pytest

from wsc_pipeline import config
from wsc_pipeline.normalize import normalize_event
from wsc_pipeline.site import render_team
from wsc_pipeline.site_data import team_data

from .conftest import make_raw_event
from .fixture_site import build_fixture_site

BASE = "https://nexthomegame.com"
BIG_TEN = next(lg for lg in config.LEAGUES if lg.slug == "ncaaw-big-ten")
USC = next(t for t in BIG_TEN.teams if t.slug == "usc-trojans-womens-basketball")
NWSL = next(lg for lg in config.LEAGUES if lg.slug == "nwsl")
THORNS = next(t for t in NWSL.teams if t.slug == "portland-thorns")
CHECKED = datetime(2026, 11, 4, 8, 23, tzinfo=UTC)

# What an honest "nothing listed" sentence must never be: a placeholder
# standing in for a game, or a value standing in for "not listed".
PLACEHOLDERS = ("TBD", "TBA", "Date TBD", "N/A", "None", "Venue not available", "undefined")


class _Lede(HTMLParser):
    """The text of the first <p class="lede">, and its <time> datetimes."""

    def __init__(self) -> None:
        super().__init__()
        self.text = ""
        self.times: list[str] = []
        self._in = False
        self._done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "p" and a.get("class") == "lede" and not self._done:
            self._in = True
        if self._in and tag == "time":
            self.times.append(a.get("datetime") or "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self._in:
            self._in = False
            self._done = True

    def handle_data(self, data: str) -> None:
        if self._in:
            self.text += data


def lede(html: str) -> _Lede:
    parser = _Lede()
    parser.feed(html)
    parser.text = " ".join(parser.text.split())
    return parser


def first_sentence(html: str) -> str:
    """The lede's text up to its first full stop followed by a space."""
    text = lede(html).text
    end = text.find(". ")
    return text if end < 0 else text[: end + 1]


def assert_honest_no_home_game(sentence: str, name: str, checked_on: str) -> None:
    """The no-home-game sentence: says no home game is listed, names the team
    as a fan searches it, gives the date Ticketmaster was checked, and has
    no placeholder in it."""
    assert sentence.strip(), "the opening sentence is blank"
    assert sentence.startswith("Ticketmaster lists no upcoming "), sentence
    assert name in sentence, sentence
    assert f"as of {checked_on}" in sentence, sentence
    for placeholder in PLACEHOLDERS:
        assert placeholder not in sentence, (placeholder, sentence)


def _usc_game(event_id: str = "U1", **kw):
    fields = {
        "name": "USC Trojans Womens Basketball vs Utah State Aggies Womens Basketball",
        "date_time": "2026-11-09T01:00:00Z",
        "local_date": "2026-11-08",
        "local_time": "17:00:00",
        "venue_name": "Galen Center",
        "venue_city": "Los Angeles",
        "venue_state": "CA",
        "timezone": "America/Los_Angeles",
        "url": f"https://www.ticketmaster.com/event/{event_id}",
    }
    fields.update(kw)
    game = normalize_event(
        make_raw_event(event_id=event_id, **fields),
        league_slug=BIG_TEN.slug,
        tracked_team_slug=USC.slug,
        tracked_team_name=USC.name,
    )
    assert game is not None
    return game


def _usc_page(games, *, fetched: bool = True, fetched_at: datetime | None = CHECKED) -> str:
    payload = team_data(USC, BIG_TEN, games, fetched=fetched)
    if fetched_at is not None:
        payload["fetched_at"] = fetched_at.isoformat()
    return render_team(team=payload, base_url=BASE)


def test_the_first_sentence_is_the_next_home_game_in_the_name_fans_search():
    page = lede(_usc_page([_usc_game()]))
    assert page.text.startswith(
        "The next USC women's basketball home game is against Utah State Aggies at Galen Center "
        "in Los Angeles, CA, on Sunday, November 8, 2026, at 5:00 PM PST."
    ), page.text
    assert page.times == ["2026-11-08T17:00:00-08:00"]
    # The Ticketmaster keyword and the league's long name are gone from the lede.
    assert "USC Trojans Womens Basketball" not in page.text
    assert "NCAA Women's Basketball (Big Ten)" not in page.text
    assert "(Big Ten)" in page.text


def test_a_team_without_a_title_name_keeps_its_shown_name():
    raw = make_raw_event(
        event_id="T1",
        name="Portland Thorns FC vs Seattle Reign FC",
        venue_name="Providence Park",
        venue_city="Portland",
        venue_state="OR",
        timezone="America/Los_Angeles",
        date_time="2026-06-16T02:00:00Z",
    )
    game = normalize_event(raw, league_slug="nwsl", tracked_team_slug=THORNS.slug, tracked_team_name=THORNS.name)
    assert game is not None
    payload = team_data(THORNS, NWSL, [game])
    text = lede(render_team(team=payload, base_url=BASE)).text
    assert text.startswith("The next Portland Thorns home game is against Seattle Reign FC at Providence Park"), text


def test_a_team_with_no_games_says_so_with_the_date_it_was_checked():
    """The negative control the brief asks for: no game at all renders the
    honest sentence, not a blank, a "TBD" or a stand-in date."""
    page = _usc_page([])
    sentence = first_sentence(page)
    assert_honest_no_home_game(sentence, "USC women's basketball", "Wednesday, November 4, 2026")
    assert "home or away" in sentence
    assert lede(page).times == ["2026-11-04"]


def test_a_team_with_only_away_games_says_no_home_game_is_listed():
    away = _usc_game(
        "U2",
        name="UCLA Bruins Womens Basketball vs USC Trojans Womens Basketball",
        venue_name="Pauley Pavilion",
    )
    page = _usc_page([away])
    sentence = first_sentence(page)
    assert_honest_no_home_game(sentence, "USC women's basketball home game", "Wednesday, November 4, 2026")
    assert "Pauley Pavilion" not in sentence


def test_control_the_honesty_check_rejects_a_blank_or_placeholder_sentence():
    """The check above must be able to fail: each planted defect is caught."""
    bad = [
        "",
        "The next USC women's basketball home game is TBD.",
        "The next USC women's basketball home game is on Date TBD.",
        "Ticketmaster lists no upcoming USC women's basketball home game right now.",
        "Ticketmaster lists no upcoming USC Trojans Womens Basketball home game as of Wednesday, November 4, 2026.",
    ]
    for sentence in bad:
        with pytest.raises(AssertionError):
            assert_honest_no_home_game(sentence, "USC women's basketball", "Wednesday, November 4, 2026")


def test_with_no_fetch_time_it_says_right_now_and_invents_no_date():
    text = lede(_usc_page([], fetched_at=None)).text
    assert text.startswith(
        "Ticketmaster lists no upcoming USC women's basketball (Big Ten) game, home or away, right now."
    ), text


def test_a_build_that_did_not_check_claims_nothing_about_games():
    text = lede(_usc_page([], fetched=False, fetched_at=None)).text
    assert text.startswith("Every USC women's basketball (Big Ten) game Ticketmaster lists"), text
    assert "lists no" not in text
    assert "next" not in text.lower()


def test_an_unannounced_time_is_said_in_words_not_as_a_placeholder():
    page = lede(_usc_page([_usc_game(local_time=None, time_tba=True, date_time=None)]))
    assert page.text.startswith(
        "The next USC women's basketball home game is against Utah State Aggies at Galen Center "
        "in Los Angeles, CA, on Sunday, November 8, 2026, start time not announced yet."
    ), page.text
    assert page.times == ["2026-11-08"]
    assert "TBA" not in first_sentence(_usc_page([_usc_game(local_time=None, time_tba=True, date_time=None)]))


def test_an_unannounced_date_gets_no_date_and_no_time_element():
    page = lede(_usc_page([_usc_game(date_tbd=True, local_date="2026-11-08", local_time=None, date_time=None)]))
    assert page.text.startswith(
        "The next USC women's basketball home game Ticketmaster lists is against Utah State Aggies "
        "at Galen Center in Los Angeles, CA; its date is not announced yet."
    ), page.text
    assert page.times == []


def test_a_missing_venue_and_opponent_are_left_out_not_filled_in():
    game = _usc_game(name="USC Trojans Womens Basketball vs Utah State Aggies Womens Basketball")
    payload = team_data(USC, BIG_TEN, [game])
    payload["fetched_at"] = CHECKED.isoformat()
    for g in payload["games"]:
        g.update(away_team=None, venue_name=None, venue_city=None, venue_state=None)
    text = lede(render_team(team=payload, base_url=BASE)).text
    assert text.startswith(
        "The next USC women's basketball home game is on Sunday, November 8, 2026, at 5:00 PM PST."
    ), text
    assert "Venue not available" not in text
    assert "against" not in text


def test_a_postponed_home_game_says_so():
    text = lede(_usc_page([_usc_game(status="postponed")])).text
    assert "Ticketmaster lists it as postponed." in text, text


@pytest.fixture(scope="module")
def dist(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("lede") / "dist"
    build_fixture_site(out, now=datetime(2026, 9, 18, 8, 30, tzinfo=UTC))
    return out


def test_every_built_team_page_opens_with_the_fan_name_and_no_placeholder(dist: Path):
    seen = 0
    for league in config.LEAGUES:
        for team in league.teams:
            html = (dist / league.slug / team.slug / "index.html").read_text()
            sentence = first_sentence(html)
            assert sentence.startswith(("The next ", "Ticketmaster lists no upcoming ")), (team.slug, sentence)
            assert team.search_title_name in sentence, (team.slug, sentence)
            if team.title_name:
                assert team.shown_name not in lede(html).text, (team.slug, sentence)
            for placeholder in PLACEHOLDERS:
                assert placeholder not in sentence, (team.slug, placeholder, sentence)
            seen += 1
    assert seen == sum(len(lg.teams) for lg in config.LEAGUES)
