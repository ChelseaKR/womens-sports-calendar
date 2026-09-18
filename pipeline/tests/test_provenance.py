"""Every published record says where it came from and when it was fetched
(DATA-GOVERNANCE-STANDARD DG-01, DG-02, DG-04; RELEASE-AND-VERSIONING-STANDARD
§5.3 build stamp)."""

from __future__ import annotations

import json
import re
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

import pytest

from wsc_pipeline import build as build_module
from wsc_pipeline import site_data
from wsc_pipeline.config import LEAGUES
from wsc_pipeline.normalize import Game, normalize_event

from .conftest import make_raw_event

BASE_URL = "https://nexthomegame.com"
DATA_CARDS = Path(__file__).resolve().parents[2] / "docs" / "data"
# DATA-GOVERNANCE-STANDARD §1: the fields every data card states.
CARD_FIELDS = (
    "Source",
    "License",
    "Fetch/refresh cadence",
    "Staleness SLA",
    "Fetch timestamp",
    "Tier",
    "Known limitations",
    "Retention",
)


def _fetched() -> tuple[list[Game], dict[str, set[str]], dict[str, set[str]], int, int]:
    league, team = LEAGUES[0], LEAGUES[0].teams[0]
    raw = make_raw_event(event_id="EVT-PROV", name=f"{team.name} vs Visiting Team")
    game = normalize_event(raw, league_slug=league.slug, tracked_team_slug=team.slug, tracked_team_name=team.name)
    assert game is not None
    return [game], {lg.slug: set() for lg in LEAGUES}, {lg.slug: set() for lg in LEAGUES}, 1, 100


def _data_files(root: Path) -> dict[str, dict[str, object]]:
    return {str(p.relative_to(root)): json.loads(p.read_text()) for p in sorted((root / "data").rglob("*.json"))}


def test_every_data_file_and_the_build_stamp_carry_source_and_fetch_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(build_module, "fetch_all_games", lambda api_key: _fetched())
    monkeypatch.setenv("GITHUB_SHA", "0123456789abcdef0123456789abcdef01234567")
    out = tmp_path / "dist"
    before = datetime.now().astimezone()
    build_module.build(out_dir=out, base_url=BASE_URL, api_key="fake-key", affiliate_id=None)

    files = _data_files(out)
    expected = 1 + sum(1 + len(lg.teams) for lg in LEAGUES)  # site.json + league + team files
    assert len(files) == expected
    fetched_at = {payload["fetched_at"] for payload in files.values()}
    assert len(fetched_at) == 1, "every file of one build states the same fetch time"
    (stamp,) = fetched_at
    assert isinstance(stamp, str) and datetime.fromisoformat(stamp) >= before
    assert {payload["source"] for payload in files.values()} == {site_data.SOURCE_ID}

    built = json.loads((out / "version.json").read_text())
    assert built["fetched_at"] == stamp
    assert built["source"] == site_data.SOURCE_ID
    assert built["commit"] == "0123456789abcdef0123456789abcdef01234567"
    assert built["pipeline_version"] == version("wsc-pipeline")


def test_a_build_that_fetched_nothing_states_no_fetch_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    out = tmp_path / "dist"
    build_module.build(out_dir=out, base_url=BASE_URL, api_key=None, affiliate_id=None)
    assert {payload["fetched_at"] for payload in _data_files(out).values()} == {None}
    built = json.loads((out / "version.json").read_text())
    assert built["fetched_at"] is None
    assert built["commit"] is None
    team_page = (out / LEAGUES[0].slug / LEAGUES[0].teams[0].slug / "index.html").read_text()
    assert "Listings as of" not in team_page


def test_league_and_team_pages_say_when_the_listings_were_fetched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(build_module, "fetch_all_games", lambda api_key: _fetched())
    out = tmp_path / "dist"
    build_module.build(out_dir=out, base_url=BASE_URL, api_key="fake-key", affiliate_id=None)
    stamp = json.loads((out / "version.json").read_text())["fetched_at"]
    for page in (out / LEAGUES[0].slug / "index.html", out / LEAGUES[0].slug / LEAGUES[0].teams[0].slug / "index.html"):
        html = page.read_text()
        match = re.search(r'Listings as of <time datetime="([^"]+)">([^<]+) UTC</time>', html)
        assert match, f"{page}: no fetch time on the page"
        assert match.group(1) == stamp


@pytest.mark.parametrize("source_id", [site_data.SOURCE_ID])
def test_every_data_source_has_a_complete_data_card(source_id: str) -> None:
    card = DATA_CARDS / f"{source_id}.md"
    assert card.is_file(), f"no data card for {source_id} at {card}"
    text = card.read_text(encoding="utf-8")
    missing = [field for field in CARD_FIELDS if not re.search(rf"^\| {re.escape(field)} \| \S", text, re.MULTILINE)]
    assert not missing, f"{card.name} has no value for {missing}"
