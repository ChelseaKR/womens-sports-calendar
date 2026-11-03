"""The published terms of use page."""

from __future__ import annotations

import re

from wsc_pipeline import site


def _text(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def test_the_page_names_the_operator_the_source_and_the_law() -> None:
    html = site.render_terms(base_url="https://nexthomegame.com")
    text = _text(html.split('<main id="main">', 1)[1].split("</main>", 1)[0])
    for want in (
        "Chelsea Kelly-Reif",
        "chelsea@chelseakr.com",
        "Ticketmaster Discovery API",
        "not affiliated with or endorsed by any league, team, school, Ticketmaster",
        "can be wrong or late",
        "laws of the State of California",
        f"Updated {site.display_date(site.TERMS_UPDATED)}.",
    ):
        assert want in text, want
    assert len(text.split()) < 700
    assert '<link rel="canonical" href="https://nexthomegame.com/terms/">' in html


def test_the_affiliate_paragraph_follows_the_paid_link_switch() -> None:
    plain = _text(site.render_terms(base_url="https://nexthomegame.com"))
    assert "Today no link on this site earns it money." in plain
    assert "earns a commission" not in plain
    paid = _text(site.render_terms(base_url="https://nexthomegame.com", paid_links=True))
    assert "earns a commission" in paid
    assert "Today no link on this site earns it money." not in paid


def test_every_page_footer_links_the_terms() -> None:
    for html in (
        site.render_privacy(base_url="https://nexthomegame.com"),
        site.render_accessibility(base_url="https://nexthomegame.com"),
        site.render_terms(base_url="https://nexthomegame.com"),
    ):
        assert re.search(rf'<footer[^>]*>.*href="{re.escape(site.TERMS_PATH)}"', html, re.DOTALL)
