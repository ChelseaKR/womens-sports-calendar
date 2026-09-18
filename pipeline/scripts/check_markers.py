"""Fail on work-in-progress markers and inline suppressions that name no issue.

CODE-QUALITY-STANDARD CQ-34: every to-do / fix-me / hack marker carries an
issue reference on the same line -- ``(#142)`` or a full
``https://github.com/<owner>/<repo>/issues/<n>`` URL.

CQ-35: every inline lint or type suppression (a ruff/flake8 no-QA comment, a
mypy ignore comment, an ESLint disable comment) carries a specific code *and*
an issue reference. A whole-file exception belongs in pyproject.toml's
``[tool.ruff.lint.per-file-ignores]``, with a written reason, where review
sees it.

Scans ``*.py``, ``*.js`` and ``*.mjs`` files under the given paths and exits
1 listing every offending line, 0 when there are none. A run that found no
files to read exits 2: a check that examined nothing has not passed.

The marker words are assembled from halves below so that this file does not
match its own patterns.

Usage: check_markers.py <path> [<path> ...]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SUFFIXES = (".py", ".js", ".mjs")
SKIP_DIRS = {".venv", "node_modules", "__pycache__", ".pytest_cache", "dist"}

_MARKER_WORDS = ("TO" + "DO", "FIX" + "ME", "HA" + "CK")
_NOQA = "no" + "qa"
_TYPE_IGNORE = "type:" + r"\s*" + "ignore"
_ESLINT_DISABLE = "eslint-" + "disable"

MARKER = re.compile(r"\b(" + "|".join(_MARKER_WORDS) + r")\b")
SUPPRESSION = re.compile(r"#\s*" + _NOQA + r"\b|#\s*" + _TYPE_IGNORE + r"\b|" + _ESLINT_DISABLE)
# The specific code after a suppression: ruff `: E402`, mypy `[arg-type]`,
# ESLint `-next-line no-console`.
SUPPRESSION_CODE = re.compile(
    r"#\s*" + _NOQA + r":\s*[A-Z]+\d+"
    r"|#\s*" + _TYPE_IGNORE + r"\[[\w-]+"
    r"|" + _ESLINT_DISABLE + r"(?:-next-line|-line)?\s+[\w@/-]+"
)
ISSUE_REF = re.compile(r"\(#\d+\)|(?<![\w&])#\d+\b|https?://\S+/issues/\d+")


def violations(path: Path) -> list[str]:
    """Every offending line in one file, as ``path:line: reason: text``."""
    found = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        has_issue = ISSUE_REF.search(line) is not None
        if MARKER.search(line) and not has_issue:
            found.append(f"{path}:{lineno}: marker without an issue reference: {line.strip()}")
        if SUPPRESSION.search(line):
            if SUPPRESSION_CODE.search(line) is None:
                found.append(f"{path}:{lineno}: suppression without a specific code: {line.strip()}")
            elif not has_issue:
                found.append(f"{path}:{lineno}: suppression without an issue reference: {line.strip()}")
    return found


def iter_files(roots: list[Path]) -> list[Path]:
    """Source files under each root (or the root itself if it is a file)."""
    files = []
    for root in roots:
        candidates = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in candidates:
            if path.suffix in SUFFIXES and path.is_file() and not SKIP_DIRS.intersection(path.parts):
                files.append(path)
    return files


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    roots = [Path(a) for a in argv]
    missing = [str(r) for r in roots if not r.exists()]
    if missing:
        print(f"check_markers: no such path: {missing}", file=sys.stderr)
        return 2
    files = iter_files(roots)
    if not files:
        print(f"check_markers: no {'/'.join(SUFFIXES)} files under {argv}; nothing was checked", file=sys.stderr)
        return 2
    problems = [v for f in files for v in violations(f)]
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"check_markers: {len(problems)} problem(s) in {len(files)} files (CQ-34/CQ-35)", file=sys.stderr)
        return 1
    print(f"check_markers: {len(files)} files, no bare markers or unreferenced suppressions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
