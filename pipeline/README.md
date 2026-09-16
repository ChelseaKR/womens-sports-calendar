# pipeline

Python 3.12, managed with `uv`. Fetches from the Ticketmaster Discovery API
only (see `../docs/LICENSES-AND-ATTRIBUTION.md` and `../docs/DECISIONS.md`
0006 for why no league's own schedule feed is used — the short version:
every league examined either explicitly forbids automated/commercial reuse
of its site, or its terms could not be read at all), normalizes into `Game`
records, and emits per-league and per-team `.ics` calendars, compact JSON,
and the static site into `dist/`.

## Run it

```sh
uv sync --extra dev
uv run pytest -q                 # 80 tests, 4 with a recorded negative-control run (see below)

# Degraded mode (no key) -- always safe, always produces a valid site:
uv run python -m wsc_pipeline.build --out dist --base-url https://nexthomegame.com

# Real build:
TICKETMASTER_API_KEY=... uv run python -m wsc_pipeline.build --out dist --base-url https://nexthomegame.com
```

Every build prints a coverage report (also written to `dist/COVERAGE.txt`):
leagues examined vs. queried, teams with at least one game found, games
fetched, games with a Ticketmaster price, and the crawl budget actually
used (requests, bytes).

## Shape

- `config.py` — the static team/league registry (data, not code) that
  drives Discovery API keyword queries, plus the leagues examined and
  *not* configured (`LEAGUES_EXAMINED_NOT_INCLUDED`) with why.
- `ticketmaster.py` — the Discovery API client. Self-limits to 1
  request/second (below both published rate numbers — the two official
  Ticketmaster pages disagree, 2 vs. 5 req/s), retries on 429/5xx, and
  raises `TicketmasterFetchError` on a fetch that never succeeds. A raised
  `TicketmasterFetchError` is the "a failed fetch fails the build"
  contract — `build.py` lets it propagate rather than swallowing it into a
  silently-thinned result.
- `normalize.py` — turns a raw Discovery API event into a `Game`. Parses
  home/away teams from the event name (falling back to `_embedded.attractions`),
  extracts venue/date/TZID, and extracts a price range *only* when
  Ticketmaster published `priceRanges` with real `min`/`max` values —
  otherwise `price=None`, never a fabricated 0 or omitted-but-implied
  value. No broadcaster field exists anywhere in this pipeline: no
  licensed source carries one.
- `ics.py` — RFC 5545 `.ics` emission. UIDs are derived deterministically
  from the Ticketmaster event id (`tm-<event_id>@womens-sports-calendar.invalid`),
  so re-subscribing or a nightly rebuild never duplicates entries.
  `check_no_duplicate_uids` raises on any collision within one calendar.
  Games with no exact start instant (`date_tbd` or no `dateTime`) are
  excluded from the `.ics` — RFC 5545 has no clean "TBD" representation —
  but stay visible on the site.
- `coverage.py` — the printed coverage report. "Join hit-rate" from the
  original brief is reinterpreted here (see `docs/DECISIONS.md` 0006):
  since there is no second feed to join against Ticketmaster, it is the
  fraction of configured teams that had at least one upcoming Ticketmaster
  listing.
- `site_data.py` — the compact JSON the HTML is templated from. One shape,
  reused for league and team pages; a game's `price` key is present and
  either a real object or `null`, never omitted.
- `site.py` — the static HTML generator. Zero `<script>` elements on any
  page (checked by `tests/test_site_html.py`), `<link rel="canonical">`,
  a favicon (SVG primary + PNG/apple-touch-icon fallbacks), Open Graph and
  Twitter Card tags — including a real `og:image` per page (the site-wide
  default on the index, a per-league card on every league and team page,
  see `assets/` below) — semantic landmarks, table headers with `scope`,
  link text that names its destination ("Buy tickets for X vs Y on
  \<date\> from Ticketmaster", never bare "Buy" or "click here"), and a
  literal, non-euphemistic privacy note in the footer.
- `build.py` — the orchestrator/CLI (`python -m wsc_pipeline.build`).
  Writes to a temp directory and only atomically replaces `--out` on full
  success, so a failed fetch never leaves a partial/broken build where a
  good one used to be — the "a stale build is never published as current"
  rule, enforced locally as well as by the GitHub Actions job stopping
  before the deploy step on any failure. Also copies the favicon and
  social-card assets from `assets/` into `--out` (raising if one is
  missing, rather than shipping a page whose `og:image` 404s).
- `assets/` — the favicon and Open Graph / Twitter card images: hand-
  authored SVG (`scripts/render_social_assets.py`), rendered to PNG with
  `rsvg-convert` and committed here (both the `.svg` sources and the
  rendered `.png` files), so a normal build — including the nightly CI
  run — never needs `rsvg-convert` installed; it only copies
  already-rendered files. Re-run the script and commit its output only
  when the artwork itself changes. Colour contrast for every text/graphic
  pair drawn into these images is checked and recorded in the script's
  module docstring, at the same rigor as `site.STYLE_CSS`.

## Tests

`tests/` covers normalization (absence discipline for price/date/venue),
`.ics` generation (RFC 5545 round-trip via `icalendar`, duplicate-UID
checks at both the single-calendar and whole-build level, TBD-date
exclusion), the Ticketmaster client (throttling, retry, the 429 path, the
"failed fetch raises" contract), coverage math, the JSON data layer's
absence discipline, and the generated HTML (no `<script>` tags anywhere,
no price rendered without a matching Ticketmaster event, table headers,
link text, canonical/favicon/OG/Twitter-card tags — including that each
page's `og:image` is the real, correctly-sized card for that page type,
not one generic image repeated everywhere — the privacy note, and that
`build.py` actually copies the favicon and social-card bytes into `--out`
at the real dimensions those tags promise, failing loudly if one is
missing).

Four of these checks were run through a full negative-control cycle
(sabotage the guarded code, confirm the sabotage landed by occurrence
count and `git hash-object`, confirm the targeted test goes RED with the
assertion, restore the file with `cp` from a backup and confirm
`git hash-object` matches the pre-sabotage hash byte-for-byte): the
duplicate-UID check, the price-absence-discipline check (at the
normalize/site_data/ics-description layers together), the
no-`<script>`-tags check, and the RFC 5545 required-property check
(`dtstamp`). All four went RED with the sabotage in place and green again
after restoration; this was a one-time verification pass, not something
CI re-runs.

Also run (not part of `pytest`, but part of `make verify` and so CI-gated on
every push/PR, not a one-time manual check):

- `make validate-html` — `html5validator` against every generated page (0
  errors across all 54 pages in the degraded, no-API-key build CI runs).
- `make a11y` — `pa11y --standard WCAG2AA` against every generated page (the
  same 54) **plus** two fixture pages rendered with a populated games table
  (a priced game, an unpriced game, and a date-TBD game together — the exact
  shape `tests/test_site_html.py::_pages()` builds and asserts on, reused via
  `scripts/render_a11y_fixtures.py` rather than duplicated) — these two exist
  because the degraded build CI runs never has a non-empty games table to
  check. **56/56 pages pass, 0 issues, as of this pipeline's last run** — see
  `pipeline/Makefile`'s `a11y` target for exactly what runs.

No human screen-reader walkthrough has been performed (this is a brand-new
private product, not yet public); that stays a manually-tracked open item,
separate from the two automated, CI-enforced checks above.
