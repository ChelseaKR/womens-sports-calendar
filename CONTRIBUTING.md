# Contributing

This is a private, single-maintainer repository. Changes arrive as pull
requests against `main`; nothing is pushed to `main` directly.

## Set up

- [uv](https://docs.astral.sh/uv/) 0.11 or newer (it fetches Python 3.12 from
  `pipeline/.python-version`).
- Node 22 for the accessibility and performance checks (puppeteer
  downloads its own Chrome on first install).
- Once per clone, install the hooks:

  ```sh
  pre-commit install && pre-commit install --hook-type pre-push
  ```

  gitleaks, ruff and ruff-format run on commit, and mypy runs on push
  (`.pre-commit-config.yaml`).

## The one local gate: `make verify`

```sh
make verify
```

It runs every check CI runs, in the same order, from the repository root:
the lockfile drift check, ruff, ruff format, mypy --strict, the
marker check, the tests with an 85% branch-coverage floor, a wheel build, a
degraded build of the site, HTML validation, `.ics` validation, the
accessibility sweep over every page, and pip-audit. CI runs exactly this
target (`.github/workflows/ci.yml`). If `make verify` is green locally, the
`verify` check should be green too. The security scans (gitleaks, Semgrep,
OSV-Scanner) run in `.github/workflows/security.yml`.

A build without `TICKETMASTER_API_KEY` fetches nothing, and its pages say
so. That's the mode CI uses. Never paste a key into a file; use the
environment.

## Pull requests

- One concern per PR. Stage files by name; never `git add -A` or `git add .`.
- Commit subjects are lowercase conventional commits (`fix(site): ...`,
  `feat(data): ...`).
- Fill in the PR template's Definition of Done checklist
  (`DEFINITION_OF_DONE.md`).
- A change to a guardrail needs an ADR in `docs/adr/`. The guardrails are:
  a failed or empty fetch never publishes; absence is never shown as a
  value; a `permissions:` block; a coverage, accessibility or performance
  threshold. Declaring a standard N/A needs one too.
- Add a line to `CHANGELOG.md` under Unreleased for any user-visible change.
- New data sources follow "licence before bytes" (`docs/DECISIONS.md` 0003):
  the terms are read and quoted in `docs/LICENSES-AND-ATTRIBUTION.md`, and a
  data card is added in `docs/data/`, before anything is fetched.

## Standards

The portfolio standards are vendored, unedited, at `docs/standards/`
(v2.0.0; `.standards-version`). Renovate proposes upgrades. Never
hand-edit them. The README's Standards Conformance table says which
standards apply, and links the open issue for each gap.
