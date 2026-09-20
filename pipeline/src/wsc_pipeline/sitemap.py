"""sitemap.xml and robots.txt, with a lastmod that means what it says
(docs/adr/0005-sitemap-lastmod-from-the-live-site.md).

A page's <lastmod> is when that page's schedule last changed, never when the
site was built: the build runs every night, so a build-time lastmod would
claim every page changed every night and teach search engines to ignore it.

The build is stateless (a fresh checkout every night, no cache, no write
access to the repository), so the only record of what was published last is
the live site itself. Every build therefore publishes /lastmod.json: for
each schedule page, a fingerprint of the content it rendered from and when
that content was first seen. The next build reads the live copy back and,
page by page:

- same fingerprint: the schedule did not change, so the old date carries
  over (including "unknown");
- different fingerprint, or a page the last build did not have: it changed
  in this build, so the date is this build's fetch time;
- no readable previous manifest (the first deploy with this file, or the
  live site unreachable): whether anything changed is unknown, so the date
  is unknown and the page gets no <lastmod> at all -- absence, never a
  guess. The next successful comparison fills it in from the first real
  change onward.

A build that fetched nothing (degraded mode) observed no schedule, so it
records no dates either; the deploy workflow never publishes one anyway.

The fingerprint covers everything the page renders from except when it was
fetched (the "Listings as of" line changes every night; the schedule may
not). The privacy and accessibility pages are not schedules: their lastmod
is the "Updated" date printed on each page, from one constant in site.py.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from html import escape
from typing import Any

import httpx

from .ticketmaster import USER_AGENT

STATE_PATH = "lastmod.json"
STATE_SCHEMA = 1
# Keys of a page payload that say when it was fetched, not what it holds.
PROVENANCE_KEYS = frozenset({"fetched_at", "source", "generated_at"})


@dataclass(frozen=True)
class PageState:
    fingerprint: str
    changed_at: str | None


def fingerprint(payload: Mapping[str, Any]) -> str:
    """A stable hash of what a page renders from, provenance excluded."""
    content = {k: v for k, v in payload.items() if k not in PROVENANCE_KEYS}
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_state(payload: object) -> dict[str, PageState] | None:
    """The page map from a lastmod.json body, or None when it is not
    exactly the shape this module writes -- a malformed file is treated as
    no history, never partly trusted."""
    if not isinstance(payload, dict) or payload.get("schema") != STATE_SCHEMA:
        return None
    pages = payload.get("pages")
    if not isinstance(pages, dict):
        return None
    out: dict[str, PageState] = {}
    for path, entry in pages.items():
        if not isinstance(path, str) or not isinstance(entry, dict):
            return None
        fp, changed = entry.get("fingerprint"), entry.get("changed_at")
        if not isinstance(fp, str) or not (changed is None or _is_datetime(changed)):
            return None
        out[path] = PageState(fingerprint=fp, changed_at=changed)
    return out


def _is_datetime(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False


def fetch_previous_state(base_url: str, *, client: httpx.Client | None = None) -> dict[str, PageState] | None:
    """The live site's lastmod.json, or None when it cannot be read.
    Never raises: a missing history costs only lastmod dates, and must never
    stop tonight's calendars from publishing."""
    url = f"{base_url}/{STATE_PATH}"
    owns_client = client is None
    http = client or httpx.Client(timeout=15.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
    try:
        response = http.get(url)
        if response.status_code != 200:
            print(f"NOTE: {url} returned HTTP {response.status_code}; sitemap dates start unknown.", file=sys.stderr)
            return None
        state = parse_state(response.json())
    except (httpx.HTTPError, ValueError) as exc:
        print(f"NOTE: could not read {url} ({exc}); sitemap dates start unknown.", file=sys.stderr)
        return None
    finally:
        if owns_client:
            http.close()
    if state is None:
        print(f"NOTE: {url} is not a lastmod manifest this build can read; dates start unknown.", file=sys.stderr)
    return state


def next_state(
    fingerprints: Mapping[str, str],
    previous: Mapping[str, PageState] | None,
    observed_at: datetime | None,
) -> dict[str, PageState]:
    """This build's page map, per the rules in the module docstring."""
    stamp = observed_at.isoformat() if observed_at else None
    out: dict[str, PageState] = {}
    for path, fp in fingerprints.items():
        if stamp is None or previous is None:
            changed = None
        elif path in previous and previous[path].fingerprint == fp:
            changed = previous[path].changed_at
        else:
            changed = stamp
        out[path] = PageState(fingerprint=fp, changed_at=changed)
    return out


def render_state(state: Mapping[str, PageState]) -> str:
    return (
        json.dumps(
            {
                "schema": STATE_SCHEMA,
                "about": "When each page's schedule last changed; read back by the next nightly build.",
                "pages": {
                    path: {"fingerprint": s.fingerprint, "changed_at": s.changed_at}
                    for path, s in sorted(state.items())
                },
            },
            indent=2,
        )
        + "\n"
    )


def render_sitemap(base_url: str, entries: list[tuple[str, str | date | None]]) -> str:
    """entries: (site path, lastmod) in order; lastmod None = omitted."""
    rows = []
    for path, lastmod in entries:
        row = f"  <url><loc>{escape(base_url + path, quote=False)}</loc>"
        if lastmod is not None:
            value = lastmod.isoformat() if isinstance(lastmod, date) else lastmod
            row += f"<lastmod>{escape(value, quote=False)}</lastmod>"
        rows.append(row + "</url>")
    body = "\n".join(rows)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}\n</urlset>\n"
    )


def render_robots(base_url: str) -> str:
    """Everything may be crawled; the sitemap says what is worth indexing.
    The 404 page keeps itself out with its own noindex."""
    return f"User-agent: *\nAllow: /\n\nSitemap: {base_url}/sitemap.xml\n"
