# 0002. Security scanning on a private repository

Status: Accepted
Date: 2026-09-17
Deciders: Chelsea Kelly-Reif

## Context

SECURITY-AND-SUPPLY-CHAIN-STANDARD §3-4 and §9 name Semgrep + CodeQL for
SAST, gitleaks (pre-commit and CI) plus a scheduled TruffleHog history scan
for secrets, and pip-audit/OSV-Scanner for dependencies, with results
uploaded to GitHub code scanning. This repository is private. GitHub code
scanning, SARIF upload and the CodeQL CLI's licence for non-open-source
code all require GitHub Advanced Security, which this account does not
have. A gate that depends on an upload that cannot succeed would either
fail forever or be muted, and a muted gate is forbidden.

The one dependency advisory present at adoption (extract-zip 2.0.1, two
HIGH, no fixed release) arrives only through the accessibility test
tooling.

## Decision

- SAST: Semgrep OSS (pinned version) with the `p/python`,
  `p/security-audit`, `p/secrets` and `p/github-actions` registry packs, plus
  a repository rule (`.semgrep/wsc-credential-in-output.yml`) whose own
  tests run first. ruff's bandit rules (`S`) run in `make verify`. The job
  fails on any ERROR or WARNING finding. CodeQL is not used.
- Workflow SAST: zizmor, in `workflow-lint.yml` (CI/CD change).
- Secrets: gitleaks v8.30.1 over the full history on every push and PR and
  as a pre-commit hook; TruffleHog weekly over every branch, failing on
  verified, unknown and unverified results alike.
- Dependencies: pip-audit in `make verify`; OSV-Scanner over both lockfiles
  in CI. Each tool is a pinned release checked against a pinned SHA-256.
- Findings are read in the job log. Nothing is uploaded to code scanning.
- A dependency advisory with no fix may be waived only in
  `pipeline/osv-scanner.toml` with a reason and an expiry of at most 90 days,
  plus a VEX statement in `pipeline/vex.cdx.json`. An expired waiver stops
  suppressing, and the gate fails until someone reviews it.

## Consequences

- Every scanner is merge-blocking and can fail. The PR that added them
  shows a planted secret, a sabotaged rule and an expired waiver each
  failing.
- There is no Security-tab view and no CodeQL cross-file dataflow. The
  attack surface is a static site built from one API, which keeps that gap
  small, but it is a gap. If this repository becomes public, add CodeQL
  (`python` and `actions`) with SARIF upload and supersede this ADR.
- Registry rule packs can change between runs; a new rule can fail an
  unchanged tree. That is intended: triage it, fix it or waive it with a
  reason. Don't pin it away.
- OpenSSF Scorecard (SEC-31..38) is not run: on a private repository it
  needs a personal access token and cannot publish results. Tracked as an
  open gap.
