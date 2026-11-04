"""What the Ticketmaster Discovery API terms ask of the published site
(DECISIONS 0024), checked on a populated fixture build:

- no bulk copy of the event data: the deployed data/ directory holds only
  site.json (counts, no event), and each page's payload stays in the build's
  records beside the site;
- no event description says anything about a ticket price, including that
  one is not available (absence printed as a value, against 0013);
- every page's footer says the site is not affiliated with any league, team
  or Ticketmaster, in the same words as the Atom feeds.

Each validator rule has a negative control whose sabotage is asserted to
have applied before the validator is run on it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from icalendar import Calendar

from wsc_pipeline import feeds, validate_ics
from wsc_pipeline.config import LEAGUES
from wsc_pipeline.site_data import records_dir

from .conftest import copy_built_site
from .fixture_site import build_fixture_site

# Any wording about a price, or the lack of one, in an event description.
PRICE_WORDS = re.compile(r"price|not available|tickets:", re.IGNORECASE)


@pytest.fixture(scope="module")
def dist(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("terms") / "dist"
    build_fixture_site(out)
    return out


def _event_descriptions(dist: Path) -> list[str]:
    out = []
    for feed in sorted((dist / "ics").rglob("*.ics")):
        cal = Calendar.from_ical(feed.read_bytes())
        out.extend(str(ev.get("description", "")) for ev in cal.walk("VEVENT"))
    return out


# --- no bulk event data ------------------------------------------------------------------------------------


def test_the_site_publishes_only_the_counts_file_under_data(dist: Path):
    assert sorted(str(p.relative_to(dist / "data")) for p in (dist / "data").rglob("*")) == ["site.json"]
    site_json = json.loads((dist / "data" / "site.json").read_text())
    # Counts per league and the fetch time; no game, venue or event id.
    assert set(site_json) == {
        "generated_at",
        "api_key_present",
        "leagues",
        "leagues_examined_not_included",
        "source",
        "fetched_at",
    }
    assert all(set(lg) == {"slug", "name", "games_count", "schedule_source_used"} for lg in site_json["leagues"])
    assert "event_id" not in (dist / "data" / "site.json").read_text()


def test_each_page_payload_is_kept_beside_the_site_not_in_it(dist: Path):
    records = records_dir(dist)
    assert records.parent == dist.parent and records != dist
    for league in LEAGUES:
        assert (records / f"{league.slug}.json").is_file()
        for team in league.teams:
            assert (records / league.slug / f"{team.slug}.json").is_file()
    assert any(json.loads(p.read_text()).get("games") for p in records.rglob("*.json"))


def test_control_a_league_file_in_the_deployed_data_dir_fails(dist: Path, tmp_path: Path):
    bad = copy_built_site(dist, tmp_path / "dist")
    (bad / "data" / "pwhl.json").write_text((records_dir(bad) / "pwhl.json").read_text())
    assert (bad / "data" / "pwhl.json").is_file()
    with pytest.raises(validate_ics.FeedError, match=r"would publish pwhl\.json"):
        validate_ics.validate_dist(bad)


def test_control_a_team_file_in_the_deployed_data_dir_fails(dist: Path, tmp_path: Path):
    bad = copy_built_site(dist, tmp_path / "dist")
    (bad / "data" / "wnba").mkdir()
    (bad / "data" / "wnba" / "las-vegas-aces.json").write_text("{}")
    with pytest.raises(validate_ics.FeedError, match=r"wnba/las-vegas-aces\.json"):
        validate_ics.validate_dist(bad)


def test_the_unsabotaged_copy_passes(dist: Path, tmp_path: Path):
    """The controls above fail for their sabotage, not for the copy."""
    feeds_checked, _events = validate_ics.validate_dist(copy_built_site(dist, tmp_path / "dist"))
    assert feeds_checked > 1


# --- no price line in any event -----------------------------------------------------------------------------


def test_no_event_description_says_anything_about_a_price(dist: Path):
    descriptions = _event_descriptions(dist)
    assert len(descriptions) > 10  # the fixture build really has events
    offenders = [d for d in descriptions if PRICE_WORDS.search(d)]
    assert offenders == []


@pytest.mark.parametrize(
    "line",
    ["Tickets: price not available from Ticketmaster", "Tickets: USD 25.00-150.00 (Ticketmaster)"],
    ids=["unavailable", "priced"],
)
def test_control_a_feed_with_a_price_line_fails(dist: Path, tmp_path: Path, line: str):
    bad = copy_built_site(dist, tmp_path / "dist")
    feed = bad / "ics" / "wnba" / "las-vegas-aces.ics"
    text = feed.read_text()
    sabotaged = text.replace("DESCRIPTION:League: WNBA", f"DESCRIPTION:League: WNBA\\n{line}", 1)
    assert sabotaged != text, "sabotage target not found"
    feed.write_text(sabotaged)
    with pytest.raises(validate_ics.FeedError, match="ticket price or its absence"):
        validate_ics.validate_dist(bad)


# --- not affiliated ----------------------------------------------------------------------------------------


def test_every_page_footer_says_the_site_is_not_affiliated(dist: Path):
    pages = sorted(dist.rglob("*.html"))
    assert len(pages) > 20
    missing = []
    for page in pages:
        html = page.read_text(encoding="utf-8")
        footer = html[html.find('<footer class="site-footer">') :]
        if f"<p>{feeds.INDEPENDENCE_LINE}</p>" not in footer:
            missing.append(str(page.relative_to(dist)))
    assert missing == []


def test_the_footer_and_the_atom_feed_use_the_same_words(dist: Path):
    atom = next((dist / feeds.FEEDS_DIR).rglob("*.atom"))
    assert feeds.INDEPENDENCE_LINE in atom.read_text(encoding="utf-8")
    assert "not affiliated with any league, team or Ticketmaster" in feeds.INDEPENDENCE_LINE
