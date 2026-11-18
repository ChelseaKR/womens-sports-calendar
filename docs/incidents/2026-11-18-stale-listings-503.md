# Incident: live listings went past the 30-hour SLA after one feed read returned HTTP 503 — 2026-11-18

**Severity:** SEV2 · **Status:** Resolved · **Related issue:** #105

## Summary

The nightly pages build on 2026-11-18 refused to publish. While re-reading the
previous night's calendar feeds, one request (the Minnesota Golden Gophers
Big Ten feed) got HTTP 503 from the live site. The publish guard
(docs/adr/0006) treats a previous feed it cannot read as a possible loss of
played games, so it wrote nothing and left the last good deploy live. No
games were removed from anyone's calendar. Because nothing new was
published, the listings passed the 30-hour freshness SLA at about 14:25 UTC,
and `freshness.yml` opened #105. Re-running the same pages run published
normally at 21:27 UTC.

## Timeline (UTC)

| Time | Event |
|---|---|
| 2026-11-17 08:25 | Last good publish (pages run at `a69b680`); listings `fetched_at` 08:25:26. |
| 2026-11-17 14:37, 20:55 | #102 (About page) and #103 (ticket-link hosts) merged; they wait for the next nightly publish. |
| 2026-11-18 08:20 | Nightly pages run starts at `9961f96`. |
| 2026-11-18 08:25 | Publish guard refuses: `ics/ncaaw-big-ten/minnesota-golden-gophers-womens-basketball.ics (HTTP 503)`. Nothing written; previous deploy stays live. |
| 2026-11-18 ~14:25 | Listings pass the 30-hour SLA. |
| 2026-11-18 15:13 | `freshness.yml` opens #105 (listings 30.8 h old). |
| 2026-11-18, before 21:21 | The missing About page (404) is noticed; the failed run's log is read. |
| 2026-11-18 21:21:46 | The pages run is re-run (attempt 2), as the guard's message advises. |
| 2026-11-18 21:27 | Re-run succeeds; `site.json` `fetched_at` 21:26:57; `/about/` returns 200. |

## Impact

- Listings were stale for about 13 hours in total, about 7 of them past the SLA.
- Calendar subscribers kept every game from the previous good night. A game
  added, moved or cancelled at the source in that window reached subscribers
  late; how many, if any, was not measured.
- The About page and the ticket-link change merged on 2026-11-17 went live
  about 13 hours later than planned.

## Detection

`freshness.yml` detected the SLA breach 48 minutes after it began and opened
#105. The failed pages run at 08:25 raised nothing beyond the run's own red
status, and #105 sat for about 6 hours before anyone acted on it.

## Root cause

A single transient HTTP 503 from the live site while the build re-read one
previous feed. The guard is working as designed: it refuses rather than risk
dropping played games. There is no automatic retry, so one failed request
stopped the whole night's publish until someone re-ran it by hand.

## What went well

- The guard kept every played game in subscribers' calendars and left the last good deploy live.
- The guard's error said exactly what to do ("re-run the pages workflow once the live site answers"), and that worked on the first try.
- The freshness check caught the breach within the hour.

## What went poorly

- One transient 503 blocked the whole publish; nothing retried it.
- A failed nightly publish produced no alert of its own; only the SLA check, six hours later, did.
- `freshness.yml` opens stale-data issues but never closes them, so #105 needed closing by hand.

## Action items

| Action | Owner | Due | Tracking issue |
|---|---|---|---|
| Retry a previous-feed read a few times with backoff on 5xx or timeout before the guard counts it as unreadable | Chelsea | Proposed, not scheduled | none yet |
| Open an incident issue when the nightly pages run fails, not only when the SLA passes | Chelsea | Proposed, not scheduled | none yet |
| Let `freshness.yml` close its own `stale-data` issue when a later check passes | Chelsea | Proposed, not scheduled | none yet |

## Related

- docs/adr/0006 (publish guard)
- Pages run 44266112305 (attempt 1 failed, attempt 2 succeeded)
- Freshness run 44333118448
