"""scripts/check_live_freshness.py's verdicts, on fixed payloads and a fixed
clock (the script itself is run against the live site by freshness.yml)."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_live_freshness.py"
NOW = datetime(2026, 9, 18, 15, 7, tzinfo=UTC)
SLA = timedelta(hours=30)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_live_freshness", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


freshness = _load()


def test_last_nights_listings_are_fresh() -> None:
    fresh, reason = freshness.assess({"fetched_at": "2026-09-18T08:31:00+00:00", "api_key_present": True}, NOW, SLA)
    assert fresh, reason
    assert "6.6 h old" in reason


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"fetched_at": "2026-09-17T08:31:00+00:00", "api_key_present": True}, "over the 30 h SLA"),
        ({"fetched_at": None, "api_key_present": True}, "no fetched_at value"),
        ({"fetched_at": "yesterday", "api_key_present": True}, "unparseable"),
        ({"fetched_at": "2026-09-18T08:31:00", "api_key_present": True}, "no time zone"),
        ({"fetched_at": "2026-09-19T08:31:00+00:00", "api_key_present": True}, "in the future"),
        ({"fetched_at": "2026-09-18T08:31:00+00:00", "api_key_present": False}, "fetched nothing"),
        (["not", "an", "object"], "not a JSON object"),
    ],
)
def test_stale_or_unreadable_listings_fail(payload: object, expected: str) -> None:
    fresh, reason = freshness.assess(payload, NOW, SLA)
    assert not fresh
    assert expected in reason


def test_a_build_before_fetched_at_falls_back_to_generated_at_and_says_so() -> None:
    fresh, reason = freshness.assess({"generated_at": "2026-09-17T08:33:01+00:00", "api_key_present": True}, NOW, SLA)
    assert not fresh
    assert "generated_at (build predates fetched_at)" in reason


def test_a_non_https_url_is_refused() -> None:
    assert freshness.main(["--url", "http://nexthomegame.com/data/site.json", "--max-age-hours", "30"]) == 2
