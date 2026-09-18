"""schema.org JSON-LD (structured_data.py) and its validator (validate_seo.py),
on the populated fixture site (tests/fixture_site.py) and the degraded build,
with negative controls that corrupt a built page and must be caught."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from wsc_pipeline import build as build_module
from wsc_pipeline import structured_data, validate_seo
from wsc_pipeline.config import LEAGUES
from wsc_pipeline.normalize import normalize_event
from wsc_pipeline.site_data import game_to_dict

from .conftest import make_raw_event
from .fixture_site import BASE_URL, build_fixture_site

JSONLD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL)
ACES_PAGE = Path("wnba/las-vegas-aces/index.html")


@pytest.fixture(scope="module")
def fixture_dist(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("fixture") / "dist"
    build_fixture_site(out)
    return out


def _nodes(html: str) -> list[dict]:
    blocks = JSONLD_RE.findall(html)
    return [n for b in blocks for n in json.loads(b)["@graph"]]


def _events(html: str) -> list[dict]:
    return [n for n in _nodes(html) if n["@type"] == "SportsEvent"]


def _copy(src: Path, dst: Path) -> Path:
    shutil.copytree(src, dst)
    return dst


def _sabotage(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"sabotage target not found: {old!r}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    assert path.read_text(encoding="utf-8") != text, "sabotage did not land"


# ---------------------------------------------------------------------------
# What is marked up, and what is not
# ---------------------------------------------------------------------------


def test_only_games_with_a_known_date_and_time_are_events(fixture_dist: Path):
    events = _events((fixture_dist / ACES_PAGE).read_text())
    names = sorted(e["name"] for e in events)
    assert names == [
        "Las Vegas Aces vs Los Angeles Sparks",  # cancelled, still a real dated game
        "Las Vegas Aces vs Seattle Storm",
        "Phoenix Mercury vs Las Vegas Aces",  # "Aces at Mercury"
        "Seattle Storm vs Las Vegas Aces",
    ]
    data = json.loads((fixture_dist / "data/wnba/las-vegas-aces.json").read_text())
    by_id = {g["event_id"]: g for g in data["games"]}
    # Listed on the page, but never marked up: no time, no date, not a game,
    # or no known home side.
    for skipped in ("FX-TIME-TBA", "FX-DATE-TBD", "FX-PACKAGE", "FX-ATTRACTIONS"):
        assert skipped in by_id
        assert not structured_data.event_eligible(by_id[skipped]), skipped
    assert "Atlanta Dream" not in json.dumps(events)  # the time-TBA opponent
    assert "Dallas Wings" not in json.dumps(events)  # the date-TBD opponent


def test_start_dates_carry_the_venue_offset_and_are_the_real_instant(fixture_dist: Path):
    data = json.loads((fixture_dist / "data/wnba/las-vegas-aces.json").read_text())
    for event in _events((fixture_dist / ACES_PAGE).read_text()):
        start = event["startDate"]
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}", start), start
        game = next(g for g in data["games"] if g["start_local_datetime"] == start)
        assert datetime.fromisoformat(start) == datetime.fromisoformat(game["start_utc"])
    storm = next(
        e for e in _events((fixture_dist / ACES_PAGE).read_text()) if e["name"].startswith("Las Vegas Aces vs Seattle")
    )
    assert storm["startDate"] == "2026-09-19T18:00:00-07:00"  # 01:00Z next day, in Las Vegas


def test_home_and_away_follow_the_event_name(fixture_dist: Path):
    events = {e["name"]: e for e in _events((fixture_dist / ACES_PAGE).read_text())}
    at = events["Phoenix Mercury vs Las Vegas Aces"]
    assert at["homeTeam"] == {"@type": "SportsTeam", "name": "Phoenix Mercury"}
    assert at["awayTeam"] == {"@type": "SportsTeam", "name": "Las Vegas Aces"}


def test_location_is_the_listed_venue_with_its_postal_address(fixture_dist: Path):
    toronto = _events((fixture_dist / "pwhl/toronto-sceptres/index.html").read_text())[0]
    assert toronto["location"] == {
        "@type": "Place",
        "name": "Coca-Cola Coliseum",
        "address": {
            "@type": "PostalAddress",
            "streetAddress": "45 Manitoba Dr",
            "addressLocality": "Toronto",
            "addressRegion": "ON",
            "postalCode": "M6K 3C3",
            "addressCountry": "CA",
        },
    }
    assert toronto["sport"] == "Ice hockey"
    assert toronto["startDate"] == "2026-11-21T15:00:00-05:00"


def test_event_status_only_when_ticketmaster_states_one(fixture_dist: Path):
    html = (fixture_dist / ACES_PAGE).read_text()
    events = {e["name"]: e for e in _events(html)}
    assert events["Las Vegas Aces vs Los Angeles Sparks"]["eventStatus"] == "https://schema.org/EventCancelled"
    assert '<strong class="game-status">Cancelled</strong>' in html  # and the page says so
    for name, event in events.items():
        if name != "Las Vegas Aces vs Los Angeles Sparks":
            assert "eventStatus" not in event, name


def test_team_page_has_one_accurate_sports_team_and_breadcrumbs(fixture_dist: Path):
    nodes = _nodes((fixture_dist / ACES_PAGE).read_text())
    (team,) = [n for n in nodes if n["@type"] == "SportsTeam"]
    assert team == {
        "@type": "SportsTeam",
        "@id": f"{BASE_URL}/wnba/las-vegas-aces/#team",
        "name": "Las Vegas Aces",
        "gender": "https://schema.org/Female",
        "sport": "Basketball",
        "memberOf": {"@type": "SportsOrganization", "name": "Women's National Basketball Association"},
    }
    (crumbs,) = [n for n in nodes if n["@type"] == "BreadcrumbList"]
    assert [i["item"] for i in crumbs["itemListElement"]] == [
        f"{BASE_URL}/",
        f"{BASE_URL}/wnba/",
        f"{BASE_URL}/wnba/las-vegas-aces/",
    ]


def test_league_page_marks_up_a_two_team_game_once(fixture_dist: Path):
    events = _events((fixture_dist / "wnba/index.html").read_text())
    assert [e["name"] for e in events].count("Las Vegas Aces vs Seattle Storm") == 1


def test_home_page_names_the_site(fixture_dist: Path):
    nodes = _nodes((fixture_dist / "index.html").read_text())
    assert nodes == [
        {"@type": "WebSite", "@id": f"{BASE_URL}/#website", "name": "Next Home Game", "url": f"{BASE_URL}/"}
    ]


def test_a_build_that_fetched_nothing_marks_up_no_events(tmp_path: Path):
    out = tmp_path / "dist"
    build_module.build(out_dir=out, base_url=BASE_URL, api_key=None, affiliate_id=None)
    for page in out.rglob("*.html"):
        assert '"SportsEvent"' not in page.read_text(), page
    assert '"SportsTeam"' in (out / ACES_PAGE).read_text()
    assert validate_seo.validate_dist(out)[1] == 0


def test_hostile_strings_cannot_close_the_json_ld_block():
    raw = make_raw_event(
        event_id="EVT-X",
        name='Evil</script><script>alert(1)</script> vs "Rivals" & Co',
        venue_name="</script><img src=x onerror=alert(2)>",
    )
    game = normalize_event(raw, league_slug="wnba", tracked_team_slug="t", tracked_team_name="Evil")
    assert game is not None
    block = structured_data.script_block([structured_data.sports_event(game_to_dict(game), sport="Basketball")])
    body = block.removeprefix('<script type="application/ld+json">').removesuffix("</script>\n")
    assert "<" not in body and ">" not in body and "&" not in body
    assert json.loads(body)["@graph"][0]["homeTeam"]["name"] == "Evil</script><script>alert(1)</script>"


# ---------------------------------------------------------------------------
# The validator, and controls proving each of its checks can fail
# ---------------------------------------------------------------------------


def test_validator_passes_the_fixture_site_and_counts_its_events(fixture_dist: Path):
    pages, events = validate_seo.validate_dist(fixture_dist)
    assert pages == 3 + sum(1 + len(lg.teams) for lg in LEAGUES)  # home, privacy, accessibility
    # Aces 4 + Storm 1 + Thorns 1 + Sceptres 1 on team pages; WNBA 4, NWSL 1
    # and PWHL 1 on league pages (the Aces/Storm game once).
    assert events == 13
    assert validate_seo.main([str(fixture_dist)]) == 0


@pytest.mark.parametrize(
    "page,old,new,match",
    [
        # A start time moved: the event no longer describes a listed game.
        (ACES_PAGE, '"startDate":"2026-09-19T18:00:00-07:00"', '"startDate":"2026-09-19T19:00:00-07:00"', "matches 0"),
        # A time without an offset.
        (ACES_PAGE, '"startDate":"2026-09-19T18:00:00-07:00"', '"startDate":"2026-09-19T18:00:00"', "no UTC offset"),
        # An invented status.
        (
            ACES_PAGE,
            '"sport":"Basketball"}',
            '"sport":"Basketball","eventStatus":"https://schema.org/EventPostponed"}',
            "eventStatus",
        ),
        # A home team swapped.
        (
            ACES_PAGE,
            '"homeTeam":{"@type":"SportsTeam","name":"Phoenix Mercury"},"awayTeam":{"@type":"SportsTeam","name":"Las Vegas Aces"}',
            '"homeTeam":{"@type":"SportsTeam","name":"Las Vegas Aces"},"awayTeam":{"@type":"SportsTeam","name":"Phoenix Mercury"}',
            "matches 0",
        ),
        # A second title, and a raw tag inside the JSON-LD.
        (ACES_PAGE, "<title>", "<title>Other</title><title>", "one non-empty <title>"),
        (ACES_PAGE, '"name":"Las Vegas Aces","gender"', '"name":"<b>Las Vegas Aces</b>","gender"', "raw '<'"),
        # A canonical that points elsewhere.
        (
            ACES_PAGE,
            f'rel="canonical" href="{BASE_URL}/wnba/las-vegas-aces/"',
            f'rel="canonical" href="{BASE_URL}/"',
            "canonical",
        ),
    ],
)
def test_control_a_corrupted_page_fails(fixture_dist: Path, tmp_path: Path, page, old, new, match):
    dist = _copy(fixture_dist, tmp_path / "dist")
    _sabotage(dist / page, old, new)
    with pytest.raises(validate_seo.SeoError, match=re.escape(match)):
        validate_seo.validate_dist(dist)
    assert validate_seo.main([str(dist)]) == 1


def test_control_a_dropped_event_fails(fixture_dist: Path, tmp_path: Path):
    dist = _copy(fixture_dist, tmp_path / "dist")
    page = dist / "pwhl/toronto-sceptres/index.html"
    html = page.read_text()
    assert len(_events(html)) == 1
    doc_text = JSONLD_RE.search(html).group(1)
    doc = json.loads(doc_text)
    doc["@graph"] = [n for n in doc["@graph"] if n["@type"] != "SportsEvent"]
    _sabotage(page, doc_text, json.dumps(doc, separators=(",", ":")))
    assert not _events(page.read_text())
    with pytest.raises(validate_seo.SeoError, match="eligible games not marked up"):
        validate_seo.validate_dist(dist)


def test_control_an_event_for_a_time_tba_game_fails(fixture_dist: Path, tmp_path: Path):
    """The page lists the time-TBA game; markup that gives it a start time
    anyway (here: a guessed 7 PM) must be rejected."""
    dist = _copy(fixture_dist, tmp_path / "dist")
    page = dist / ACES_PAGE
    html = page.read_text()
    doc_text = JSONLD_RE.search(html).group(1)
    doc = json.loads(doc_text)
    doc["@graph"].append(
        {
            "@type": "SportsEvent",
            "name": "Las Vegas Aces vs Atlanta Dream",
            "startDate": "2026-09-24T19:00:00-07:00",
            "location": {
                "@type": "Place",
                "name": "Michelob Ultra Arena",
                "address": {"@type": "PostalAddress", "addressLocality": "Las Vegas"},
            },
            "homeTeam": {"@type": "SportsTeam", "name": "Las Vegas Aces"},
            "awayTeam": {"@type": "SportsTeam", "name": "Atlanta Dream"},
        }
    )
    _sabotage(page, doc_text, json.dumps(doc, separators=(",", ":")))
    with pytest.raises(validate_seo.SeoError, match="matches 0 listed games"):
        validate_seo.validate_dist(dist)


def test_control_events_on_an_unfetched_page_fail(tmp_path: Path, fixture_dist: Path):
    dist = tmp_path / "dist"
    build_module.build(out_dir=dist, base_url=BASE_URL, api_key=None, affiliate_id=None)
    page = dist / ACES_PAGE
    event = _events((fixture_dist / ACES_PAGE).read_text())[0]
    html = page.read_text()
    doc_text = JSONLD_RE.search(html).group(1)
    doc = json.loads(doc_text)
    doc["@graph"].append(event)
    _sabotage(page, doc_text, json.dumps(doc, separators=(",", ":")))
    with pytest.raises(validate_seo.SeoError, match="not fetched"):
        validate_seo.validate_dist(dist)


def test_control_a_duplicated_description_fails(fixture_dist: Path, tmp_path: Path):
    dist = _copy(fixture_dist, tmp_path / "dist")
    donor = re.search(r'<meta name="description" content="([^"]*)">', (dist / "wnba/index.html").read_text()).group(1)
    victim = dist / "nwsl/index.html"
    current = re.search(r'<meta name="description" content="([^"]*)">', victim.read_text()).group(1)
    _sabotage(victim, f'<meta name="description" content="{current}">', f'<meta name="description" content="{donor}">')
    with pytest.raises(validate_seo.SeoError, match="meta description"):
        validate_seo.validate_dist(dist)


def test_two_listings_of_one_game_are_one_event(tmp_path: Path, monkeypatch):
    """Ticketmaster can list the same game under two event ids; it is still
    one SportsEvent, and the validator accepts it."""
    from wsc_pipeline.config import LEAGUES as ALL

    wnba = ALL[0]
    aces = next(t for t in wnba.teams if t.slug == "las-vegas-aces")
    raws = [
        make_raw_event(
            event_id=eid, name="Las Vegas Aces vs Seattle Storm", url=f"https://www.ticketmaster.com/event/{eid}"
        )
        for eid in ("DUP-1", "DUP-2")
    ]
    games = [
        normalize_event(r, league_slug="wnba", tracked_team_slug=aces.slug, tracked_team_name=aces.name) for r in raws
    ]
    empty = {lg.slug: set() for lg in ALL}
    monkeypatch.setattr(build_module, "fetch_all_games", lambda api_key: (games, empty, empty, 1, 1))
    out = tmp_path / "dist"
    build_module.build(out_dir=out, base_url=BASE_URL, api_key="fake-key", affiliate_id=None)
    assert len(_events((out / ACES_PAGE).read_text())) == 1
    assert validate_seo.validate_dist(out)[1] == 2  # once on the team page, once on the league page


def test_a_theme_night_suffix_is_not_part_of_the_team_name():
    raw = make_raw_event(event_id="EVT-THEME", name="Atlanta Dream vs Chicago Sky (HBCU + D9 Night)")
    game = normalize_event(raw, league_slug="wnba", tracked_team_slug="chicago-sky", tracked_team_name="Chicago Sky")
    node = structured_data.sports_event(game_to_dict(game), sport="Basketball")
    assert node["name"] == "Atlanta Dream vs Chicago Sky"
    assert node["awayTeam"] == {"@type": "SportsTeam", "name": "Chicago Sky"}
    assert structured_data.team_label("(Only parentheses)") == "(Only parentheses)"
