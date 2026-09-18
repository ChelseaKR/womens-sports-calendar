"""Validate what search engines read on a built site, before it is published.

Run by `make verify` on the degraded build and on the populated fixture
site (scripts/build_fixture_site.py), and by pages.yml on the real fetched
build before deploy. Exits non-zero on the first site that would publish:

1. robots.txt that blocks the site or does not point at the sitemap.
2. A sitemap that is not well-formed, declares a DTD or an entity, names a
   page the build did not write, misses one it did, lists the 404 page, or
   carries a <lastmod> that is not a W3C date, lies in the future, or
   disagrees with lastmod.json.
3. An indexable page without exactly one <title>, one meta description, one
   <h1> and a canonical link to its own sitemap URL, or a title or
   description another page also uses.
4. A JSON-LD block that is not JSON, or that could close its own <script>.
5. Structured data that says more than the page's data does. Each
   SportsEvent is checked against the game in the page's data/*.json it
   describes, from that game's raw fields rather than the code that built
   the event: the game must be listed in the calendar feed, with neither
   date nor time TBD, startDate must carry a UTC offset and be the same
   instant as the game's start_utc, the home and away teams must be the
   ones the event name gave in that order, location must name the venue
   with a postal address, and eventStatus may only appear when the page
   states that status. Every eligible game must be marked up (none dropped),
   and a build that did not fetch must carry no events at all.
6. On a team page, exactly one SportsTeam, named as the page's team; on
   league and team pages, a BreadcrumbList whose items are real pages.

Usage: python -m wsc_pipeline.validate_seo <dist-dir>
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from defusedxml import DefusedXmlException
from defusedxml import ElementTree as SafeElementTree

from . import config, sitemap, structured_data

SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
# ISO 8601 with a UTC offset (or Z), whole seconds: what Google's Event
# startDate asks for, and what the site writes.
OFFSET_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2}|Z)$")
W3C_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# A lastmod may not be later than the moment of validation; a small margin
# absorbs clock skew between the build step and this one.
FUTURE_MARGIN = timedelta(minutes=5)


class SeoError(ValueError):
    pass


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.titles: list[str] = []
        self.descriptions: list[str] = []
        self.canonicals: list[str] = []
        self.h1_count = 0
        self.noindex = False
        self.jsonld: list[str] = []
        self._in: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag == "title":
            self._in, self._buf = "title", []
        elif tag == "meta" and a.get("name") == "description":
            self.descriptions.append(a.get("content", ""))
        elif tag == "meta" and a.get("name") == "robots" and "noindex" in a.get("content", ""):
            self.noindex = True
        elif tag == "link" and a.get("rel") == "canonical":
            self.canonicals.append(a.get("href", ""))
        elif tag == "h1":
            self.h1_count += 1
        elif tag == "script" and a.get("type") == "application/ld+json":
            self._in, self._buf = "jsonld", []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._in == "title":
            self.titles.append("".join(self._buf).strip())
            self._in = None
        elif tag == "script" and self._in == "jsonld":
            self.jsonld.append("".join(self._buf))
            self._in = None

    def handle_data(self, data: str) -> None:
        if self._in:
            self._buf.append(data)


def _parse_page(path: Path) -> _PageParser:
    parser = _PageParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser


def _nodes(page: Path, blocks: list[str]) -> list[dict[str, Any]]:
    """Every JSON-LD node on the page; raises SeoError on a bad block."""
    nodes: list[dict[str, Any]] = []
    for raw in blocks:
        if "<" in raw or ">" in raw:
            raise SeoError(f"{page}: a JSON-LD block contains a raw '<' or '>'")
        try:
            doc = json.loads(raw)
        except ValueError as exc:
            raise SeoError(f"{page}: a JSON-LD block is not JSON: {exc}") from exc
        if not isinstance(doc, dict) or doc.get("@context") != structured_data.CONTEXT:
            raise SeoError(f"{page}: a JSON-LD block has no https://schema.org @context")
        graph = doc.get("@graph", [doc])
        if not isinstance(graph, list) or not all(isinstance(n, dict) for n in graph):
            raise SeoError(f"{page}: a JSON-LD @graph is not a list of objects")
        nodes.extend(graph)
    return nodes


def _page_file(dist: Path, site_path: str) -> Path:
    return dist / site_path.lstrip("/") / "index.html"


def _check_robots(dist: Path, base_url: str) -> None:
    robots = dist / "robots.txt"
    if not robots.is_file():
        raise SeoError("robots.txt is missing")
    lines = [line.strip() for line in robots.read_text(encoding="utf-8").splitlines()]
    if "Disallow: /" in lines:
        raise SeoError("robots.txt disallows the whole site")
    if f"Sitemap: {base_url}/sitemap.xml" not in lines:
        raise SeoError(f"robots.txt does not name {base_url}/sitemap.xml")


def _sitemap_entries(dist: Path, base_url: str) -> dict[str, str | None]:
    """site path -> lastmod (None when omitted)."""
    # defusedxml, never the standard library parser: it refuses entity
    # expansion and external references, and forbid_dtd refuses any DOCTYPE,
    # which a sitemap never needs. The file is this build's own output, but
    # the check should not depend on that staying true.
    try:
        root = SafeElementTree.parse(dist / "sitemap.xml", forbid_dtd=True).getroot()
    except (OSError, SafeElementTree.ParseError) as exc:
        raise SeoError(f"sitemap.xml is missing or not well-formed: {exc}") from exc
    except DefusedXmlException as exc:
        raise SeoError(f"sitemap.xml declares a DTD or an entity, which a sitemap never needs: {exc!r}") from exc
    if root is None or root.tag != f"{SITEMAP_NS}urlset":
        raise SeoError("sitemap.xml is not a sitemaps.org <urlset>")
    entries: dict[str, str | None] = {}
    for url in root.findall(f"{SITEMAP_NS}url"):
        loc = (url.findtext(f"{SITEMAP_NS}loc") or "").strip()
        if not loc.startswith(base_url + "/"):
            raise SeoError(f"sitemap.xml: {loc!r} is not under {base_url}/")
        path = loc[len(base_url) :]
        if path in entries:
            raise SeoError(f"sitemap.xml lists {loc} twice")
        lastmod = url.findtext(f"{SITEMAP_NS}lastmod")
        entries[path] = lastmod.strip() if lastmod is not None else None
    return entries


def _check_lastmod(path: str, lastmod: str | None, state: dict[str, sitemap.PageState], now: datetime) -> None:
    if lastmod is None:
        if path in state and state[path].changed_at is not None:
            raise SeoError(f"sitemap.xml: {path} has no <lastmod> but lastmod.json says it changed")
        return
    if path in state:
        if lastmod != state[path].changed_at:
            raise SeoError(f"sitemap.xml: {path} lastmod {lastmod} disagrees with lastmod.json")
        if not OFFSET_DATETIME.match(lastmod):
            raise SeoError(f"sitemap.xml: {path} lastmod {lastmod!r} is not a W3C datetime with offset")
        when = datetime.fromisoformat(lastmod)
    elif W3C_DATE.match(lastmod):
        when = datetime.combine(date.fromisoformat(lastmod), datetime.min.time(), tzinfo=UTC)
    else:
        raise SeoError(f"sitemap.xml: {path} lastmod {lastmod!r} is not a W3C date")
    if when > now + FUTURE_MARGIN:
        raise SeoError(f"sitemap.xml: {path} lastmod {lastmod} is in the future")


def _indexable_pages(dist: Path) -> set[str]:
    """Site paths of every page a search engine should index: every
    <dir>/index.html the build wrote, minus fixture pages."""
    out = set()
    for page in dist.rglob("index.html"):
        rel = page.relative_to(dist).parent.as_posix()
        if rel.startswith("_"):
            continue
        out.add("/" if rel == "." else f"/{rel}/")
    return out


def _game_key(home: object, away: object, start: str) -> tuple[str, str, datetime]:
    """(home, away, instant); team names as the markup writes them, without
    a theme-night suffix (structured_data.team_label)."""
    return structured_data.team_label(str(home)), structured_data.team_label(str(away)), datetime.fromisoformat(start)


def _check_event(page: Path, node: dict[str, Any], games: list[dict[str, Any]]) -> tuple[str, str, datetime]:
    """Checks one SportsEvent against the listed games it describes (the same
    home team, away team and start instant; Ticketmaster may list one game
    more than once) and returns that key."""
    name, start = node.get("name"), node.get("startDate")
    if not isinstance(start, str) or not OFFSET_DATETIME.match(start):
        raise SeoError(f"{page}: SportsEvent {name!r} startDate {start!r} has no UTC offset")
    home = (node.get("homeTeam") or {}).get("name")
    away = (node.get("awayTeam") or {}).get("name")
    key = _game_key(home, away, start)
    matches = [
        g
        for g in games
        if g.get("start_utc") and _game_key(g.get("home_team"), g.get("away_team"), g["start_utc"]) == key
    ]
    if not matches:
        raise SeoError(f"{page}: SportsEvent {name!r} at {start} matches 0 listed games")
    known = [
        g
        for g in matches
        if g["in_calendar_feed"] and not g.get("date_tbd") and not g.get("time_tba") and g.get("home_away_known")
    ]
    if not known:
        raise SeoError(f"{page}: SportsEvent {name!r} marks up a game without a known date, time and home side")
    if name != f"{home} vs {away}":
        raise SeoError(f"{page}: SportsEvent name {name!r} is not '<home> vs <away>'")
    location = node.get("location") or {}
    address = location.get("address") or {}
    if (
        location.get("@type") != "Place"
        or address.get("@type") != "PostalAddress"
        or not any(
            location.get("name") == g.get("venue_name") and address.get("addressLocality") == g.get("venue_city")
            for g in known
        )
    ):
        raise SeoError(f"{page}: SportsEvent {name!r} location is not the listed venue with a postal address")
    stated = {structured_data.EVENT_STATUS.get(g.get("status") or "") for g in known}
    if node.get("eventStatus") not in stated:
        raise SeoError(
            f"{page}: SportsEvent {name!r} eventStatus {node.get('eventStatus')} is not what the page states"
        )
    return key


def _schedule_data(dist: Path, site_path: str) -> dict[str, Any] | None:
    """The data/*.json a league or team page renders from, or None for a
    page with no schedule."""
    parts = site_path.strip("/").split("/")
    if site_path == "/" or len(parts) not in (1, 2) or parts[0] not in {lg.slug for lg in config.LEAGUES}:
        return None
    data: dict[str, Any] = json.loads((dist / "data" / f"{'/'.join(parts)}.json").read_text(encoding="utf-8"))
    return data


def _check_structured_data(dist: Path, site_path: str, page: Path, nodes: list[dict[str, Any]]) -> None:
    types = Counter(n.get("@type") for n in nodes)
    events = [n for n in nodes if n.get("@type") == "SportsEvent"]
    data = _schedule_data(dist, site_path)
    if data is None:
        if events:
            raise SeoError(f"{page}: SportsEvent markup on a page with no schedule")
        return
    if types["BreadcrumbList"] != 1:
        raise SeoError(f"{page}: expected one BreadcrumbList, found {types['BreadcrumbList']}")
    if "team_name" in data:
        teams = [n for n in nodes if n.get("@type") == "SportsTeam"]
        if len(teams) != 1 or teams[0].get("name") != data["team_name"]:
            raise SeoError(f"{page}: expected one SportsTeam named {data['team_name']!r}")
    if not data.get("fetched", True):
        if events:
            raise SeoError(f"{page}: SportsEvent markup on a page whose schedule was not fetched")
        return
    _check_events(page, events, data["games"])


def _check_events(page: Path, events: list[dict[str, Any]], games: list[dict[str, Any]]) -> None:
    """Every SportsEvent describes one eligible listed game, and every
    eligible listed game has one."""
    marked = [_check_event(page, n, games) for n in events]
    if len(marked) != len(set(marked)):
        raise SeoError(f"{page}: a game is marked up twice")
    expected = {
        _game_key(g["home_team"], g["away_team"], g["start_utc"]) for g in games if structured_data.event_eligible(g)
    }
    if set(marked) != expected:
        missing = sorted(f"{h} vs {a} at {t.isoformat()}" for h, a, t in expected - set(marked))
        raise SeoError(f"{page}: eligible games not marked up: {missing[:5]}")


def _check_breadcrumbs(page: Path, nodes: list[dict[str, Any]], base_url: str, pages: set[str]) -> None:
    for node in nodes:
        if node.get("@type") != "BreadcrumbList":
            continue
        items = node.get("itemListElement") or []
        for i, item in enumerate(items, start=1):
            url = item.get("item", "")
            if item.get("position") != i or not item.get("name") or url[len(base_url) :] not in pages:
                raise SeoError(f"{page}: breadcrumb item {i} is not a named link to a page on this site")


def _check_page(dist: Path, site_path: str, base_url: str, pages: set[str]) -> tuple[str, str, int]:
    """Checks one indexable page; returns (title, description, events)."""
    page = _page_file(dist, site_path)
    parsed = _parse_page(page)
    if parsed.noindex:
        raise SeoError(f"{page}: a noindex page is listed in the sitemap")
    if len(parsed.titles) != 1 or not parsed.titles[0]:
        raise SeoError(f"{page}: expected exactly one non-empty <title>")
    if len(parsed.descriptions) != 1 or not parsed.descriptions[0]:
        raise SeoError(f"{page}: expected exactly one non-empty meta description")
    if parsed.h1_count != 1:
        raise SeoError(f"{page}: expected exactly one <h1>, found {parsed.h1_count}")
    if parsed.canonicals != [base_url + site_path]:
        raise SeoError(f"{page}: canonical {parsed.canonicals} is not {base_url + site_path}")
    nodes = _nodes(page, parsed.jsonld)
    _check_structured_data(dist, site_path, page, nodes)
    _check_breadcrumbs(page, nodes, base_url, pages)
    return parsed.titles[0], parsed.descriptions[0], sum(1 for n in nodes if n.get("@type") == "SportsEvent")


def _check_sitemap(dist: Path, base_url: str, now: datetime) -> set[str]:
    """robots.txt, sitemap.xml and lastmod.json agree with each other
    and with the pages built; returns the indexable pages' site paths."""
    _check_robots(dist, base_url)
    entries = _sitemap_entries(dist, base_url)
    pages = _indexable_pages(dist)
    if set(entries) != pages:
        raise SeoError(
            f"sitemap.xml and the built pages disagree -- built, not listed: {sorted(pages - set(entries))[:5]}; "
            f"listed, not built: {sorted(set(entries) - pages)[:5]}"
        )
    state_file = dist / sitemap.STATE_PATH
    state = sitemap.parse_state(json.loads(state_file.read_text(encoding="utf-8"))) if state_file.is_file() else None
    if state is None:
        raise SeoError(f"{sitemap.STATE_PATH} is missing or malformed")
    for site_path in sorted(pages):
        _check_lastmod(site_path, entries[site_path], state, now)
    return pages


def validate_dist(dist: Path, *, now: datetime | None = None) -> tuple[int, int]:
    """Returns (pages checked, SportsEvents checked); raises SeoError."""
    index = _parse_page(dist / "index.html")
    if len(index.canonicals) != 1 or not index.canonicals[0].endswith("/"):
        raise SeoError("index.html has no canonical URL to take the site's base URL from")
    base_url = index.canonicals[0].rstrip("/")
    pages = _check_sitemap(dist, base_url, now or datetime.now(UTC))
    titles: Counter[str] = Counter()
    descriptions: Counter[str] = Counter()
    n_events = 0
    for site_path in sorted(pages):
        title, description, events = _check_page(dist, site_path, base_url, pages)
        titles[title] += 1
        descriptions[description] += 1
        n_events += events
    for label, counts in (("title", titles), ("meta description", descriptions)):
        repeated = [text for text, n in counts.items() if n > 1]
        if repeated:
            raise SeoError(f"{len(repeated)} {label}(s) used by more than one page, e.g. {repeated[0]!r}")
    if not _parse_page(dist / "404.html").noindex:
        raise SeoError("404.html is not noindex")
    return len(pages), n_events


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        pages, events = validate_dist(Path(argv[0]))
    except SeoError as exc:
        print(f"SEO VALIDATION FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"seo validation: {pages} pages, sitemap and robots.txt valid; {events} SportsEvents checked against data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
