# 0005. Sitemap lastmod: when the schedule changed, read back from the live site

Status: Proposed
Date: 2026-09-18
Deciders: Chelsea Kelly-Reif

## Context

`sitemap.xml` listed every page with no `<lastmod>`. Search engines use
`<lastmod>` to decide what to recrawl, and Google ignores it on sites where
it proves unreliable. The obvious value, the build time, would claim every
page changed every night, which is false for any team between games and
for every league in its off-season.

The build is stateless by design: a fresh checkout every night, no cache
(CI-CD-STANDARD §8c), no write access to the repository, and a deploy only
when the whole fetch succeeds. Nothing survives from one night to the next
except what was published.

## Decision

- Every build publishes `/lastmod.json`: for each schedule page (home,
  league, team), a SHA-256 fingerprint of the payload it renders from,
  excluding when the listings were fetched, and the time that content was
  first seen.
- A build that fetches listings first reads the live `/lastmod.json`. Per
  page: same fingerprint keeps the old time (including "unknown"); a
  different fingerprint, or a page the last deploy did not have, takes this
  build's fetch time.
- When there is no readable previous manifest (the first deploy with this
  file, the site unreachable, a malformed body), every date is unknown, and
  a page with an unknown date gets no `<lastmod>`. It is never replaced by
  the build time. The read never fails the build: it costs dates, not
  calendars.
- The privacy and accessibility pages are not schedules. Their `<lastmod>`
  is the "Updated" date each page prints, from one constant in `site.py`.
- `make validate-seo` (in `make verify` and in `pages.yml` before deploy)
  fails a sitemap whose `<lastmod>` disagrees with `/lastmod.json`, lies in
  the future, or is not a W3C date.

## Consequences

- After the first deploy, no schedule page has a `<lastmod>` until its
  listings change; in season that is usually the next night. Pages with no
  change stay undated rather than wrongly dated.
- A night whose build cannot read the live manifest loses every carried-over
  date, and pages regain them one change at a time.
- The comparison is against what is live, so after failed nights the date
  is when the change was first published, not first fetched.
- A code change that alters a page's payload (a new field) moves every
  affected page's date once. That page did change.
- The build now makes one request to its own site before fetching from
  Ticketmaster. It sends no secret, and a failure or a malformed body is
  treated as no history.
