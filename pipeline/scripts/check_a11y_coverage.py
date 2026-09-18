"""Refuse a green a11y gate that checked fewer pages than the site has.

`make a11y` hands pa11y-ci one URL per HTML file in dist/, and pa11y-ci
writes its own report (pa11y-ci-results.json, via the json reporter in
pa11y-ci.config.json). This script then asserts three things, and exits
non-zero if any fails:

1. pa11y-ci's report names exactly the URLs it was handed -- no page
   skipped, none it invented -- and says every one of them passed
   (total == passes == number of URLs, errors == 0).
2. The URL list covers every page the site config says a build must
   produce: the index, one page per tracked league, one per tracked team
   (wsc_pipeline.config.LEAGUES), plus the populated-games-table fixtures
   from scripts/render_a11y_fixtures.py. A build that silently produced
   fewer pages would otherwise hand pa11y-ci a shorter list and pass.
3. Pages beyond that set (a future 404 page, say) are allowed -- they are
   checked like any other -- but never counted in place of a missing one.

Usage: check_a11y_coverage.py <pa11y-ci-results.json> <url> [<url> ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

PIPELINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PIPELINE_ROOT / "src"))
sys.path.insert(0, str(PIPELINE_ROOT))

from wsc_pipeline.config import LEAGUES  # noqa: E402
from scripts.render_a11y_fixtures import FIXTURE_PAGES  # noqa: E402


def expected_paths() -> set[str]:
    paths = {"index.html"}
    for league in LEAGUES:
        paths.add(f"{league.slug}/index.html")
        for team in league.teams:
            paths.add(f"{league.slug}/{team.slug}/index.html")
    for name in FIXTURE_PAGES:
        paths.add(f"_a11y-fixtures/{name}.html")
    return paths


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    report_path, urls = Path(argv[0]), argv[1:]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    problems: list[str] = []

    checked = set(report.get("results", {}))
    handed = set(urls)
    if len(handed) != len(urls):
        problems.append("the URL list handed to pa11y-ci contains duplicates")
    if checked != handed:
        missing = sorted(handed - checked)
        extra = sorted(checked - handed)
        if missing:
            problems.append(f"pa11y-ci did not report on {len(missing)} URL(s): {missing[:5]}")
        if extra:
            problems.append(f"pa11y-ci reported on URL(s) it was not handed: {extra[:5]}")
    total, passes, errors = report.get("total"), report.get("passes"), report.get("errors")
    if not (total == passes == len(urls)) or errors != 0:
        problems.append(
            f"pa11y-ci totals do not show every page passing: total={total} "
            f"passes={passes} errors={errors} urls={len(urls)}"
        )

    handed_paths = {urlparse(u).path.lstrip("/") for u in urls}
    required = expected_paths()
    not_handed = sorted(required - handed_paths)
    if not_handed:
        problems.append(
            f"{len(not_handed)} page(s) the site config requires were never handed "
            f"to pa11y-ci (missing from dist/?): {not_handed[:5]}"
        )

    if problems:
        print("a11y coverage check FAILED:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(
        f"a11y coverage check: pa11y-ci examined {len(checked)}/{len(urls)} pages, "
        f"all passing; covers all {len(required)} pages the site config requires "
        f"(+{len(handed_paths - required)} extra)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
