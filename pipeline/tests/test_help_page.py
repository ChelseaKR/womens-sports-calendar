"""The calendar help page, /help/ (DECISIONS 0036): subscribe and unsubscribe
steps per calendar app, how often feeds update, why a game can be missing.

Every claim the page makes about this site is tied here to the code that
makes it true (the feed's refresh request, the nightly build time, the
seller table, the feed addresses), so a change there fails a test instead
of leaving the help page quietly wrong.
"""

from __future__ import annotations

import html as html_lib
import importlib.util
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from wsc_pipeline import config, ics, sellers, site

from .fixture_site import BASE_URL, build_fixture_site

PIPELINE = Path(__file__).resolve().parents[1]
REPO = PIPELINE.parent


def _main_text(html: str) -> str:
    main = html.split('<main id="main">', 1)[1].split("</main>", 1)[0]
    return " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", main)).split())


@pytest.fixture(scope="module")
def dist(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("help") / "dist"
    build_fixture_site(out, now=datetime(2026, 9, 18, 8, 30, tzinfo=UTC))
    return out


def test_the_page_has_its_own_title_h1_description_and_canonical() -> None:
    html = site.render_help(base_url=BASE_URL)
    assert "<title>Calendar help: subscribe and unsubscribe | Next Home Game</title>" in html
    assert html.count("<h1>") == 1 and "<h1>Calendar help</h1>" in html
    assert '<meta name="description" content="How to add a team&#x27;s games to Apple Calendar' in html
    assert f'<link rel="canonical" href="{BASE_URL}/help/">' in html
    assert f"Updated {site.display_date(site.HELP_UPDATED)}." in _main_text(html)


def test_each_app_has_subscribe_and_unsubscribe_steps_with_its_source() -> None:
    html = site.render_help(base_url=BASE_URL)
    text = _main_text(html)
    for want in (
        "Add Subscription Calendar",  # iPhone and iPad
        "File \u203a New Calendar Subscription",  # Mac
        "From URL",  # Google
        "Subscribe from web",  # Outlook
        "tap Unsubscribe",
        "Edit \u203a Delete",
        "Remove calendar, then Unsubscribe",
        "More options next to the calendar, then Remove",
    ):
        assert want in text, want
    for url in site.HELP_SOURCES.values():
        assert f'href="{url}"' in html, url
        assert url.startswith(
            ("https://support.apple.com/", "https://support.google.com/", "https://support.microsoft.com/")
        )


def test_refresh_claims_match_the_feed_and_the_build() -> None:
    text = _main_text(site.render_help(base_url=BASE_URL))
    # "Each feed asks calendar apps to check it again once a day."
    assert timedelta(days=1) == ics.REFRESH_INTERVAL
    assert "check it again once a day" in text
    # "rebuilds every feed once a night, shortly after midnight Pacific time":
    # 08:13 UTC is 00:13 PST or 01:13 PDT.
    pages_yml = (REPO / ".github" / "workflows" / "pages.yml").read_text()
    assert '- cron: "13 8 * * *"' in pages_yml
    assert "shortly after midnight Pacific time" in text
    # Only documented figures are given; the rest say the app does not publish one.
    assert "about every 3 hours" in text and "about every 6 hours" in text
    assert text.count("does not publish how often") == 2


def test_the_sellers_named_as_a_reason_are_in_the_seller_table() -> None:
    text = _main_text(site.render_help(base_url=BASE_URL))
    in_table = {s.name for s in sellers.PRIMARY_SELLERS.values()}
    for name in site.HELP_NAMED_SELLERS:
        assert name in in_table, name
        assert name in text, name
    assert sellers.PRIMARY_SELLERS[site.HELP_ACCOUNT_MANAGER_TEAM].name == "Ticketmaster Account Manager"
    assert f"{site.HELP_ACCOUNT_MANAGER_NAME}, which sells through its own Ticketmaster Account Manager store" in text
    assert "Ticketmaster’s public listings" in text


def test_the_page_links_no_seller_and_keeps_the_affiliate_disclosure() -> None:
    for paid in (False, True):
        html = site.render_help(base_url=BASE_URL, paid_links=paid)
        main = html.split('<main id="main">', 1)[1].split("</main>", 1)[0]
        assert "sponsored" not in main and site.PAID_LINK_TEXT not in main
        footer = html.split('<footer class="site-footer">', 1)[1]
        note = site.AFFILIATE_NOTE_ACTIVE if paid else site.AFFILIATE_NOTE_INACTIVE
        assert note in footer


def test_the_example_addresses_are_feeds_the_build_writes(dist: Path) -> None:
    html = (dist / "help" / "index.html").read_text(encoding="utf-8")
    addresses = re.findall(r"<code>(https://[^<]+\.ics)</code>", html)
    assert len(addresses) == 3
    for address in addresses:
        assert address.startswith(BASE_URL + "/")
        assert (dist / address[len(BASE_URL) + 1 :]).is_file(), address


def test_every_page_links_the_help_page_and_the_sitemap_lists_it(dist: Path) -> None:
    pages = [p for p in dist.rglob("*.html") if 'http-equiv="refresh"' not in p.read_text(encoding="utf-8")]
    assert len(pages) > 40
    for page in pages:
        html = page.read_text(encoding="utf-8")
        assert html.count(f'href="{site.HELP_PATH}"') >= 2, page  # header and footer
    assert f"<loc>{BASE_URL}/help/</loc>" in (dist / "sitemap.xml").read_text(encoding="utf-8")
    team = (dist / "wnba" / "seattle-storm" / "index.html").read_text(encoding="utf-8")
    other_apps = team.split('<section class="other-apps"', 1)[1].split("</section>", 1)[0]
    assert f'href="{site.HELP_PATH}"' in other_apps


def test_control_without_the_header_and_footer_links_a_page_does_not_link_help(dist: Path) -> None:
    html = (dist / "privacy" / "index.html").read_text(encoding="utf-8")
    stripped = html.replace(site.SITE_NAV, "").replace(f'<a href="{site.HELP_PATH}">Calendar help</a> &middot; ', "")
    assert stripped != html
    assert f'href="{site.HELP_PATH}"' not in stripped


def test_the_a11y_gate_must_see_the_help_page() -> None:
    # Loaded by path, the way tests/test_check_markers.py loads its script;
    # the script puts the pipeline root on sys.path for its own imports.
    spec = importlib.util.spec_from_file_location(
        "check_a11y_coverage", PIPELINE / "scripts" / "check_a11y_coverage.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert "help/index.html" in module.expected_paths()


def test_example_team_is_a_tracked_team() -> None:
    league = config.LEAGUES[0]
    html = site.render_help(base_url=BASE_URL)
    assert f"{BASE_URL}/ics/{league.slug}/{league.teams[0].slug}.ics" in html
