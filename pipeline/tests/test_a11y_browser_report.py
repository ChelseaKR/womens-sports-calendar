"""scripts/check_a11y_browser_report.py must refuse a report that checked less
than it claims, including a page whose dark color scheme was never checked
(style.css swaps every content color under prefers-color-scheme: dark, so a
light-only axe pass says nothing about contrast there; WCAG 1.4.3 / 1.4.11)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_a11y_browser_report.py"
URL = "http://127.0.0.1:8917/index.html"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_a11y_browser_report", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


report_check = _load()


def _result(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "url": URL,
        "axeRulesRun": 60,
        "axeDarkRulesRun": 60,
        "tabStops": 12,
        "tabbable": 12,
        "problems": [],
    }
    result.update(overrides)
    return result


def test_a_complete_passing_report_is_accepted() -> None:
    assert report_check.problems_in({"results": [_result()]}, [URL]) == []


def test_a_page_never_checked_in_the_dark_color_scheme_is_refused() -> None:
    without_dark = _result()
    del without_dark["axeDarkRulesRun"]
    problems = report_check.problems_in({"results": [without_dark]}, [URL])
    assert problems == [f"{URL}: axe ran no rules in the dark color scheme"]


def test_a_dark_pass_that_ran_nothing_is_refused() -> None:
    problems = report_check.problems_in({"results": [_result(axeDarkRulesRun=0)]}, [URL])
    assert problems == [f"{URL}: axe ran no rules in the dark color scheme"]


def test_a_reported_problem_fails_the_report() -> None:
    problem = "axe dark serious color-contrast: Elements must meet minimum color contrast ratio thresholds (p)"
    problems = report_check.problems_in({"results": [_result(problems=[problem])]}, [URL])
    assert problems == [f"{URL}: {problem}"]
