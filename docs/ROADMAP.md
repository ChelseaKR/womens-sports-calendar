# Roadmap and metrics ledger

The product plan lives in [moved to private strategy notes] and the decision
logs (`docs/DECISIONS.md`, `docs/adr/`). Open work is tracked as issues.
This file holds the per-repo **Metrics ledger** the standards ask for: each
gate with this repository's value, how it's measured, and whether it
blocks. The standards themselves (vendored in `docs/standards/`) own the
thresholds. Only this repository's values are recorded here.

## CI stages (CI-CD-STANDARD §1, §10)

| Stage | State here | Where |
|---|---|---|
| 1–4 format, lint, type, test | Applies, blocking | `make verify` → `ci.yml` / `verify` |
| 5 security | Applies, blocking | `security.yml` (gitleaks, Semgrep, OSV-Scanner), `make audit` (pip-audit), `secret-scan-history.yml` (weekly) |
| 6 a11y | Applies, blocking: the site is human-facing HTML | `make a11y` |
| 7 perf | Applies, blocking: a hosted frontend | `make perf` (Lighthouse). k6 N/A: static files, no route of ours runs |
| 8 responsible | N/A: no AI, consent or no-outing guard in this product (ADR 0004). The fail-closed build and the absence discipline are tested in stage 4 | — |
| 9 build | Applies: the site is built and validated (`make build`, `validate-html`, `validate-ics`); a wheel is built (`make wheel`). There's no release artifact (#7) | `ci.yml`, `pages.yml` |
| Workflow SAST | Applies, blocking | `workflow-lint.yml` (zizmor, policy script) |
| CI minutes | Ubuntu only; per-commit concurrency; heavy browser gates on push/PR only; schedules for history and freshness scans | `.github/workflows/` |

## Observability (OBSERVABILITY-STANDARD §0, §7)

**Tier B** for the site (static HTML and `.ics` feeds on GitHub Pages).
**Tier C** for the pipeline, a nightly batch job with no network ingress.

| Control | State |
|---|---|
| OBS-11 no secrets in logs | Applies: fetch errors redact the API key (`test_security_hardening.py`); Semgrep rule `wsc-credential-in-output` |
| OBS-23/24/25 lab Core Web Vitals | Applies: Lighthouse LCP < 2500 ms, CLS < 0.1, TBT < 200 ms (lab proxy for INP), in `make perf` |
| OBS-26 field Core Web Vitals (RUM) | Gap (#4). GA4 counts page views; there's no `web-vitals` beacon |
| OTel traces/metrics, SLOs, `/livez` `/readyz` | N/A: no service of ours runs at request time (Tier B static hosting, Tier C batch) |
| Pipeline logs | Tier C: human-readable build and coverage report on stdout; the coverage report goes to the `pages.yml` job summary. Structured JSON logging is N/A: one batch job, read in the Actions log |
| Freshness | `freshness.yml` checks the live `fetched_at` daily against a 30-hour SLA (ADR 0003) |

## Accessibility (ACCESSIBILITY-STANDARD §5)

| Metric | Value | Gate |
|---|---|---|
| axe violations, critical/serious/moderate, wcag2a–wcag22aa | 0 on every page | blocking (`make a11y`) |
| pa11y-ci, WCAG2AA, htmlcs + axe runners | 0 errors on every page | blocking |
| Lighthouse accessibility | ≥ 0.90 | blocking (`make perf`) |
| Keyboard walk, 320 px reflow, reduced motion | every page | blocking |
| Screen-reader and keyboard walkthroughs, ACR | not done | REVIEW, open (#5) |
| Route list | every HTML page in `dist/` plus two populated-table fixtures | `scripts/check_a11y_coverage.py` |
| Ignore list | empty | — |

## Performance (PERFORMANCE-STANDARD)

| Metric | Value | Gate |
|---|---|---|
| Lighthouse performance | ≥ 0.9 on every measured page | blocking |
| Script transfer | ≤ 204,800 B | blocking |
| Regression | ≤ 10% against `pipeline/perf/baseline.json` | blocking |
| p95 server latency (k6) | N/A: no server route of ours | — |

## Data (DATA-GOVERNANCE-STANDARD)

| Item | Value |
|---|---|
| Sources | Ticketmaster Discovery API only (`docs/data/ticketmaster-discovery-api.md`) |
| Tier | L1 |
| Freshness SLA | 30 hours (ADR 0003) |
| RPO | 24 hours. Every night rebuilds everything from the source; nothing else needs recovering |
| RTO | 1 hour. Re-run `pages.yml` (`gh workflow run pages.yml`) from `main` or the last good commit |
| Backups | None needed: the repository is the source of truth and data is re-fetched nightly (DG §3 N/A: no persistent store) |

## Release (RELEASE-AND-VERSIONING-STANDARD §1)

Release-producing: the deployed site is the release. No release process
exists yet (#7); `/version.json` stamps the live commit and pipeline
version.

Last verified: 2026-09-17 · Recheck cadence: quarterly, and whenever a
standard's version pin changes.
