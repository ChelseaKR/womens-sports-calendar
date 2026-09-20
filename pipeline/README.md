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
uv sync                          # runtime dependencies plus the `dev` group
uv run pytest -q                 # the whole suite; negative controls described below

# Degraded mode (no key) -- always safe, always produces a valid site:
uv run python -m wsc_pipeline.build --out dist --base-url https://nexthomegame.com

# Real build:
TICKETMASTER_API_KEY=... uv run python -m wsc_pipeline.build --out dist --base-url https://nexthomegame.com
```

The tools (pytest, ruff, mypy and the rest) are a PEP 735 dependency group
named `dev` in `pyproject.toml`, not an extra, so `uv sync` installs them
without a flag (`uv sync --extra dev` fails). `make install`, which CI runs,
is `uv lock --check` followed by `uv sync --frozen`: it installs exactly
`uv.lock` and fails if `pyproject.toml` and the lockfile disagree.

Every build prints a coverage report (also written to `dist/COVERAGE.txt`):
leagues examined vs. queried, teams with at least one game found, games
fetched, games with a Ticketmaster price, and the crawl budget actually
used (requests, bytes).

## Shape

- `config.py` — the static team/league registry (data, not code) that
  drives Discovery API keyword queries, plus the leagues examined and
  *not* configured (`LEAGUES_EXAMINED_NOT_INCLUDED`) with why. Adding a
  team or a league also touches the seller table, the social cards, the
  tests and the licensing notes: `../CONTRIBUTING.md` has the checklist.
- `ticketmaster.py` — the Discovery API client. Self-limits to 1
  request/second (below both published rate numbers — the two official
  Ticketmaster pages disagree, 2 vs. 5 req/s), retries on 429/5xx, and
  raises `TicketmasterFetchError` on a fetch that never succeeds. A raised
  `TicketmasterFetchError` is the "a failed fetch fails the build"
  contract — `build.py` lets it propagate rather than swallowing it into a
  silently-thinned result.
- `normalize.py` — turns a raw Discovery API event into a `Game`. Parses
  home/away teams from the event name ("Home vs Away", or "Away at Home"),
  falling back to `_embedded.attractions` for the pair only — then
  `home_away_known` is false and nothing calls either team the home side —
  and extracts venue (name, city, state, street, postcode, country), date,
  TZID and Ticketmaster's status code, and extracts a price range *only* when
  Ticketmaster published `priceRanges` with real `min`/`max` values —
  otherwise `price=None`, never a fabricated 0 or omitted-but-implied
  value. That price now reaches only the `.ics` event description, which
  is unchanged; no page or JSON shows it (DECISIONS 0013). No broadcaster
  field exists anywhere in this pipeline: no
  licensed source carries one.
- `ics.py` — RFC 5545 `.ics` emission. Each calendar is named
  "\<team or league\> (Next Home Game)" (`X-WR-CALNAME` and RFC 7986
  `NAME`), says what it holds and links back to its page (`X-WR-CALDESC`,
  `DESCRIPTION`, `URL`, and a last line in every event's description), and
  asks apps to refresh daily (`REFRESH-INTERVAL`, `X-PUBLISHED-TTL`). None
  of that reaches a UID. UIDs are derived deterministically
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
  reused for league and team pages. It publishes no prices (DECISIONS 0013).
  A game's `buy` key is present and is either its one ticket link or `null`,
  never omitted and never guessed.
- `sellers.py` — where each game's ticket link goes. For a home game of a
  team whose primary seller is known (and is not Ticketmaster, e.g. AXS or
  SeatGeek), it links to that team's page at the seller, with the evidence
  recorded per entry. Otherwise it uses the Ticketmaster event URL, labelled
  with the site it actually points to. `AFFILIATE_LINK_TEMPLATES` is the
  single place an affiliate ID would go. It is empty, and the footer
  disclosure is rendered from it. A link that went through a template also
  carries `rel="sponsored noopener"` (`is_affiliate_link`, applied in
  `site.py`); a plain link carries no `rel` at all. The `.ics` feeds do not
  use this module.
- `analytics.py` — Google Analytics 4 (`../docs/DECISIONS.md` 0012).
  `GA4_MEASUREMENT_ID` is the one place the measurement ID goes (committed:
  it is public); empty means no page carries any analytics. When set, every
  HTML page gets one inline loader in `<head>` that returns before loading
  anything unless the page is on the base URL's own host, the browser
  sends neither Global Privacy Control nor Do Not Track, and the visitor has
  not used the footer's "Opt out of analytics" (a localStorage flag,
  `OPT_OUT_STORAGE_KEY`, that toggles to "Opt back in";
  `tests/test_analytics_opt_out.py`); sets Consent Mode v2
  defaults (ad storage / ad user data / ad personalisation denied everywhere,
  analytics storage denied in the EEA, UK and Switzerland); configures gtag
  with Google signals and ad personalisation off; and records
  `ticket_click` / `calendar_subscribe` events without touching the links.
  The `.ics` feeds and `data/*.json` never see the ID.
- `site.py` — the static HTML generator. No executable `<script>` on any
  page except that GA4 loader (checked by `tests/test_site_html.py` and
  `tests/test_analytics.py`); the one other `<script>` is a JSON-LD data
  block that browsers never run (`structured_data.py`). League and team
  pages are titled "\<name\> \<season\> schedule: add to your calendar",
  with the season taken from the listed games' dates (`site_data.season_label`,
  none when no game is dated), and carry one subscribe button each for
  Google Calendar, Apple Calendar and Outlook (personal and work) above the
  next-home-game hero, which shows the soonest listed game the event name
  says is at home. Also `<link rel="canonical">`,
  a favicon (SVG primary + PNG/apple-touch-icon fallbacks), Open Graph and
  Twitter Card tags — including a real `og:image` per page (the site-wide
  default on the index and on every page without a card of its own, a
  per-league card on the WNBA, NWSL and PWHL league and team pages; AUSL and
  NCAA women's basketball have no card yet, see `assets/` below and
  `CONTRIBUTING.md`) — semantic landmarks, table headers with `scope`,
  link text that names its destination ("Buy tickets for X vs Y on
  \<date\> from SeatGeek, the official seller for … home games", never bare
  "Buy" or "click here"), no price anywhere, a
  literal, non-euphemistic privacy note in the footer that links
  `/privacy/`, and the privacy page itself. Both are rendered from the GA4
  ID, so they say "no analytics" exactly when a build has none.
- `structured_data.py` — schema.org JSON-LD: `WebSite` on the home page,
  `BreadcrumbList` on league and team pages, `SportsTeam` on team pages, and
  a `SportsEvent` for each listed game whose date, time and home side are
  all published — never for a date-TBD or time-TBA game, never with a start
  time filled in, and none on a build that fetched nothing. `eventStatus`
  only when Ticketmaster says cancelled, postponed or rescheduled, which
  the page then shows too.
- `sitemap.py` — `sitemap.xml`, `robots.txt` and `lastmod.json`. A page's
  `<lastmod>` is when its schedule last changed, found by comparing this
  build's content fingerprints with the live site's own `lastmod.json`;
  unknown means no `<lastmod>`, never the build time.
- `validate_seo.py` — `make validate-seo`: sitemap, robots.txt, titles,
  descriptions, canonicals and every structured-data node checked against
  the page's own data, before deploy.
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
absence discipline, and the generated HTML (no `<script>` tags anywhere
without a GA4 ID, no price or price promise on any page even when
Ticketmaster sent one, table headers,
link text, canonical/favicon/OG/Twitter-card tags — including that each
page's `og:image` is the real, correctly-sized card for that page type,
not one generic image repeated everywhere — the privacy note, and that
`build.py` actually copies the favicon and social-card bytes into `--out`
at the real dimensions those tags promise, failing loudly if one is
missing).

`tests/test_analytics.py` covers GA4 (`../docs/DECISIONS.md` 0012): a build
with no ID emits no GA on any page; a build with an ID puts the same guarded
loader in the `<head>` of every page the build writes (the index, the privacy,
accessibility and 404 pages, one page per league and one per team); the `.ics`
feeds are byte-identical with and without an ID (and
`data/*.json` too, apart from `site.json`'s build timestamp); ticket links
stay plain Ticketmaster URLs; a malformed ID fails the build before anything
is written. The loader itself is executed in Node against stubbed
`window`/`navigator`/`document` objects: under Global Privacy Control, any
of the three Do Not Track spellings, or an off-site hostname it creates no
`dataLayer`, requests nothing and adds no listener; otherwise it sets both
Consent Mode defaults before `config`, loads gtag.js, and records
`ticket_click`/`calendar_subscribe` without cancelling or rewriting the
link. (Node is set up in CI; locally the Node tests skip if it is missing,
and in CI they fail instead.) Its negative controls run in the suite on
every build: each breaks a page or the loader (drops the GPC or DNT guard,
turns Google signals on, adds a static `<script src>`, removes the tag),
first asserts the break actually landed, and then asserts the checker
rejects it.

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
CI re-runs. The same cycle was run on 2026-09-17 for three GA4 checks: an
unset ID that still emitted a tag, the GPC guard removed from the loader,
and the ID written into every `.ics` feed. Each targeted test in
`tests/test_analytics.py` went RED, and each file was restored to its
pre-sabotage `git hash-object`.

Also run (not part of `pytest`, but part of `make verify` and so CI-gated on
every push/PR, not a one-time manual check):

- `make validate-html` — `html5validator` against every generated page of
  the degraded, no-API-key build CI runs: the index, the privacy,
  accessibility and 404 pages, one page per league and one per team, so the
  count follows `config.py` (`find dist -name '*.html' | wc -l` prints it).
- `make a11y` — `pa11y --standard WCAG2AA` (via `pa11y-ci`, 5 pages at a
  time) against every generated page (the same ones) **plus** two fixture
  pages rendered with a populated games table (a priced game, an unpriced
  game, and a date-TBD game together — the exact shape
  `tests/test_site_html.py::_pages()` builds and asserts on, reused via
  `scripts/render_a11y_fixtures.py` rather than duplicated) — these two exist
  because the degraded build CI runs never has a non-empty games table to
  check. That is two more pages than the build alone writes; see
  `pipeline/Makefile`'s `a11y` target and `pipeline/pa11y-ci.config.json` for
  exactly what runs. The URL list is rebuilt from
  `find dist -name '*.html'` on every run, and
  `scripts/check_a11y_coverage.py` then fails the gate unless pa11y-ci's own
  JSON report names every URL it was handed, all passing, and that list
  covers every index, privacy, accessibility, 404, league and team page
  `wsc_pipeline.config` says the build must produce, so a faster sweep can't
  quietly check fewer pages.
  The pages carry the GA4 loader (the committed ID is set), but it returns
  before loading anything on 127.0.0.1, so the sweep never contacts Google.
  `make a11y` installs its own npm dependency (`make install-a11y`); plain
  `make install`, which the nightly deploy runs, is Python-only.

No human screen-reader walkthrough has been performed; that stays a
manually-tracked open item (#5), separate from the two automated,
CI-enforced checks above.
