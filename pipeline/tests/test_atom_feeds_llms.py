"""Atom feeds under /feeds/, their autodiscovery links, and /llms.txt.

Everything is read back from a built fixture site with real parsers (an XML
parser, html.parser, the llms.txt grammar), not substring checks. The
fixture's fetch time is the wall clock, so two builds of the same data are
built at different times: a feed that leaked the fetch time would differ.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

import pytest
from defusedxml import ElementTree as SafeElementTree

from wsc_pipeline import feeds, llms

from .fixture_site import BASE_URL, build_fixture_site

NS = {"a": "http://www.w3.org/2005/Atom"}
RFC3339_Z = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
# Home-game entries the fixture holds: Aces (2, one cancelled), Thorns, Sceptres.
EXPECTED = {"wnba": 2, "nwsl": 1, "pwhl": 1, "all": 4}


@pytest.fixture(scope="module")
def two_builds(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    root = tmp_path_factory.mktemp("feeds")
    a, b = root / "a", root / "b"
    build_fixture_site(a)
    build_fixture_site(b)
    return a, b


def parse_feed(text: str) -> ET.Element:
    root = SafeElementTree.fromstring(text)  # raises ParseError on malformed XML
    assert root.tag == f"{{{NS['a']}}}feed"
    return root


def check_feed(root: ET.Element, *, base_url: str = BASE_URL) -> list[ET.Element]:
    """Asserts the feed's invariants; returns its entries."""
    assert root.findtext("a:id", namespaces=NS).startswith(base_url + "/feeds/")
    updated = root.findtext("a:updated", namespaces=NS)
    assert RFC3339_Z.match(updated)
    self_link = root.find("a:link[@rel='self']", NS)
    assert self_link.get("href") == root.findtext("a:id", namespaces=NS)
    assert self_link.get("type") == "application/atom+xml"
    assert root.findtext("a:author/a:name", namespaces=NS)
    entries = root.findall("a:entry", NS)
    assert entries
    ids = [e.findtext("a:id", namespaces=NS) for e in entries]
    assert len(set(ids)) == len(ids)
    for e in entries:
        assert RFC3339_Z.match(e.findtext("a:updated", namespaces=NS))
        assert e.findtext("a:title", namespaces=NS)
        assert e.findtext("a:summary", namespaces=NS)
        href = e.find("a:link[@rel='alternate']", NS).get("href")
        assert href.startswith(base_url + "/") and href.endswith("/")
    assert updated == max(e.findtext("a:updated", namespaces=NS) for e in entries)
    return entries


def test_feeds_exist_for_leagues_with_home_games_only(two_builds):
    built, _ = two_builds
    written = {p.stem for p in (built / "feeds").glob("*.atom")}
    assert written == set(EXPECTED)  # no empty ausl feed
    for key, count in EXPECTED.items():
        entries = check_feed(parse_feed((built / feeds.feed_path(key)).read_text(encoding="utf-8")))
        assert len(entries) == count, key


def test_entries_are_home_games_with_exact_starts(two_builds):
    built, _ = two_builds
    root = parse_feed((built / feeds.feed_path("wnba")).read_text(encoding="utf-8"))
    by_id = {e.findtext("a:id", namespaces=NS): e for e in root.findall("a:entry", NS)}
    assert set(by_id) == {
        f"{BASE_URL}/wnba/las-vegas-aces/#game-FX-H2H",
        f"{BASE_URL}/wnba/las-vegas-aces/#game-FX-CANCELLED",
    }
    h2h = by_id[f"{BASE_URL}/wnba/las-vegas-aces/#game-FX-H2H"]
    assert h2h.findtext("a:updated", namespaces=NS) == "2026-09-20T01:00:00Z"
    assert h2h.findtext("a:title", namespaces=NS) == "Las Vegas Aces vs Seattle Storm, Sep 19"
    cancelled = by_id[f"{BASE_URL}/wnba/las-vegas-aces/#game-FX-CANCELLED"]
    assert "(Cancelled)" in cancelled.findtext("a:title", namespaces=NS)
    # Never an away game, a time-TBA game, a date-TBD game, or an unknown-home listing.
    text = (built / feeds.feed_path("all")).read_text(encoding="utf-8")
    for absent in ("FX-AWAY", "FX-AT", "FX-TIME-TBA", "FX-DATE-TBD", "FX-PACKAGE", "FX-ATTRACTIONS"):
        assert absent not in text


def test_ids_and_dates_are_stable_between_two_builds(two_builds):
    a, b = two_builds
    for key in EXPECTED:
        ta = (a / feeds.feed_path(key)).read_text(encoding="utf-8")
        tb = (b / feeds.feed_path(key)).read_text(encoding="utf-8")
        assert ta == tb, key


def test_negative_control_stability_check_detects_a_fetch_time_leak(two_builds):
    """Sabotage: stamp each entry's updated with the build's fetch time. The
    two builds then differ, and the stability assertion above would fail."""
    a, b = two_builds
    fetch_a = re.search(r"Listings as of[^<]*", (a / "wnba" / "index.html").read_text(encoding="utf-8"))
    fetch_b = re.search(r"Listings as of[^<]*", (b / "wnba" / "index.html").read_text(encoding="utf-8"))
    assert fetch_a and fetch_b  # the pages do print a fetch time, so a leak could occur
    text = (a / feeds.feed_path("wnba")).read_text(encoding="utf-8")
    sabotaged_a = text.replace("2026-09-20T01:00:00Z", "BUILD-A")
    sabotaged_b = text.replace("2026-09-20T01:00:00Z", "BUILD-B")
    assert sabotaged_a != text  # the sabotage applied
    assert sabotaged_a != sabotaged_b


def test_negative_control_malformed_xml_is_rejected():
    with pytest.raises(ET.ParseError):
        parse_feed("<feed xmlns='http://www.w3.org/2005/Atom'><entry></feed>")
    with pytest.raises(AssertionError):  # wrong root element
        parse_feed("<rss/>")


def test_negative_control_invariants_catch_a_bad_feed(two_builds):
    built, _ = two_builds
    text = (built / feeds.feed_path("nwsl")).read_text(encoding="utf-8")
    bad = text.replace("2026-09-27T", "2026-09-27 ")  # not RFC 3339
    assert bad != text
    with pytest.raises(AssertionError):
        check_feed(parse_feed(bad))


URL = re.compile(r"https?://[^\s<>\"']+")
BUY_OR_AFFILIATE = re.compile(r"impact|sjv\.io|ticketmaster\.|utm_|fanatics|seatgeek|\?", re.I)


def foreign_or_tracking_urls(text: str) -> list[str]:
    """Every URL in the text that is not a plain page on this site."""
    return [u for u in URL.findall(text) if not u.startswith(BASE_URL + "/") or BUY_OR_AFFILIATE.search(u)]


def test_feeds_carry_no_buy_or_affiliate_links(two_builds):
    built, _ = two_builds
    for key in EXPECTED:
        text = (built / feeds.feed_path(key)).read_text(encoding="utf-8")
        root = parse_feed(text)
        hrefs = [el.get("href") for el in root.iter(f"{{{NS['a']}}}link")]
        assert hrefs and all(h.startswith(BASE_URL + "/") for h in hrefs)
        # (the namespace URI is the one allowed outside URL)
        assert foreign_or_tracking_urls(text.replace(NS["a"], "")) == []


def test_negative_control_affiliate_check_fires():
    assert foreign_or_tracking_urls('<link href="https://www.ticketmaster.com/event/FX-1"/>')
    assert foreign_or_tracking_urls("https://x.sjv.io/c/123")
    assert foreign_or_tracking_urls(f"{BASE_URL}/wnba/?utm_source=x")
    assert foreign_or_tracking_urls(f"{BASE_URL}/wnba/") == []


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.atom: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        d = dict(attrs)
        if tag == "link" and d.get("rel") == "alternate" and d.get("type") == "application/atom+xml":
            self.atom.append(d)


def atom_links(html: str) -> list[dict[str, str | None]]:
    p = _Links()
    p.feed(html)
    return p.atom


def test_autodiscovery_links_point_at_feeds_that_exist(two_builds):
    built, _ = two_builds
    pages = {
        "index.html": "all",
        "wnba/index.html": "wnba",
        "wnba/las-vegas-aces/index.html": "wnba",
        "nwsl/portland-thorns/index.html": "nwsl",
        "pwhl/index.html": "pwhl",
    }
    for page, key in pages.items():
        links = atom_links((built / page).read_text(encoding="utf-8"))
        assert [link["href"] for link in links] == [f"{BASE_URL}/{feeds.feed_path(key)}"], page
        assert links[0]["title"]
        assert (built / feeds.feed_path(key)).is_file()


def test_no_autodiscovery_where_no_feed_exists(two_builds):
    built, _ = two_builds
    # AUSL has no home game in the fixture, so no feed and no link on its pages.
    assert not (built / feeds.feed_path("ausl")).exists()
    assert atom_links((built / "ausl" / "index.html").read_text(encoding="utf-8")) == []
    # Pages that are not about a league advertise nothing.
    assert atom_links((built / "privacy" / "index.html").read_text(encoding="utf-8")) == []


def test_negative_control_link_parser_sees_a_link():
    html = '<head><link rel="alternate" type="application/atom+xml" href="/x"></head>'
    assert atom_links(html) == [{"rel": "alternate", "type": "application/atom+xml", "href": "/x"}]
    assert atom_links('<link rel="alternate" type="text/html" href="/x">') == []


def parse_llms(text: str) -> dict:
    """The llmstxt.org grammar: H1, blockquote, free text, then H2 sections
    of '- [name](url): note' lists."""
    lines = text.split("\n")
    assert lines[0].startswith("# ") and not lines[0].startswith("## ")
    assert lines[2].startswith("> ")
    sections: dict[str, list[tuple[str, str]]] = {}
    current = None
    for line in lines[3:]:
        if line.startswith("## "):
            current = line[3:]
            sections[current] = []
        elif line.startswith("# "):
            raise AssertionError("second H1")
        elif current and line.strip():
            m = re.match(r"^- \[([^\]]+)\]\((https://[^)\s]+)\)(?:: .+)?$", line)
            assert m, line
            sections[current].append((m.group(1), m.group(2)))
    return {"title": lines[0][2:], "sections": sections}


def test_llms_txt_follows_the_format_and_lists_only_real_files(two_builds):
    built, _ = two_builds
    text = (built / "llms.txt").read_text(encoding="utf-8")
    doc = parse_llms(text)
    assert doc["title"] == "Next Home Game"
    assert llms.SPEC_URL in text
    urls = [u for items in doc["sections"].values() for _, u in items]
    assert urls
    for url in urls:
        assert url.startswith(BASE_URL + "/")
        path = url[len(BASE_URL) + 1 :]
        target = built / (path or "index.html")
        if target.is_dir():
            target = target / "index.html"
        assert target.is_file(), url
    # Feeds listed are exactly the feeds written.
    listed = {u for n, u in doc["sections"]["Feeds (Atom) and data"] if u.endswith(".atom")}
    written = {f"{BASE_URL}/{feeds.feed_path(p.stem)}" for p in (built / "feeds").glob("*.atom")}
    assert listed == written
    assert "Ticketmaster" in text and "08:13 UTC" in text


def test_negative_control_llms_parser_rejects_bad_files():
    with pytest.raises(AssertionError):
        parse_llms("Next Home Game\n\n> x\n")
    with pytest.raises(AssertionError):
        parse_llms("# T\n\n> x\n## S\n- not a link\n")
    ok = parse_llms("# T\n\n> x\n\n## S\n\n- [a](https://e.com/): note\n")
    assert ok["sections"]["S"] == [("a", "https://e.com/")]


def test_llms_lists_no_feed_that_was_not_written():
    text = llms.render(base_url=BASE_URL, feed_keys={"wnba"})
    assert "/feeds/wnba.atom" in text and "/feeds/nwsl.atom" not in text and "/feeds/all.atom" not in text
