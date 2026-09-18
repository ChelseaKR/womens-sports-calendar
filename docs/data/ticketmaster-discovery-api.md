# Data card: Ticketmaster Discovery API

The only data source this site ingests (DECISIONS 0006). The DATA-GOVERNANCE-STANDARD
§1 card fields are listed below; `pipeline/tests/test_provenance.py` fails
if any of them is missing or empty, and fails if a published data file stops
naming this source.

| Field | Value |
|---|---|
| Source | Ticketmaster Discovery API v2, `https://app.ticketmaster.com/discovery/v2/events.json`, operated by Ticketmaster L.L.C. (Live Nation Entertainment). One keyword search per tracked team and country, `classificationName=Sports` (`pipeline/src/wsc_pipeline/ticketmaster.py`). |
| License | Not an open licence. Used under the Ticketmaster Developer Portal "General Terms of Use" (last updated 2023-06-27): no resale of API access, no replicating Ticketmaster's purchase experience, Event Content stored only for reasonable periods to provide the service, and removed within 24 hours if the owner asks. Clause-by-clause reading in `docs/LICENSES-AND-ATTRIBUTION.md` §2. No SPDX identifier applies. |
| Fields taken | Event id, name, attractions, venue name/city/state/time zone, venue street address, postcode and country code (the structured-data address only), local and UTC start, date/time-TBD flags, the event status code (only cancelled, postponed and rescheduled are shown), event URL. Price ranges are read but not shown (DECISIONS 0013). Nothing about any person. |
| Fetch/refresh cadence | Nightly, `pages.yml` at 08:13 UTC. Each run replaces the whole published data set. |
| Staleness SLA | 30 hours since the last successful fetch (ADR 0003). `.github/workflows/freshness.yml` reads the live `version.json` every day at 15:07 UTC. If the listings are older than that, or unreadable, it fails and opens a `sev2` incident issue. Every league and team page shows "Listings as of <time>" so a reader can see the date. |
| Fetch timestamp | `fetched_at` (ISO 8601, UTC) in `data/site.json`, every `data/<league>.json` and `data/<league>/<team>.json`, and `version.json`. The same value across one build. `null` when a build fetched nothing, and such a build is never deployed. |
| Tier | L1: public event listings with no personal or identity data (DATA-GOVERNANCE-STANDARD §0). Not openly licensed, so the redistribution limits in the License row apply. |
| Known limitations | Keyword search matches venue and other text, so each result is checked against the event's own participants and non-matches are dropped and counted (`team_is_participant`, DECISIONS 0009). At most 5 pages of 50 results per team and country are read; a longer result list is flagged "possibly incomplete" on the page. Seasons in progress may be listed late or partly. A game Ticketmaster doesn't list isn't on this site. Zero games across every tracked team is treated as a failed fetch, never as "no games". |
| Retention | Nothing is kept beyond the live site. Each night's build replaces the previous one. Nothing fetched is committed to git (`pipeline/dist/` is ignored), and the Pages deployment artifact is GitHub's to expire. The terms require removing an event within 24 hours if its owner asks. There's no per-event exclusion switch yet, so today that request means a code change that filters the event id, then a manual redeploy (`gh workflow run pages.yml`). This is an open item, and so is the contact channel such a request would arrive through (`docs/LICENSES-AND-ATTRIBUTION.md` §2). |
| Dataset version | Not versioned: the published data is a nightly snapshot of the source, identified by its `fetched_at` and by `version.json`'s `commit`, not a released dataset (DG-17..19 do not apply). |

Last verified: 2026-09-17 · Recheck cadence: quarterly, and whenever the
Ticketmaster Developer Portal terms change.
