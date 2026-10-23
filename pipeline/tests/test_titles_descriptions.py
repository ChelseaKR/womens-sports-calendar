"""Page titles and meta descriptions: the words a fan types ("schedule and
tickets", "home games"), the next home game's date when one is listed, no
more than 60 and 155 characters, and a claim only where the page backs it.
Page URLs, headings, feeds and data files are unchanged."""

from __future__ import annotations

import re
import shutil
from datetime import UTC, datetime
from html import unescape
from pathlib import Path

import pytest

from wsc_pipeline import build as build_module
from wsc_pipeline import config, site, validate_seo
from wsc_pipeline.normalize import normalize_event
from wsc_pipeline.site_data import team_data

from .conftest import make_raw_event
from .fixture_site import BASE_URL, build_fixture_site

TITLE_MAX = 60
DESCRIPTION_MAX = 155
LONG_OPPONENT = "Minnesota Golden Gophers Womens Basketball"
ALL_TEAMS = [(lg, t) for lg in config.LEAGUES for t in lg.teams]


@pytest.fixture(scope="module")
def dist(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("titles") / "dist"
    build_fixture_site(out, now=datetime(2026, 9, 18, 8, 30, tzinfo=UTC))
    return out


def _head(html: str) -> tuple[str, str]:
    title = unescape(re.search(r"<title>(.*?)</title>", html).group(1))
    description = unescape(re.search(r'<meta name="description" content="([^"]*)">', html).group(1))
    return title, description


def _game(league, team, event_id: str, name: str, **kw):
    raw = make_raw_event(event_id=event_id, name=name, url=f"https://www.ticketmaster.com/event/{event_id}", **kw)
    game = normalize_event(raw, league_slug=league.slug, tracked_team_slug=team.slug, tracked_team_name=team.name)
    assert game is not None
    return game


def _page(league, team, games) -> str:
    return site.render_team(team={**team_data(team, league, games), "fetched_at": None}, base_url=BASE_URL)


def _home_games(league, team):
    # A long opponent and a season spanning two years: the worst case for length.
    return [
        _game(
            league,
            team,
            "H1",
            f"{team.name} vs {LONG_OPPONENT}",
            date_time="2026-11-20T01:00:00Z",
            local_date="2026-11-19",
        ),
        _game(
            league,
            team,
            "H2",
            f"{team.name} vs {LONG_OPPONENT}",
            date_time="2027-02-20T01:00:00Z",
            local_date="2027-02-19",
        ),
    ]


def _away_games(league, team):
    return [
        _game(
            league,
            team,
            "A1",
            f"{LONG_OPPONENT} vs {team.name}",
            date_time="2026-11-20T01:00:00Z",
            local_date="2026-11-19",
        )
    ]


# ---------------------------------------------------------------------------
# Length and uniqueness, for every page of a populated and an unfetched build
# ---------------------------------------------------------------------------


def _pages_of(root: Path):
    for page in sorted(root.rglob("index.html")):
        if page.parent.name.startswith("_") or "noindex" in page.read_text():
            continue
        yield page, *_head(page.read_text())


def test_every_listed_page_of_a_populated_build_fits(dist: Path):
    seen = list(_pages_of(dist))
    assert len(seen) > 10
    for page, title, description in seen:
        assert len(title) <= TITLE_MAX, (page, title)
        assert len(description) <= DESCRIPTION_MAX, (page, description)
    assert validate_seo.validate_dist(dist)


def test_every_page_of_an_unfetched_build_fits(tmp_path: Path):
    out = tmp_path / "dist"
    build_module.build(out_dir=out, base_url=BASE_URL, api_key=None, affiliate_id=None)
    seen = list(_pages_of(out))
    assert len(seen) >= 70  # every team page: the worst case, 67 teams plus the site pages
    for page, title, description in seen:
        assert len(title) <= TITLE_MAX, (page, title)
        assert len(description) <= DESCRIPTION_MAX, (page, description)
    assert len({t for _, t, _ in seen}) == len(seen)
    assert len({d for _, _, d in seen}) == len(seen)
    assert validate_seo.validate_dist(out)


@pytest.mark.parametrize("scenario", ["home", "away", "none"])
def test_every_configured_team_fits_with_the_longest_opponent(scenario: str):
    titles, descriptions = [], []
    for league, team in ALL_TEAMS:
        games = {"home": _home_games, "away": _away_games, "none": lambda lg, t: []}[scenario](league, team)
        title, description = _head(_page(league, team, games))
        assert len(title) <= TITLE_MAX, title
        assert len(description) <= DESCRIPTION_MAX, description
        titles.append(title)
        descriptions.append(description)
    assert len(set(titles)) == len(titles) == 67
    assert len(set(descriptions)) == len(descriptions)


# ---------------------------------------------------------------------------
# What the words are
# ---------------------------------------------------------------------------


def test_a_team_with_a_home_game_says_schedule_tickets_home_games_and_the_date(dist: Path):
    title, description = _head((dist / "wnba/las-vegas-aces/index.html").read_text())
    assert title == "Las Vegas Aces schedule and tickets: home games 2026"
    assert description.startswith("Next Las Vegas Aces home game: Sat, Sep 19, 2026, 6:00 PM PDT vs Seattle Storm.")
    assert "ticket links" in description


def test_the_date_is_the_next_home_game_and_a_tba_time_is_not_made_up():
    league, team = config.LEAGUES[0], config.LEAGUES[0].teams[0]
    tba = _game(
        league,
        team,
        "T1",
        f"{team.name} vs Seattle Storm",
        date_time=None,
        local_date="2026-09-24",
        local_time=None,
        time_tba=True,
    )
    _, description = _head(_page(league, team, [tba]))
    assert "Next Minnesota Lynx home game: Thu, Sep 24, 2026 (time TBA) vs Seattle Storm." in description


def test_away_only_claims_no_home_game():
    league, team = config.LEAGUES[1], config.LEAGUES[1].teams[0]
    title, description = _head(_page(league, team, _away_games(league, team)))
    assert "home games" not in title and "home game" not in description
    assert title.endswith("schedule and tickets 2026")
    assert "ticket links" in description  # games are listed, each with its seller link


def test_a_team_with_nothing_listed_claims_no_tickets_and_says_so():
    league, team = config.LEAGUES[0], config.LEAGUES[0].teams[0]
    title, description = _head(_page(league, team, []))
    assert title == "Minnesota Lynx schedule"
    assert "tickets" not in title + description
    assert "No games are listed right now" in description


def test_an_unfetched_team_says_nothing_about_games():
    league, team = config.LEAGUES[0], config.LEAGUES[0].teams[0]
    html = site.render_team(team=team_data(team, league, [], fetched=False), base_url=BASE_URL)
    title, description = _head(html)
    assert title == "Minnesota Lynx schedule"
    assert "No games are listed" not in description and "ticket" not in description


def test_big_ten_names_are_short_in_titles_and_descriptions_only(dist: Path):
    league = next(lg for lg in config.LEAGUES if lg.slug == "ncaaw-big-ten")
    team = next(t for t in league.teams if t.slug == "ohio-state-buckeyes-womens-basketball")
    games = [
        _game(
            league,
            team,
            "B1",
            f"{team.name} vs Rutgers Scarlet Knights Womens Basketball",
            date_time="2026-11-20T01:00:00Z",
            local_date="2026-11-19",
        )
    ]
    html = _page(league, team, games)
    title, description = _head(html)
    assert title == "Ohio State women's basketball schedule and tickets 2026" or title.startswith(
        "Ohio State women's basketball"
    )
    assert "Buckeyes" not in title and "Womens" not in title
    assert "vs Rutgers." in description and "Scarlet Knights" not in description
    # The page itself, its feed and its address keep the full name.
    assert "<h1>Ohio State Buckeyes Womens Basketball 2026 schedule</h1>" in html
    assert team.slug == "ohio-state-buckeyes-womens-basketball"
    assert team.shown_name == "Ohio State Buckeyes Womens Basketball"


def test_no_url_changed(dist: Path):
    expected = {f"/{lg.slug}/{t.slug}/" for lg, t in ALL_TEAMS} | {f"/{lg.slug}/" for lg in config.LEAGUES}
    built = {"/" + p.parent.relative_to(dist).as_posix() + "/" for p in dist.rglob("index.html") if p.parent != dist}
    assert expected <= built
    for lg, t in ALL_TEAMS:
        assert (dist / "ics" / lg.slug / f"{t.slug}.ics").is_file()
        canonical = re.search(
            r'<link rel="canonical" href="([^"]+)"', (dist / lg.slug / t.slug / "index.html").read_text()
        )
        assert canonical is None or canonical.group(1) == f"{BASE_URL}/{lg.slug}/{t.slug}/"


# ---------------------------------------------------------------------------
# Controls: each sabotage is asserted to have applied
# ---------------------------------------------------------------------------


def _corrupt(src: Path, dst: Path, rel: str, old: str, new: str) -> Path:
    shutil.copytree(src, dst)
    path = dst / rel
    text = path.read_text()
    assert old in text, f"sabotage target not found: {old!r}"
    path.write_text(text.replace(old, new, 1))
    assert path.read_text() != text
    return dst


def test_control_the_validator_rejects_a_long_title(dist: Path, tmp_path: Path):
    old = "<title>Las Vegas Aces schedule and tickets: home games 2026</title>"
    out = _corrupt(dist, tmp_path / "dist", "wnba/las-vegas-aces/index.html", old, "<title>" + "x" * 61 + "</title>")
    assert len(_head((out / "wnba/las-vegas-aces/index.html").read_text())[0]) == 61
    with pytest.raises(validate_seo.SeoError, match="title is 61 characters"):
        validate_seo.validate_dist(out)


def test_control_the_validator_rejects_a_long_description(dist: Path, tmp_path: Path):
    description = _head((dist / "wnba/las-vegas-aces/index.html").read_text())[1]
    out = _corrupt(dist, tmp_path / "dist", "wnba/las-vegas-aces/index.html", description, "y" * 156)
    assert len(_head((out / "wnba/las-vegas-aces/index.html").read_text())[1]) == 156
    with pytest.raises(validate_seo.SeoError, match="meta description is 156 characters"):
        validate_seo.validate_dist(out)


def test_control_the_limit_is_what_shortens_a_title(monkeypatch: pytest.MonkeyPatch):
    league = next(lg for lg in config.LEAGUES if lg.slug == "ncaaw-big-ten")
    team = next(t for t in league.teams if t.slug == "michigan-state-spartans-womens-basketball")
    games = _home_games(league, team)
    fitted = _head(_page(league, team, games))[0]
    monkeypatch.setattr(site, "TITLE_MAX", 1000)
    unfitted = _head(_page(league, team, games))[0]
    assert len(fitted) <= TITLE_MAX < len(unfitted)  # the sabotage applied: the long form returned


def test_control_the_short_names_are_what_fit_the_big_ten(monkeypatch: pytest.MonkeyPatch):
    league = next(lg for lg in config.LEAGUES if lg.slug == "ncaaw-big-ten")
    team = next(t for t in league.teams if t.slug == "michigan-state-spartans-womens-basketball")
    games = _home_games(league, team)
    with_short = _head(_page(league, team, games))[0]
    monkeypatch.setattr(site, "title_name_for", lambda league_slug, name: name)
    without = _head(_page(league, team, games))[0]
    assert "Spartans" in without and "Spartans" not in with_short  # the sabotage applied
    assert without != with_short
