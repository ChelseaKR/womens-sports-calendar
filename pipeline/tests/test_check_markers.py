"""scripts/check_markers.py must be able to fail: each planted violation below
is asserted to be present in the file before the check runs, so a sabotage
that silently did not land cannot read as a pass."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_markers.py"

# Assembled from halves so this test file does not trip the check itself.
WIP = "TO" + "DO"
NOQA = "no" + "qa"
TYPE_IGNORE = "type: " + "ignore"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_markers", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_markers = _load()


def _plant(tmp_path: Path, line: str) -> Path:
    path = tmp_path / "planted.py"
    path.write_text(f"x = 1\n{line}\n", encoding="utf-8")
    assert line in path.read_text(encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    "line",
    [
        f"# {WIP}: tidy this later",
        f"import os  # {NOQA}",
        f"import os  # {NOQA}: F401",
        f"y: int = 'a'  # {TYPE_IGNORE}",
        f"y: int = 'a'  # {TYPE_IGNORE}[assignment]",
    ],
)
def test_unreferenced_marker_or_suppression_fails(tmp_path: Path, line: str) -> None:
    assert check_markers.main([str(_plant(tmp_path, line))]) == 1


@pytest.mark.parametrize(
    "line",
    [
        f"# {WIP}(#12): tidy this later",
        f"# {WIP} https://github.com/o/r/issues/12 tidy this later",
        f"import os  # {NOQA}: F401 (#12)",
        f"y: int = 'a'  # {TYPE_IGNORE}[assignment]  # see #12",
    ],
)
def test_referenced_marker_or_coded_suppression_passes(tmp_path: Path, line: str) -> None:
    assert check_markers.main([str(_plant(tmp_path, line))]) == 0


def test_an_html_entity_is_not_an_issue_reference(tmp_path: Path) -> None:
    line = f"# {WIP}: fix the &#8217; quote"
    assert check_markers.main([str(_plant(tmp_path, line))]) == 1


def test_a_run_that_found_nothing_to_read_is_not_a_pass(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text(f"{WIP}\n", encoding="utf-8")
    assert check_markers.main([str(tmp_path)]) == 2


def test_the_repository_itself_is_clean() -> None:
    root = SCRIPT.parents[1]
    assert check_markers.main([str(root / "src"), str(root / "tests"), str(root / "scripts")]) == 0
