"""SportsEvent required fields, performer and offers (DECISIONS 0030), on the
populated fixture site, with negative controls: markup that states a fact
the page does not (a venue, a status, a price, an Offer for a game the page
sends to a team's seller page) must not be emitted, and must fail
validate_seo when planted on a built page."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from wsc_pipeline import structured_data, validate_seo
from wsc_pipeline.normalize import normalize_event
from wsc_pipeline.site_data import game_to_dict

from .conftest import copy_built_site, make_raw_event
from .fixture_site import build_fixture_site

JSONLD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL)
ACES_PAGE = Path("wnba/las-vegas-aces/index.html")
SCEPTRES_PAGE = Path("pwhl/toronto-sceptres/index.html")
OFFSET_START = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}")
# Offer properties the site never has a fact for.
INVENTED_OFFER_KEYS = {"price", "priceCurrency", "lowPrice", "highPrice", "availability", "validFrom"}


@pytest.fixture(scope="module")
def fixture_dist(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("fixture") / "dist"
    build_fixture_site(out)
    return out


def _events(html: str) -> list[dict]:
    return [n for b in JSONLD_RE.findall(html) for n in json.loads(b)["@graph"] if n["@type"] == "SportsEvent"]


def _keys(value) -> list[str]:
    """Every property name anywhere inside a JSON value."""
    if isinstance(value, dict):
        return [k for key, item in value.items() for k in (key, *_keys(item))]
    if isinstance(value, list):
        return [k for item in value for k in _keys(item)]
    return []


def _game(**kwargs) -> dict:
    raw = make_raw_event(**kwargs)
    game = normalize_event(
        raw, league_slug="wnba", tracked_team_slug="indiana-fever", tracked_team_name="Indiana Fever"
    )
    assert game is not None
    return game_to_dict(game)


def _replace_events(page: Path, edit) -> None:
    """Rewrites the page's JSON-LD with edit(event) applied to every
    SportsEvent, and checks the page really changed."""
    html = page.read_text(encoding="utf-8")
    doc_text = JSONLD_RE.search(html).group(1)
    doc = json.loads(doc_text)
    for node in doc["@graph"]:
        if node["@type"] == "SportsEvent":
            edit(node)
    new_text = json.dumps(doc, separators=(",", ":"))
    assert new_text != doc_text, "sabotage did not change the markup"
    page.write_text(html.replace(doc_text, new_text, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Every emitted event is valid for Google's Event rules
# ---------------------------------------------------------------------------


def test_every_event_has_googles_required_properties(fixture_dist: Path):
    events = [e for page in fixture_dist.rglob("index.html") for e in _events(page.read_text())]
    assert len(events) == 18
    for event in events:
        assert event["name"], event
        assert OFFSET_START.fullmatch(event["startDate"]), event
        assert event["location"]["@type"] == "Place"
        assert event["location"]["name"]
        assert event["location"]["address"]["@type"] == "PostalAddress"
        assert event["location"]["address"]["addressLocality"]
        assert event["performer"] == [event["homeTeam"], event["awayTeam"]]
        if "offers" in event:
            assert set(event["offers"]) == {"@type", "url"}, event
        assert not INVENTED_OFFER_KEYS & set(_keys(event)), event


def test_offers_only_for_a_games_own_ticketmaster_listing(fixture_dist: Path):
    aces = {e["name"]: e for e in _events((fixture_dist / ACES_PAGE).read_text())}
    # Away games: the page's "Buy tickets" link is the Ticketmaster event.
    assert aces["Phoenix Mercury vs Las Vegas Aces"]["offers"] == {
        "@type": "Offer",
        "url": "https://www.ticketmaster.com/event/FX-AT",
    }
    assert aces["Seattle Storm vs Las Vegas Aces"]["offers"]["url"] == "https://www.ticketmaster.com/event/FX-AWAY"
    # Aces home games: the link goes to the Aces' page at AXS, which is not
    # this game's listing, so there is no Offer (and the page says AXS).
    assert "offers" not in aces["Las Vegas Aces vs Seattle Storm"]
    assert "offers" not in aces["Las Vegas Aces vs Los Angeles Sparks"]
    assert "from AXS" in (fixture_dist / ACES_PAGE).read_text()
    (sceptres,) = _events((fixture_dist / SCEPTRES_PAGE).read_text())
    assert sceptres["offers"]["url"] == "https://www.ticketmaster.ca/event/FX-SCEPTRES"


# ---------------------------------------------------------------------------
# Absence stays absent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "missing",
    [
        {"venue_name": None, "venue_city": None, "venue_state": None},
        {"venue_name": None},
        {"venue_city": None},
        {"venue_state": None},
    ],
)
def test_control_a_game_without_a_venue_gets_no_location(missing: dict):
    """Google requires location.name and location.address, and the site
    never fills a venue in: such a game is still listed on the page, but has
    no SportsEvent, so no location property anywhere."""
    game = _game(**missing)
    assert game["start_local_datetime"]  # dated and timed, so only the venue is missing
    assert structured_data.sports_event(game, sport="Basketball") is None
    assert structured_data.sports_events([game], sport="Basketball", fetched=True) == []
    # Negative control on the control: the same game with its venue is marked up.
    full = structured_data.sports_event(_game(), sport="Basketball")
    assert full is not None and full["location"]["name"] == "Gainbridge Fieldhouse"


@pytest.mark.parametrize(
    "code,status",
    [
        ("cancelled", "https://schema.org/EventCancelled"),
        ("canceled", "https://schema.org/EventCancelled"),
        ("postponed", "https://schema.org/EventPostponed"),
        ("rescheduled", "https://schema.org/EventRescheduled"),
        ("onsale", None),
        ("offsale", None),
        (None, None),
    ],
)
def test_control_event_status_only_from_ticketmasters_status(code, status):
    node = structured_data.sports_event(_game(status=code), sport="Basketball")
    assert node is not None
    assert node.get("eventStatus") == status
    if status == "https://schema.org/EventCancelled":
        assert "offers" not in node  # no Offer for a game that will not be played
    else:
        assert node["offers"] == {"@type": "Offer", "url": "https://www.ticketmaster.com/event/EVT1"}


def test_control_no_ticket_url_means_no_offer():
    node = structured_data.sports_event(_game(url=None), sport="Basketball")
    assert node is not None and "offers" not in node


# ---------------------------------------------------------------------------
# The validator catches each invented fact
# ---------------------------------------------------------------------------


def _price(node: dict) -> None:
    if "offers" in node:
        node["offers"].update({"price": "0", "priceCurrency": "USD"})


def _availability(node: dict) -> None:
    if "offers" in node:
        node["offers"]["availability"] = "https://schema.org/InStock"


def _offer_for_seller_page(node: dict) -> None:
    if node["name"] == "Las Vegas Aces vs Seattle Storm":
        node["offers"] = {"@type": "Offer", "url": "https://www.ticketmaster.com/event/FX-H2H"}


def _drop_offer(node: dict) -> None:
    node.pop("offers", None)


def _swap_performer(node: dict) -> None:
    node["performer"] = list(reversed(node["performer"]))


def _guess_postponed(node: dict) -> None:
    node.setdefault("eventStatus", "https://schema.org/EventPostponed")


@pytest.mark.parametrize(
    "edit,match",
    [
        (_price, "offers is not just the url"),
        (_availability, "offers is not just the url"),
        (_offer_for_seller_page, "offers is not just the url"),
        (_drop_offer, "has no Offer"),
        (_swap_performer, "performer"),
        (_guess_postponed, "eventStatus"),
    ],
)
def test_control_an_invented_fact_fails_validation(fixture_dist: Path, tmp_path: Path, edit, match):
    dist = tmp_path / "dist"
    copy_built_site(fixture_dist, dist)
    validate_seo.validate_dist(dist)  # the untouched copy passes
    _replace_events(dist / ACES_PAGE, edit)
    with pytest.raises(validate_seo.SeoError, match=re.escape(match)):
        validate_seo.validate_dist(dist)
