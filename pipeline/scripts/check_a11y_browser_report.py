"""Refuse a green browser-level a11y gate that checked less than it claims.

scripts/a11y_browser_checks.mjs writes a JSON report. This asserts that the
report covers exactly the URLs it was handed, that every page ran a non-zero
number of axe rules and walked a non-zero number of tab stops (a page that
failed to load, or whose checks examined nothing, is not a pass), and that no
page reported a problem. The URL list itself is checked against the pages the
site config requires by scripts/check_a11y_coverage.py, in the same `make
a11y` run.

Usage: check_a11y_browser_report.py <a11y-browser-results.json> <url> [<url> ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def problems_in(report: dict[str, object], urls: list[str]) -> list[str]:
    results = report.get("results")
    if not isinstance(results, list):
        return ["report has no results list"]
    problems: list[str] = []
    reported = {str(r.get("url")) for r in results if isinstance(r, dict)}
    handed = set(urls)
    if reported != handed:
        problems.append(
            f"report covers {len(reported)} URL(s) but {len(handed)} were handed; "
            f"missing {sorted(handed - reported)[:5]}, extra {sorted(reported - handed)[:5]}"
        )
    for r in results:
        if not isinstance(r, dict):
            problems.append("malformed result entry")
            continue
        url = r.get("url")
        if not r.get("axeRulesRun"):
            problems.append(f"{url}: axe ran no rules")
        if not r.get("tabStops"):
            problems.append(f"{url}: no tab stops were walked")
        problems.extend(f"{url}: {p}" for p in r.get("problems") or [])
    return problems


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    report = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    problems = problems_in(report, argv[1:])
    if problems:
        print("a11y browser report check FAILED:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(f"a11y browser report check: all {len(argv) - 1} pages checked and passing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
