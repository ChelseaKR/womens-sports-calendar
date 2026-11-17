"""The about page, /about/ (DECISIONS 0043): what the site does, where its
games come from, who makes it, how it earns, and how to reach her.

Each statement is tied here to the code or the page that already makes it
true (the league registry, the footer's source links, the independence line,
the terms page's affiliate switch, the GA4 ID, the removal address), so the
page cannot drift into claiming more than the build does.
"""

from __future__ import annotations

import html as html_lib
import importlib.util
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from wsc_pipeline import config, feeds, site

from .fixture_site import BASE_URL, build_fixture_site

PIPELINE = Path(__file__).resolve().parents[1]
GA4_ID = "G-TEST12345"


def _main(html: str) -> str:
    return html.split('<main id="main">', 1)[1].split("</main>", 1)[0]


def _text(fragment: str) -> str:
    return " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


@pytest.fixture(scope="module")
def dist(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("about") / "dist"
    build_fixture_site(out, now=datetime(2026, 9, 18, 8, 30, tzinfo=UTC))
    return out


def test_the_page_has_its_own_title_h1_description_and_canonical() -> None:
    html = site.render_about(base_url=BASE_URL)
    assert "<title>About | Next Home Game</title>" in html
    assert html.count("<h1>") == 1 and "<h1>About Next Home Game</h1>" in html
    assert (
        '<meta name="description" content="Who makes Next Home Game, where its game listings come from, which leagues it covers'
        in html
    )
    assert f'<link rel="canonical" href="{BASE_URL}/about/">' in html
    assert f"Updated {site.display_date(site.ABOUT_UPDATED)}." in _text(_main(html))


def test_it_lists_every_tracked_league_with_its_team_count() -> None:
    main = _main(site.render_about(base_url=BASE_URL))
    items = re.findall(r'<li><a href="/([^/"]+)/">([^<]+)</a>: (\d+) teams</li>', main)
    assert [(slug, html_lib.unescape(name), int(n)) for slug, name, n in items] == [
        (lg.slug, lg.name, len(lg.teams)) for lg in config.LEAGUES
    ]
    total = sum(len(lg.teams) for lg in config.LEAGUES)
    assert f"{total} teams in {len(config.LEAGUES)} leagues." in _text(main)


def test_it_credits_the_source_exactly_as_the_footer_does() -> None:
    html = site.render_about(base_url=BASE_URL)
    main, footer = _main(html), html.split('<footer class="site-footer">', 1)[1]
    for link in (
        'href="https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/">Ticketmaster Discovery API</a>',
        'href="https://developer.ticketmaster.com/support/terms-of-use/">Terms of Use</a>',
    ):
        assert link in main and link in footer, link
    text = _text(main)
    assert "No league’s own schedule is used on this site" in text
    assert "does not show ticket prices" in text
    assert feeds.INDEPENDENCE_LINE in text


def test_it_names_the_same_one_person_the_terms_page_does() -> None:
    about = _text(_main(site.render_about(base_url=BASE_URL)))
    terms = _text(_main(site.render_terms(base_url=BASE_URL)))
    assert f"made by one person, {site.OPERATOR_NAME}." in about
    assert f"run by one person, {site.OPERATOR_NAME}," in terms


def test_the_earning_paragraph_follows_the_terms_page_switch() -> None:
    plain = _text(_main(site.render_about(base_url=BASE_URL)))
    assert _text(site.TERMS_AFFILIATE_INACTIVE) in plain
    assert "earns a commission" not in plain
    paid = _text(_main(site.render_about(base_url=BASE_URL, paid_links=True)))
    assert _text(site.TERMS_AFFILIATE_ACTIVE) in paid
    assert _text(site.TERMS_AFFILIATE_INACTIVE) not in paid


def test_the_analytics_sentence_appears_only_with_an_analytics_id() -> None:
    sentence = "The web pages use Google Analytics to count visits and clicks."
    with_id = _text(_main(site.render_about(base_url=BASE_URL, ga4_id=GA4_ID)))
    without = _text(_main(site.render_about(base_url=BASE_URL)))
    assert sentence in with_id and sentence not in without
    for text in (with_id, without):
        assert "privacy page says what this site measures and how to opt out" in text


@pytest.mark.parametrize("ga4_id", [None, GA4_ID])
@pytest.mark.parametrize("paid", [False, True])
def test_it_never_claims_the_site_is_untracked(ga4_id: str | None, paid: bool) -> None:
    text = _text(_main(site.render_about(base_url=BASE_URL, ga4_id=ga4_id, paid_links=paid))).lower()
    for phrase in ("no tracking", "not tracked", "untracked", "tracking-free", "no analytics", "no cookies"):
        assert phrase not in text, phrase


def test_control_the_untracked_check_can_fail() -> None:
    text = _text("<p>This site has no tracking.</p>").lower()
    assert "no tracking" in text


def test_the_contact_is_the_address_the_footer_already_publishes() -> None:
    main = _main(site.render_about(base_url=BASE_URL))
    assert site.REMOVAL_CONTACT_EMAIL is not None
    assert f'href="mailto:{site.REMOVAL_CONTACT_EMAIL}"' in main


def test_with_the_footer_address_unset_the_page_keeps_the_terms_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(site, "REMOVAL_CONTACT_EMAIL", None)
    main = _main(site.render_about(base_url=BASE_URL))
    terms = _main(site.render_terms(base_url=BASE_URL))
    assert 'href="mailto:chelsea@chelseakr.com"' in main and 'href="mailto:chelsea@chelseakr.com"' in terms


def test_it_publishes_no_postal_address() -> None:
    # The site publishes an email address and nothing more: no street, no
    # postcode (the owner's rule; see DECISIONS 0043).
    text = _text(_main(site.render_about(base_url=BASE_URL)))
    street = re.compile(r"\b\d{1,6}\s+\w+(\s+\w+)?\s+(St|Street|Ave|Avenue|Rd|Road|Blvd|Dr|Drive|Ln|Lane|Way)\b")
    assert not street.search(text)
    assert not re.search(r"\b\d{5}(-\d{4})?\b", text)
    assert street.search("Write to 123 Main Street")  # control: the pattern matches a street


def test_every_page_footer_links_the_about_page_and_the_sitemap_lists_it(dist: Path) -> None:
    pages = [p for p in dist.rglob("*.html") if 'http-equiv="refresh"' not in p.read_text(encoding="utf-8")]
    assert len(pages) > 40
    for page in pages:
        footer = page.read_text(encoding="utf-8").split('<footer class="site-footer">', 1)[1]
        assert f'<a href="{site.ABOUT_PATH}">About</a>' in footer, page
    assert (dist / "about" / "index.html").is_file()
    assert f"<loc>{BASE_URL}/about/</loc>" in (dist / "sitemap.xml").read_text(encoding="utf-8")
    assert f"{BASE_URL}/about/" in (dist / "llms.txt").read_text(encoding="utf-8")


def test_control_without_the_footer_link_a_page_does_not_link_about(dist: Path) -> None:
    html = (dist / "privacy" / "index.html").read_text(encoding="utf-8")
    stripped = html.replace(f'<a href="{site.ABOUT_PATH}">About</a> &middot; ', "")
    assert stripped != html
    assert f'href="{site.ABOUT_PATH}"' not in stripped


def test_the_a11y_gate_must_see_the_about_page() -> None:
    spec = importlib.util.spec_from_file_location(
        "check_a11y_coverage", PIPELINE / "scripts" / "check_a11y_coverage.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert "about/index.html" in module.expected_paths()
