# Contributing

This is a public, single-maintainer repository. Changes arrive as pull
requests against `main`; nothing is pushed to `main` directly.

## Set up

To propose a change, fork the repository on GitHub and clone your fork (the
HTTPS URL of either works without an SSH key):

```sh
git clone https://github.com/<your-account>/womens-sports-calendar.git
cd womens-sports-calendar
```

- [uv](https://docs.astral.sh/uv/) 0.11 or newer (it fetches Python 3.12 from
  `pipeline/.python-version`).
- Node 22 for the accessibility and performance checks (puppeteer
  downloads its own Chrome on first install).
- Once per clone, install the hooks:

  ```sh
  pre-commit install && pre-commit install --hook-type pre-push
  ```

  gitleaks, ruff and ruff-format run on commit, and mypy runs on push
  (`.pre-commit-config.yaml`).

## The one local gate: `make verify`

```sh
make verify
```

It runs every check CI runs, in the same order, from the repository root:
the lockfile drift check, ruff, ruff format, mypy --strict, the
marker check, the tests with an 85% branch-coverage floor, a wheel build, a
degraded build of the site, HTML validation, `.ics` validation, the search
checks (sitemap, robots.txt, titles, structured data: `make validate-seo`),
the same HTML, `.ics` and search checks on a populated fixture site
(`make validate-fixture-site`), the accessibility sweep over every page, and
pip-audit. CI runs exactly this
target (`.github/workflows/ci.yml`). If `make verify` is green locally, the
`verify` check should be green too. The security scans (gitleaks, Semgrep,
OSV-Scanner) run in `.github/workflows/security.yml`.

A build without `TICKETMASTER_API_KEY` fetches nothing, and its pages say
so. That's the mode CI uses. Never paste a key into a file; use the
environment.

## Pull requests

- One concern per PR. Stage files by name; never `git add -A` or `git add .`.
- Commit subjects are lowercase conventional commits (`fix(site): ...`,
  `feat(data): ...`).
- Fill in the PR template's Definition of Done checklist
  (`DEFINITION_OF_DONE.md`).
- A change to a guardrail needs an ADR in `docs/adr/`. The guardrails are:
  a failed or empty fetch never publishes; absence is never shown as a
  value; a `permissions:` block; a coverage, accessibility or performance
  threshold. Declaring a standard N/A needs one too.
- Add a line to `CHANGELOG.md` under Unreleased for any user-visible change.
- New data sources follow "licence before bytes" (`docs/DECISIONS.md` 0003):
  the terms are read and quoted in `docs/LICENSES-AND-ATTRIBUTION.md`, and a
  data card is added in `docs/data/`, before anything is fetched.

## Adding a team or a league

The registry is data in `pipeline/src/wsc_pipeline/config.py`, but a change
there is not only a data change: the places below move with it. `make verify`
catches most of a miss, not all.

**A team in a league that is already tracked**

- [ ] Add the name to the league's `_teams(...)` in `config.py`, spelled as
  Ticketmaster spells it (the keyword search and the participant check match
  on it). The slug is derived from the name (lowercase, spaces to hyphens,
  dots dropped) and becomes the page `/<league>/<team>/` and the feed
  `/ics/<league>/<team>.ics`. Once published, a slug never changes: people
  subscribe to the feed URL, so a rename or removal is a decision to make and
  record in `docs/DECISIONS.md`, not a cleanup.
- [ ] Check the team really has upcoming games on Ticketmaster before adding
  it. A team with none publishes a page and a feed with no games in them.
- [ ] If another team's name contains the new name as a phrase ("Monterey Bay
  FC" contains "Bay FC"), add the longer name to `KEYWORD_COLLISIONS`.
- [ ] If the team's own ticket seller is not Ticketmaster, add it to
  `PRIMARY_SELLERS` in `sellers.py` with the evidence and the date checked.
  Without an entry the link is the Ticketmaster event URL.
- [ ] Update the tests that count a league's teams: `tests/test_config.py`
  pins AUSL at 6 and NCAA women's basketball at 18. The build writes the
  pages and feeds from `config.py` (the sitemap lists the pages it wrote),
  and the accessibility coverage check and the analytics tests derive their
  page lists from it, so no page count is written down in the code.
- [ ] Add a line to `CHANGELOG.md` under Unreleased.

**A new league**

- [ ] Do everything above for each of its teams, with a new `League(...)` in
  `LEAGUES`. Its `slug` is the page `/<slug>/` and the feed `/ics/<slug>.ics`,
  so it is permanent too. `schedule_source_used` stays `False` and
  `schedule_source_note` says why (a test requires a note); `sport` and
  `organization_name` feed the structured data.
- [ ] Terms and coverage before any page (`docs/DECISIONS.md` 0003). Read the
  league's terms and check its Ticketmaster coverage, then record the reading in
  `docs/LICENSES-AND-ATTRIBUTION.md` (section 1, dated, with the clauses
  quoted) and the decision in the next number of `docs/DECISIONS.md`. The data
  itself still comes only from the Ticketmaster Discovery API, whose data card
  (`docs/data/ticketmaster-discovery-api.md`) then already applies; any other
  source needs its own card in `docs/data/` first
  (`pipeline/tests/test_provenance.py`).
- [ ] The social card, registered in three files: `LEAGUE_OG_IMAGES` in
  `site.py` (the file and its alt text), `STATIC_ASSET_FILES` in `build.py`
  (the build fails if a listed file is missing), and `LEAGUE_GLYPHS`, `GLYPHS`
  (a glyph function for the sport) and `LEAGUE_NAMES` in
  `pipeline/scripts/render_social_assets.py`, which renders
  `og-image-<slug>.svg` and `.png` into `pipeline/assets/` (it needs
  `rsvg-convert`; commit both files). Then add the new file to the lists in
  `tests/test_build.py::test_favicon_and_social_card_assets_are_copied_into_the_build`
  and, to cover the league's pages, `tests/test_site_html.py`. Designing the
  artwork is its own change: a league without a card falls back to the
  generic card (`og-image.png`), which is what AUSL and NCAA women's
  basketball use today. That card's alt text (`DEFAULT_OG_IMAGE_ALT`) and
  its subtitle name only WNBA, NWSL and PWHL, so list the missing card in
  the pull request.
- [ ] If you examined a league and decided not to add it, record it instead:
  an entry in `LEAGUES_EXAMINED_NOT_INCLUDED` (`config.py`) that names the
  real reason, the same two documents as above, and the counts that are
  written by hand: `tests/test_config.py` and `tests/test_build.py` count the
  entries, and `coverage.py` prints a "Leagues examined for licensing" number.
- [ ] Say in the pull request how the league's pages will look on day one,
  including a league that is between seasons and has no games yet, and that
  no existing feed URL or event `UID` changes.

## Standards

The portfolio standards are vendored, unedited, at `docs/standards/`
(v2.0.0; `.standards-version`). Renovate proposes upgrades. Never
hand-edit them. The README's Standards Conformance table says which
standards apply, and links the open issue for each gap.
