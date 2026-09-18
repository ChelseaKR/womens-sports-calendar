# womens-sports-calendar (working name)

Subscribable `.ics` calendar feeds per league and team for women's pro and
college sports, plus a ticket-price finder, built nightly from the
Ticketmaster Discovery API. No account, no tracking, no script from anyone
but us on the page. Monetised only by plain affiliate URLs.

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
  team: the subscribe link, the next games, the price range, and one
  affiliate link per game. No JavaScript that talks to anyone but us; no
  cookies; no analytics; zero `<script>` tags on any page.
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
