# 0003. Listings freshness: a 30-hour SLA, stated on the page and alarmed

Status: Accepted
Date: 2026-09-17
Deciders: Chelsea Kelly-Reif

## Context

`pages.yml` rebuilds the site every night at 08:13 UTC and deploys only if
the fetch fully succeeded. That rule is right: a failed fetch never
replaces a subscriber's calendar with an empty one. The cost is that a
broken fetch, an expired key or a Pages problem leaves the previous night's
listings live, and nothing said so. The live data had no fetch time a
reader could see, and nothing compared it with a clock
(DATA-GOVERNANCE-STANDARD DG-02, DG-04; INCIDENT-RESPONSE-STANDARD §1 lists
"serves stale-past-SLA data as current" as SEV2).

## Decision

- Every published data file, `version.json` and the league and team pages
  carry `fetched_at`, the time the listings were read (null when nothing was
  fetched; such a build is never deployed).
- The staleness SLA is **30 hours**. A daily check at 15:07 UTC
  (`freshness.yml`, about seven hours after the nightly deploy) reads the
  live `data/site.json`. After a good night the listings are about 7 hours
  old. After one missed night they are about 31, so a single failed
  night is caught the same day.
- A failure opens one `incident` + `sev2` + `stale-data` issue, or comments
  on the open one; it never opens a second.
- Pages say "Listings as of <date, time> UTC". A static site can't
  compute "stale" in the reader's browser without adding a script, so the
  honest surface is the date itself.

## Consequences

- A stale site becomes an issue within a day instead of being found by
  chance.
- The check depends on the live site, and so on the date. It runs on a
  schedule only and is never a pull-request check.
- The SLA is a single number in `freshness.yml` (`MAX_AGE_HOURS`) and in
  the data card; change both together.
