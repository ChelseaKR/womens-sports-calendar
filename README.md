# womens-sports-calendar (working name)

Subscribable `.ics` calendar feeds per league and team for women's pro sports,
plus a ticket-price finder, built nightly from the leagues' own public schedule
feeds and the Ticketmaster Discovery API. No account, no tracking, no script
from anyone but us on the page. Monetised only by plain affiliate URLs.

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

## Not yet decided

The display name is still a working name (`womens-sports-calendar`). The
domain is decided — `nexthomegame.com`, see `docs/DECISIONS.md` 0007 — but
not yet registered; hosting configuration (Pages, DNS, `SITE_BASE_URL`) is
an owner step, not done here.
