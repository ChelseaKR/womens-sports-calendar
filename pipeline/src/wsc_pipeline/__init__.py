"""wsc_pipeline: nightly build for womens-sports-calendar.

Fetches from the Ticketmaster Discovery API only (see
docs/LICENSES-AND-ATTRIBUTION.md and docs/DECISIONS.md 0006 for why no
league's own schedule feed is used), normalizes into Game records, and
emits per-league and per-team .ics calendars, compact JSON, and the static
site.
"""
