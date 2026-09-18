"""Write the populated fixture site (tests/fixture_site.py) to
dist-fixture/, for `make validate-fixture-site`.

`make verify`'s own build has no Ticketmaster key, so every page it writes
is the degraded, no-games shape. This site goes through the same build with
canned listings -- home and away games, a cancelled game, time-TBA and
date-TBD games, a package listing, a two-tracked-team game, a Canadian
venue -- and a previous lastmod manifest, so the HTML validator, the feed
validator and the structured-data validator each see populated output.

Usage: python scripts/build_fixture_site.py [out-dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PIPELINE_ROOT))

from tests.fixture_site import build_fixture_site_with_history
from wsc_pipeline import analytics


def main(argv: list[str]) -> int:
    out_dir = Path(argv[0]) if argv else PIPELINE_ROOT / "dist-fixture"
    # Built twice (tests/fixture_site.py): the second build compares against
    # the first's manifest, so the sitemap carries a lastmod carried over,
    # one set by a change, one set by a new page, and unknown ones omitted.
    build_fixture_site_with_history(out_dir, ga4_id=analytics.GA4_MEASUREMENT_ID or None)
    print(f"wrote the fixture site to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
