"""Fail when the live site's listings are older than their staleness SLA.

DATA-GOVERNANCE-STANDARD DG-04 and ADR 0003: the nightly build replaces the
site only when a fetch fully succeeds, so a broken fetch leaves yesterday's
listings live -- correct, but invisible unless something looks. This reads
the published `data/site.json` and exits 1 when its `fetched_at` is older
than the SLA, missing, null, unparseable, in the future, or when the site
cannot be read at all; `.github/workflows/freshness.yml` runs it daily and
opens a sev2 incident issue on failure.

A build from before `fetched_at` existed carries only `generated_at` (the
build time, a few minutes after the fetch); that is used and said so.

Usage: check_live_freshness.py --url https://nexthomegame.com/data/site.json --max-age-hours 30
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta

import httpx

USER_AGENT = "NextHomeGame-freshness/1 (+https://nexthomegame.com/)"


def assess(payload: object, now: datetime, max_age: timedelta) -> tuple[bool, str]:
    """(fresh, one-line reason) for a parsed site.json."""
    if not isinstance(payload, dict):
        return False, "site.json is not a JSON object"
    if payload.get("api_key_present") is False:
        return False, "the live build fetched nothing (api_key_present is false); a degraded build was deployed"
    if "fetched_at" in payload:
        field, stamp = "fetched_at", payload["fetched_at"]
    else:
        field, stamp = "generated_at (build predates fetched_at)", payload.get("generated_at")
    if not isinstance(stamp, str) or not stamp:
        return False, f"no {field} value: {stamp!r}"
    try:
        fetched = datetime.fromisoformat(stamp)
    except ValueError:
        return False, f"unparseable {field}: {stamp!r}"
    if fetched.tzinfo is None:
        return False, f"{field} has no time zone: {stamp!r}"
    age = now - fetched
    if age < -timedelta(minutes=5):
        return False, f"{field} {stamp} is in the future"
    hours, limit = age.total_seconds() / 3600, max_age.total_seconds() / 3600
    if age > max_age:
        return False, f"listings are {hours:.1f} h old, over the {limit:g} h SLA ({field} {stamp})"
    return True, f"listings are {hours:.1f} h old, within the {limit:g} h SLA ({field} {stamp})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--max-age-hours", type=float, required=True)
    args = parser.parse_args(argv)
    if not args.url.startswith("https://"):
        print(f"STALE CHECK FAILED: refusing a non-https URL {args.url!r}")
        return 2
    try:
        response = httpx.get(args.url, headers={"User-Agent": USER_AGENT}, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        print(f"STALE CHECK FAILED: could not read {args.url}: {exc}")
        return 1
    fresh, reason = assess(payload, datetime.now(UTC), timedelta(hours=args.max_age_hours))
    print(("fresh: " if fresh else "STALE: ") + reason)
    return 0 if fresh else 1


if __name__ == "__main__":
    sys.exit(main())
