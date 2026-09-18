"""The published accessibility statement (ACCESSIBILITY-STANDARD A11Y-16)."""

from __future__ import annotations

import re
from pathlib import Path

from wsc_pipeline import site

STATEMENT = Path(__file__).resolve().parents[2] / "docs" / "a11y" / "STATEMENT.md"


def test_the_page_and_the_committed_statement_state_the_same_status() -> None:
    committed = " ".join(STATEMENT.read_text(encoding="utf-8").split())
    assert f"**Accessibility status: {site.ACCESSIBILITY_STATUS}**" in committed


def test_the_page_states_status_gaps_and_a_reporting_channel_without_claiming_conformance() -> None:
    html = site.render_accessibility(base_url="https://nexthomegame.com")
    assert site.ACCESSIBILITY_STATUS in html
    assert f'href="{site.ACCESSIBILITY_CONTACT_URL}"' in html
    assert "screen reader" in html
    for claim in ("WCAG compliant", "WCAG conformant", "fully accessible", "screen-reader tested"):
        assert claim.lower() not in html.lower(), claim
    assert '<link rel="canonical" href="https://nexthomegame.com/accessibility/">' in html


def test_every_page_footer_links_the_statement() -> None:
    html = site.render_privacy(base_url="https://nexthomegame.com")
    assert re.search(rf'<footer[^>]*>.*href="{re.escape(site.ACCESSIBILITY_PATH)}"', html, re.DOTALL)
