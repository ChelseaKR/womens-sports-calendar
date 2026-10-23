"""The footer's removal and correction contact (roadmap decision B).

REMOVAL_CONTACT_EMAIL ships set to the owner's address. Every page's footer carries one paragraph
with a mailto link (a golden pins the exact footer) and nothing else on any
page, feed or data file differs from the unset state. Unset (None), every page
is byte-identical to what main rendered before the setting existed (two
goldens rendered by main's unmodified _footer, and a whole fixture-site build). A value that is not a plain address stops the build.

Pages are read with html.parser, never a regex over markup. The .ics DTSTAMP
is the build's fetch time, so a comparison between two builds strips it.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

import pytest

from wsc_pipeline import site

from .fixture_site import build_fixture_site

GOLDEN = Path(__file__).parent / "golden"
ADDRESS = "chelsea@chelseakr.com"


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.mailto: list[str] = []
        self.footer_text: list[str] = []
        self._in_footer = False

    def handle_starttag(self, tag, attrs):
        if tag == "footer":
            self._in_footer = True
        href = dict(attrs).get("href") or ""
        if tag == "a" and href.startswith("mailto:"):
            self.mailto.append(href)

    def handle_endtag(self, tag):
        if tag == "footer":
            self._in_footer = False

    def handle_data(self, data):
        if self._in_footer:
            self.footer_text.append(data)


def _parse(html: str) -> _Links:
    page = _Links()
    page.feed(html)
    return page


def _tree(root: Path) -> dict[str, bytes]:
    """Every file of a build, DTSTAMP lines removed from the .ics feeds."""
    out = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        raw = path.read_bytes()
        if path.suffix == ".ics":
            raw = b"\r\n".join(line for line in raw.split(b"\r\n") if not line.startswith(b"DTSTAMP"))
        out[path.relative_to(root).as_posix()] = raw
    return out


def test_ships_set_to_the_owners_address():
    assert site.REMOVAL_CONTACT_EMAIL == ADDRESS


def test_default_footer_equals_the_on_golden():
    golden = (GOLDEN / "footer_removal_on_no_analytics.html").read_text(encoding="utf-8")
    assert site._footer(analytics_on=False) == golden
    assert f'<a href="mailto:{ADDRESS}">{ADDRESS}</a>' in golden


@pytest.mark.parametrize("analytics_on,name", [(False, "no_analytics"), (True, "analytics")])
def test_unset_footer_is_byte_identical_to_main(analytics_on, name, monkeypatch):
    monkeypatch.setattr(site, "REMOVAL_CONTACT_EMAIL", None)
    golden = (GOLDEN / f"footer_removal_off_{name}.html").read_text(encoding="utf-8")
    assert site.REMOVAL_CONTACT_EMAIL is None  # patch applied
    assert site._footer(analytics_on=analytics_on) == golden


def test_set_footer_adds_exactly_one_paragraph():
    golden = (GOLDEN / "footer_removal_off_no_analytics.html").read_text(encoding="utf-8")
    on = site._footer(analytics_on=False)
    assert on != golden
    page = _parse(on)
    assert page.mailto == [f"mailto:{ADDRESS}"]
    assert ADDRESS in "".join(page.footer_text)
    # Removing the one added paragraph gives main's footer back, byte for byte.
    added = site._removal_contact()
    assert added.startswith("\n<p") and on.replace(added, "", 1) == golden


def test_a_whole_build_changes_only_by_the_footer_paragraph(tmp_path: Path, monkeypatch):
    # One fixed fetch time for both builds: with the wall clock, a second ticking
    # over between them changed fetched_at in the data files and failed this test.
    built_at = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(site, "REMOVAL_CONTACT_EMAIL", None)
    build_fixture_site(tmp_path / "off", now=built_at)
    monkeypatch.undo()
    assert site.REMOVAL_CONTACT_EMAIL == ADDRESS  # the shipped default is what "on" builds
    build_fixture_site(tmp_path / "on", now=built_at)
    off, on = _tree(tmp_path / "off"), _tree(tmp_path / "on")
    assert off.keys() == on.keys()
    added = site._removal_contact().encode()
    html = [n for n in off if n.endswith(".html")]
    assert len(html) > 40
    for name in off:
        if name.endswith(".html"):
            # Every page carries the paragraph once; without it the page is main's.
            assert on[name].count(added) == 1, name
            assert on[name].replace(added, b"", 1) == off[name], name
            assert _parse(off[name].decode()).mailto == [], name
            assert _parse(on[name].decode()).mailto == [f"mailto:{ADDRESS}"], name
        elif name not in ("data/site.json", "version.json") and (
            name == "sitemap.xml" or name.endswith((".ics", ".json"))
        ):
            # (data/site.json and version.json hold the build time.) Feeds, data and the sitemap never change (sitemap lastmod is untouched too).
            assert on[name] == off[name], name


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "no-at-sign",
        "a@b",
        "two@@example.org",
        'x"onmouseover="y@example.org',
        "a b@example.org",
        "a@example.org?subject=x",
    ],
)
def test_a_value_that_is_not_a_plain_address_stops_the_build(monkeypatch, bad):
    monkeypatch.setattr(site, "REMOVAL_CONTACT_EMAIL", bad)
    with pytest.raises(ValueError, match="REMOVAL_CONTACT_EMAIL"):
        site._footer(analytics_on=False)


# Negative controls: each applies a sabotage, asserts the sabotage took
# effect, and shows the real assertion above would catch it.


def test_control_a_footer_that_drops_the_paragraph_is_caught(monkeypatch):
    monkeypatch.setattr(site, "_removal_contact", lambda: "")
    sabotaged = site._footer(analytics_on=False)
    assert site.REMOVAL_CONTACT_EMAIL == ADDRESS and "mailto" not in sabotaged  # sabotage applied
    assert _parse(sabotaged).mailto != [f"mailto:{ADDRESS}"]


def test_control_a_stale_golden_is_caught():
    golden = (GOLDEN / "footer_removal_off_no_analytics.html").read_text(encoding="utf-8")
    stale = golden.replace("Accessibility statement", "Accessibility statements", 1)
    assert stale != golden  # sabotage applied
    assert site._footer(analytics_on=False) != stale


def test_control_a_loosened_address_check_is_caught(monkeypatch):
    monkeypatch.setattr(site, "_EMAIL_SHAPE", re.compile(r".*"))
    monkeypatch.setattr(site, "REMOVAL_CONTACT_EMAIL", 'x"onmouseover="y@example.org')
    assert site._EMAIL_SHAPE.pattern == ".*"  # sabotage applied
    out = site._footer(analytics_on=False)  # no longer raises ...
    assert 'mailto:x"onmouseover' not in out  # ... and e() still escapes the quote
    assert "&quot;" in out  # the escape is the second line of defense, the check the first
