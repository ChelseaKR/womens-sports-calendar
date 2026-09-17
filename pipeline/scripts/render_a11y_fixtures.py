"""Render the populated-games-table fixture pages (a priced game, an
unpriced game, and a date-TBD game together) that a degraded, no-API-key
build never produces -- CI has no TICKETMASTER_API_KEY (by design, see
.github/workflows/ci.yml), so dist/ is always an empty-games build there,
and pa11y checking only dist/ would never exercise a real <table
class="games-table"> row.

Reuses tests/test_site_html.py::_pages() directly, so there is exactly one
definition of this fixture shape -- shared with the HTML-content assertions
in that file -- rather than a second, driftable copy here.

Written *inside* dist/ (at dist/_a11y-fixtures/), not a sibling top-level
directory: every page here links style.css and favicon/fonts with a
root-absolute path ("/style.css"), which only resolves when the page is
served from an HTTP root that also holds those files -- nesting the
fixtures under dist/ means they share dist/style.css and dist/fonts/ for
free once `make a11y` serves dist/ as that root. A sibling directory has no
style.css or fonts next to it at all, so pa11y would silently check
unstyled, default-browser-styled markup -- real contrast never exercised.
"""

from __future__ import annotations

import sys
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PIPELINE_ROOT))

from tests.test_site_html import _pages  # noqa: E402

OUT_DIR = PIPELINE_ROOT / "dist" / "_a11y-fixtures"

# Only league/team pages have a games table; index just links to leagues.
FIXTURE_PAGES = ("league", "team")


def main() -> None:
    pages = _pages()
    OUT_DIR.mkdir(exist_ok=True)
    for name in FIXTURE_PAGES:
        out_path = OUT_DIR / f"{name}.html"
        out_path.write_text(pages[name], encoding="utf-8")
        print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
