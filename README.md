# womens-sports-calendar (working name)

Subscribable `.ics` calendar feeds per league and team for women's pro and
college sports, built nightly from the Ticketmaster Discovery API, with one
plain "Buy tickets" link per game to the home team's ticket seller. No
account. Calendar-first and price-free since 2026-09-17
(`docs/DECISIONS.md` 0013): no licence-clean price source exists, and the old
price promise was empty on every game. Any revenue would come only from
affiliate links, and none is active yet. The web pages use Google Analytics 4
(not loaded under Global Privacy Control or Do Not Track, ads features off;
`docs/DECISIONS.md` 0012); the calendar feeds carry no tracking of any kind.

[moved to private strategy notes]

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
  team: the subscribe link first, then the next games, each with one plain
  ticket link (`pipeline/src/wsc_pipeline/sellers.py`) and no prices, plus
  `/privacy/`. The only script is one inline
  Google Analytics 4 loader per page, emitted only while
  `pipeline/src/wsc_pipeline/analytics.py`'s `GA4_MEASUREMENT_ID` is set
  (it is: `G-YKGPZ76LVE`); it loads nothing under Global Privacy Control or
  Do Not Track, turns Google signals and ad personalisation off, and denies
  analytics storage for the EEA, UK and Switzerland. The `.ics` feeds are
  never tracked.
- `docs/` — research, decisions, licences and attributions.
- `.github/workflows/` — `ci.yml` (tests + a degraded-mode build + HTML
  validation on every push/PR) and `pages.yml` (the nightly + manual build
  and GitHub Pages deploy).

## Where it runs

Live at **https://nexthomegame.com** (checked 2026-09-17): the domain was
registered 2026-09-14 (Amazon Registrar, Route 53 DNS), the apex points at
GitHub Pages, the Pages custom domain is set and its certificate is issued,
and `pages.yml` deploys nightly. Still open, all owner steps:
`www.nexthomegame.com` has no DNS record (it needs a `CNAME` to
`chelseakr.github.io`), "Enforce HTTPS" is off (plain `http://` is served
without a redirect), and `SITE_BASE_URL` is unset (the build's default,
`https://nexthomegame.com`, is what is used).

## Not yet decided

The pages say "Next Home Game" (header, `<title>`, `og:site_name`), matching
the domain (`docs/DECISIONS.md` 0007); the repo keeps its working name,
`womens-sports-calendar`.
