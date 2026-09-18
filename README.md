# womens-sports-calendar (working name)

Subscribable `.ics` calendar feeds per league and team for women's pro and
college sports, built nightly from the Ticketmaster Discovery API, with one
plain "Buy tickets" link per game to the home team's ticket seller. No
account. Calendar-first and price-free since 2026-09-17
(`docs/DECISIONS.md` 0013): no licence-clean price source exists, and the old
price promise was empty on every game. Any revenue would come only from
affiliate links, and none is active yet. The web pages use Google Analytics 4
(not loaded under Global Privacy Control or Do Not Track, or after the
footer's "Opt out of analytics", ads features off; `docs/DECISIONS.md` 0012);
the calendar feeds carry no tracking of any kind.

[moved to private strategy notes]

**Status: Production.** Live at https://nexthomegame.com and rebuilt every
night. Private repository.

## Quickstart

Needs `uv` (it fetches Python 3.12) and, for the accessibility and
performance checks, Node 22.

```sh
git clone git@github.com:ChelseaKR/womens-sports-calendar.git
cd womens-sports-calendar
make verify                    # every gate CI runs
make -C pipeline build         # the site, into pipeline/dist/
```

Without `TICKETMASTER_API_KEY` the build runs in degraded mode: every page
says the schedule was not fetched, never "no games". With a key
(`export TICKETMASTER_API_KEY=...`) it fetches the real listings.
`CONTRIBUTING.md` has the full workflow.

## Shape

- `pipeline/` — Python 3.12, managed with `uv`. Per
  `docs/LICENSES-AND-ATTRIBUTION.md` and `docs/DECISIONS.md` 0006, **no
  league's own schedule source passed licensing** — every league examined
  either forbids automated/commercial reuse or has unreadable terms — so the
  pipeline reads only the Ticketmaster Discovery API (per team, by keyword),
  normalizes into games, and emits one `.ics` per league and per team plus the
  compact JSON the site renders from. Nightly; no human step. The static HTML
  generator (`pipeline/src/wsc_pipeline/site.py`) lives inside the pipeline
  package rather than as a separate `site/` module, because it renders
  directly from the same `Game`/`League` types the fetch and normalize code
  use — see `site/README.md`.
- `site/` — where the deployed output logically lives; see `site/README.md`
  for why the generator itself is in `pipeline/`. The built output
  (`pipeline/dist/`, gitignored, rebuilt every run) is one page per league and
  team: the subscribe buttons (Google Calendar, Apple Calendar, Outlook)
  first, then the next home game and the upcoming games, each with one
  plain ticket link (`pipeline/src/wsc_pipeline/sellers.py`) and no prices,
  plus `/privacy/`, `sitemap.xml` and `robots.txt`. Pages carry schema.org
  JSON-LD (a data block, never run). The only script that runs is one inline
  Google Analytics 4 loader per page, emitted only while
  `pipeline/src/wsc_pipeline/analytics.py`'s `GA4_MEASUREMENT_ID` is set
  (it is: `G-YKGPZ76LVE`); it loads nothing under Global Privacy Control,
  Do Not Track, or the footer's remembered "Opt out of analytics" choice,
  turns Google signals and ad personalisation off, and denies
  analytics storage for the EEA, UK and Switzerland. The `.ics` feeds are
  never tracked.
- `docs/` — research, decisions, licences and attributions.
- `.github/workflows/` — `ci.yml` (`make verify` on every push and PR) and
  `pages.yml` (the nightly and manual build and GitHub Pages deploy).
- `docs/adr/` — architecture decisions from 2026-09-17 on
  (`docs/DECISIONS.md` holds the earlier ones).

## Where it runs

Live at **https://nexthomegame.com** (checked 2026-09-17): the domain was
registered 2026-09-14 (Amazon Registrar, Route 53 DNS), the apex points at
GitHub Pages, the Pages custom domain is set and its certificate is issued,
and `pages.yml` deploys nightly. `www.nexthomegame.com` now has its `CNAME`
to `chelseakr.github.io`, but GitHub's certificate still covers only the
apex, so `https://www` fails (checked 2026-09-18). "Enforce HTTPS" is on:
`http://` and `http://www` both redirect to `https://nexthomegame.com/`.
`SITE_BASE_URL` is unset (the build's default, `https://nexthomegame.com`,
is what is used). Still open, owner steps: the `https://www` certificate,
and verifying the Google Search Console Domain property (a DNS TXT record
in the Route 53 zone) and submitting `https://nexthomegame.com/sitemap.xml`.

## Not yet decided

The pages say "Next Home Game" (header, `<title>`, `og:site_name`), matching
the domain (`docs/DECISIONS.md` 0007); the repo keeps its working name,
`womens-sports-calendar`.

## Standards Conformance

This repository follows the portfolio standards, vendored at
`docs/standards/` (v2.0.0). Each row is one of: `Applies` (conformant),
`Applies — gap tracked in #NN` (an open issue lists what is missing), or
`N/A — reason`. CITATION.cff — N/A: a commercial consumer site with no
scholarly or civic-reuse intent.

| Standard | State |
|---|---|
| Responsible-Tech Framework | Applies — gap tracked in #29 (audits A, C and F drafted in `docs/RESPONSIBLE-TECH-AUDITS.md`, pending owner sign-off) |
| Code Quality | Applies — gap tracked in #22 (ruff, mypy --strict, an 85% branch floor, lock-drift and pip-audit gates in `make verify`; mutation testing open) |
| Security & Supply-Chain | Applies — gap tracked in #23 (gitleaks, TruffleHog, Semgrep and OSV-Scanner gates; Scorecard and release signing open) |
| CI/CD | Applies — gap tracked in #24 (the protect-main ruleset is committed but not applied) |
| Release & Versioning | Applies — gap tracked in #28 (the deployed site is the release; there is no release process yet) |
| Observability | Applies — gap tracked in #25 (Tier B site, Tier C pipeline; no field Core Web Vitals) |
| Performance | Applies — gap tracked in #33 (Lighthouse budgets with a committed baseline; k6 N/A: static files, no server route of ours) |
| Accessibility | Applies — gap tracked in #26 (WCAG 2.2 AA target; axe, pa11y, keyboard, reflow and motion gates on every page; no human review yet; statement in `docs/a11y/STATEMENT.md`) |
| Internationalization | Applies — gap tracked in #27 (English-only; a deferral is declared in `docs/I18N.md`, owner decision pending) |
| AI Evaluation | N/A — no LLM, prompt, retrieval or model component (ADR 0004) |
| Documentation | Applies — gap tracked in #31 (nothing yet checks the vendored standards against their tag) |
| Quality & Metrics | Applies — gap tracked in #32 (`DEFINITION_OF_DONE.md` and a PR template; DORA review and cross-browser smoke open) |
| AI Development Measurement | Applies (delivery and quality-debt metrics come from this repository's PR history in the standards repository's rollup; never used as a gate) |
| Incident Response | Applies (`incident` and `sev1`–`sev4` labels; the postmortem template in `docs/incidents/` and the stale-data alarm in `freshness.yml`; no incidents to date) |
| Data Governance | Applies — gap tracked in #30 (L1 public listings; a data card, fetch timestamps and a 30-hour freshness alarm; ingest schema and 24-hour removal open) |
| Discovery & Adoption | Applies (advisory; the repository is private, and the public site carries Open Graph cards on every page) |

Release cadence: none yet (see #28). The site's data refreshes nightly.
