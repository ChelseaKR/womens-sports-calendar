# Responsible-tech audits: Next Home Game

Instantiates `docs/standards/RESPONSIBLE-TECH-FRAMEWORK.md` for this
repository. Drafted 2026-09-17. The REVIEW-GATE judgments below are
**drafts pending the owner's dated sign-off (#29)**. Until that sign-off, none
of them is an approved audit.

## Applicability

- A Ethics: applies
- B Bias: applies (lite). The site ranks and classifies no one. The
  representational question is which leagues and teams are covered, and why
  others are not.
- C Privacy: applies (GA4 on the web pages, DECISIONS 0012; hosting logs)
- D Transparency: applies
- E Accessibility: applies (`docs/a11y/STATEMENT.md`)
- F Security: applies (§F below)
- AI-EVAL: N/A. There is no LLM, prompt, retrieval or model component
  (ADR 0004).
- I18N: applies, deferred pending an owner decision (`docs/I18N.md`, #27)

## A. Ethics (draft)

**Who uses it:** fans who want a team's home games in their own calendar.
**Who else it touches:** the leagues and teams whose schedules it
republishes (via Ticketmaster), the ticket sellers it links to, and
Ticketmaster as the data provider.

**Worst plausible failure:** a wrong or stale game time sends someone to an
arena on the wrong day. Mitigations: listings are Ticketmaster's own; a
failed fetch never replaces the calendar; the page shows when the listings
were fetched; a freshness alarm opens an incident if they go stale (ADR
0003); a game whose date is TBD is kept out of the calendar feed.

**Worst plausible misuse:** presenting a commercial link as neutral advice.
Every ticket link names where it goes and, where an affiliate programme
applies, the footer says so (DECISIONS 0013).

**Non-goals:** selling tickets; showing or guessing prices; accounts; any
personal data; scraping league sites (licence before bytes, DECISIONS 0003).

**Kill switch:** disable the `pages.yml` schedule or re-deploy the last good
commit (`gh workflow run pages.yml`). Every feed then keeps its last good
content.

## B. Bias (draft)

Coverage is decided by licensing and by Ticketmaster's listings, not by
popularity. Five leagues are tracked. Every league examined and not
included is named on the home page with the reason. Known skew: a team whose
games Ticketmaster does not list (small venues, some college programmes)
appears with no games. That is labelled as Ticketmaster's absence, never
"no games".

## C. Privacy (DPIA-lite, draft; needs updating for the owner's GA4 decision)

| Data | Collected by | Purpose | Retention | Control |
|---|---|---|---|---|
| Page views and ticket or subscribe clicks (URL, referrer, device and browser type, derived coarse location) | Google Analytics 4 on the web pages | See which leagues and teams are used | 14 months (`analytics.GA4_DATA_RETENTION`) | Not loaded under GPC or DNT, or after the footer opt-out; Google signals and ad personalisation off; in the EEA, UK and Switzerland, no analytics cookies |
| Request logs (IP address, user agent) | GitHub Pages, as host | Serving the site | GitHub's policy; not accessible to this site | — |
| Opt-out choice | The reader's own browser (`localStorage`) | Remember "don't load analytics" | Until the reader clears it | Never sent anywhere |
| Calendar feed fetches | GitHub Pages | Serving `.ics` | as above | Feeds carry no tracking |

No accounts, forms, cookies of our own or personal data exist in this
repository or its data files. The fetched data is public event listings (L1,
`docs/data/`).

## D. Transparency (draft)

Every page names its source (Ticketmaster Discovery API) and terms, says
that no league schedule is used and why, and shows when the listings were
fetched. Absence is shown as absence, never as a value: "not fetched",
"date TBD", "no ticket link published yet". The privacy page describes
exactly what the current build does, generated from the same configuration
as the pages.

## E. Accessibility

See `docs/a11y/STATEMENT.md` and the ledger in `docs/ROADMAP.md`. Human
review is open (#26).

## F. Security

### Declarations (SECURITY-AND-SUPPLY-CHAIN-STANDARD §8)

1. **ASVS level:** L1, the floor. There is no authentication, authorization
   or ingress of ours. The site is static files on GitHub Pages. The L1
   concern that remains is output encoding of third-party data:
   Ticketmaster fields are HTML-escaped and non-http(s) ticket URLs are
   dropped. `pipeline/tests/test_security_hardening.py` checks both.
2. **Container scanning:** N/A. There is no Dockerfile.
3. **SBOM + signing:** the site is release-producing, but no release is cut
   yet. SBOM, signing and provenance are open (#23, #28).
4. **Secret-management policy:** `SECURITY.md`, Credentials. Two Actions
   secrets are read only by the `pages.yml` build job, redacted from errors,
   and rotated on suspicion and reviewed annually.
5. **VEX:** `pipeline/vex.cdx.json` (extract-zip, dev-only, no fix
   released; waiver expires 2026-12-16).

### Threat model (STRIDE, draft)

| Threat | Vector | Mitigation | Residual |
|---|---|---|---|
| Tampering → XSS | Hostile Ticketmaster fields or ticket URLs | Escaping everywhere, http(s)-only URLs, tests | Low |
| Information disclosure | The API key in logs or history | Redaction, gitleaks (CI and pre-commit), weekly TruffleHog, secrets confined to one job | Low |
| Tampering (supply chain) | A compromised action or dependency | SHA-pinned actions, Renovate with a 72 h delay, OSV-Scanner, pip-audit, zizmor, CODEOWNERS | Medium (standard) |
| Tampering (third-party script) | Google's `gtag.js` is loaded on every page (owner decision, DECISIONS 0012) and cannot use SRI | Accepted by the owner; not loaded under GPC, DNT or opt-out | Medium, accepted |
| Spoofing (domain takeover) | The custom domain could be claimed by another Pages site if the Pages config lapses | Verify `nexthomegame.com` for GitHub Pages (owner action) | Medium until verified |
| Denial of service (stale data) | The Ticketmaster fetch breaks and yesterday's data stays live | Freshness alarm (ADR 0003) and the "as of" date on each page | Low |
| Repudiation | An unreviewed change reaching `main` | `protect-main` ruleset (committed, not yet applied: #24) | Medium until applied |

Sign-off: pending (#29).
