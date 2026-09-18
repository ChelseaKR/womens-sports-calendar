# Security policy

## Scope

- The site at https://nexthomegame.com and its calendar feeds
  (`https://nexthomegame.com/ics/...`).
- This repository: the Python pipeline in `pipeline/` that builds them, and
  the GitHub Actions workflows that test, scan and deploy them.

The site is static: no accounts, no forms, no server code of ours runs when
a page is read. The realistic risks are in what the build publishes (it
renders third-party data from the Ticketmaster Discovery API into HTML and
`.ics`), in the build's own credentials, in the supply chain, and in the one
third-party script the pages load: Google Analytics 4 (DECISIONS 0012),
which is served by Google and cannot be pinned with subresource integrity
because Google changes it in place.

## Supported versions

There are no versioned releases. The only supported version is what is
live: the site is rebuilt from `main` every night and deployed only if every
check passes.

## Reporting a vulnerability

**Do not open a public issue.** Send the report through the contact page at
https://chelseakr.com/contact and say it is a security report for Next Home
Game. You will get an acknowledgement within 72 hours. Include the page or
feed URL and what you observed; the site can be rebuilt locally
(`make verify` in a clone) to reproduce most findings without touching
production.

## Credentials

The build uses two GitHub Actions secrets, `TICKETMASTER_API_KEY` and
`TICKETMASTER_AFFILIATE_ID`. Only the nightly `pages.yml` build job reads
them; the job that deploys to Pages has no access to them, and pull-request
CI never receives them. Error messages redact the API key before printing.
If a key is exposed: rotate it in the Ticketmaster developer console, update
the secret (`gh secret set TICKETMASTER_API_KEY`), revoke the old key, and
follow the secret-leak runbook in `docs/standards/INCIDENT-RESPONSE-STANDARD.md` §4.
Keys are reviewed annually and rotated on any suspected exposure.

## What runs on every change

| Control | Where |
|---|---|
| Secret scan of the full history (gitleaks) | `security.yml` / `gitleaks`; also a pre-commit hook |
| Weekly full-history secret scan, all TruffleHog result tiers | `secret-scan-history.yml` |
| SAST: Semgrep registry packs + a repository rule against credentials in output | `security.yml` / `semgrep` |
| Dependency advisories for `uv.lock` and `package-lock.json` (OSV) | `security.yml` / `osv-scanner`; waivers with expiry in `pipeline/osv-scanner.toml`, VEX in `pipeline/vex.cdx.json` |
| Python dependency audit (pip-audit) | `make verify` |
| Output encoding of Ticketmaster data; non-http(s) ticket URLs dropped | `pipeline/tests/test_security_hardening.py` |
| Actions pinned to commit SHAs, updated by Renovate with a 72-hour delay | `renovate.json` |

Tool choices are recorded in `docs/adr/0002-security-scanning-on-a-private-repository.md`.
