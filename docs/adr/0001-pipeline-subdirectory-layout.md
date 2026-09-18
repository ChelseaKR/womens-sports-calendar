# 0001. The Python project lives in `pipeline/`, verified from the root

Status: Accepted
Date: 2026-09-17
Deciders: Chelsea Kelly-Reif

## Context

CODE-QUALITY-STANDARD §4 expects one root `pyproject.toml`, `tests/` at the
repository root, and forbids monorepo-style nesting unless an ADR declares
it (CQ-24, CQ-25, CQ-26). CI-CD-STANDARD §9 allows a nested project to
"expose a root Makefile that delegates to the package, or hoist its
configuration and lockfile", and SECURITY-AND-SUPPLY-CHAIN-STANDARD §8 asks
a nested project to expose repository-root verification so portfolio
tooling cannot silently skip it.

Here the whole product -- fetch, normalize, `.ics` and HTML generation --
is one Python package under `pipeline/`, with its `pyproject.toml`,
`uv.lock`, `.python-version`, `tests/`, `scripts/`, the pa11y tooling
(`package.json`) and the static assets beside it. `site/` holds only a
README explaining that the generator lives in the pipeline (`site/README.md`).
Both workflows run with `working-directory: pipeline`, and the build
resolves its assets relative to the package.

## Decision

Keep the project in `pipeline/`, and make the repository root delegate to
it:

- the root `Makefile`'s `verify` runs `make -C pipeline verify`, the same
  target CI runs, so `make verify` from a fresh clone is the full gate;
- all Python tool configuration (ruff, mypy, pytest, coverage) stays in the
  single `pipeline/pyproject.toml`; there is no second config anywhere;
- the root `.pre-commit-config.yaml` runs the hooks against `pipeline/`
  using the locked tool versions.

Hoisting `pipeline/` to the root was considered and not done now: it moves
every source, test, asset and workflow path in one change while other work
is in flight, for no behavioural gain.

## Consequences

- Every gate the standards require runs from the root; nothing is skipped.
- `automation/conformance_check.py` reads only repository-root files. It
  reports `tests_directory` as failing (there is no root `tests/`) and does
  not score the Python floors (`requires-python`, ruff/mypy floors,
  coverage floor, lockfile, `.python-version`) at all, because it finds no
  root `pyproject.toml`. Those controls are met in `pipeline/`; the checker
  cannot see them. This is a known measurement gap, not a pass.
- If `site/` ever becomes a real second project, or the checker's blind spot
  starts to cost more than a move would, supersede this ADR with one that
  hoists `pipeline/` to the root.
