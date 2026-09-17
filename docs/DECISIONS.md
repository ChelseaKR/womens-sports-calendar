# Decisions

## 0001 — Static site + nightly pipeline, no runtime (2026-09-13)

A Python pipeline emits `.ics` files and static pages on a schedule; the site
is files on a CDN. Nothing runs when a visitor arrives. This is what makes
"no weekly human effort" and "nothing leaves your browser" both true, and it
is the cheapest thing to run.

## 0002 — Data posture: none, revisit with data (2026-09-13)

Per DATA-GOVERNANCE-STANDARD §4a the declared posture is "none": no analytics,
no cookies, no third-party script. Affiliate revenue is plain URLs with an
affiliate id, which needs no script and no cookie on our side. The portfolio's
other products adopted analytics the same day; this one may later, as a
per-product choice, if the numbers justify it.

## 0003 — Licence before bytes (2026-09-13)

A league's schedule is used only if its published terms permit reuse in a
commercial (affiliate-monetised) product, quoted verbatim in
`docs/LICENSES-AND-ATTRIBUTION.md`. The research found stats terms are hostile
(WNBA §9, ESPN, PWHL clause xi); whether the same clauses reach a *schedule*
is the first thing to establish, per league. Unknown means not used. Nobody is
contacted.

## 0004 — Ticket prices from Ticketmaster Discovery only (2026-09-13)

One price source, read under its API terms, displayed as the range Ticketmaster
publishes, never scraped from a checkout page. Where a game has no Ticketmaster
event, the site says so; it never guesses a price.

## 0005 — Name and domain: undecided

Owner's call. Default hosting is a subdomain of chelseakr.com.

## 0006 — No league schedule source passed licensing; Ticketmaster Discovery is the sole data source (2026-09-13)

Per `docs/LICENSES-AND-ATTRIBUTION.md` §0–1: all seven leagues examined
(WNBA, PWHL, NWSL, NCAA women's, Unrivaled, LOVB, Athletes Unlimited) fail the
licence-before-bytes test — six have terms that explicitly ban automated
and/or commercial reuse of site content (which covers a schedule; a game
schedule being "facts" is not a licence per the brief), and NWSL's terms page
is an unreadable JavaScript shell, which DECISIONS 0003 treats as "unknown"
and therefore not used. There is no "join a league feed to Ticketmaster by
venue+date" step, because there is no licence-clean league feed to join.

Instead, the pipeline queries the Ticketmaster Discovery API directly per
tracked team (keyword search, `classificationName=Sports`), and each
Ticketmaster event *is* the schedule entry: a home game, its venue, its
start time, and — where published — its price range. This still satisfies
the README's "per league and per team `.ics`" shape and DECISIONS 0004
("ticket prices from Ticketmaster Discovery only"); it changes only which
step produces the game list. Broadcaster is never populated — no licensed
source carries it — and every league's calendar note says plainly that its
own schedule was not used and why, rather than silently thinning out.

## 0007 — Domain: nexthomegame.com (2026-09-14)

[moved to private strategy notes] This resolves the domain
half of 0005; the product's display name is unchanged (still
`womens-sports-calendar (working name)`, README.md) and remains open
separately.

Not registered yet — that is an owner step (registrar, DNS, GitHub Pages
custom-domain configuration, `SITE_BASE_URL` repo variable), not done here.
Placeholder `calendar.chelseakr.com` references in the pipeline's default
`--base-url`, CI, and docs are updated to `https://nexthomegame.com`
accordingly; production behavior does not change until the repo variable is
actually set and DNS points at GitHub Pages.

## 0008 — Fourth tracked league: AUSL, not all of Athletes Unlimited (2026-09-14)

AUSL (Athletes Unlimited Softball League) is added as a tracked league, same
Ticketmaster-only pattern as WNBA/NWSL/PWHL: six team names hand-authored
into `pipeline/src/wsc_pipeline/config.py`, no league schedule feed read. Per
`docs/LICENSES-AND-ATTRIBUTION.md`'s 2026-09-14 addendum, licensing was never
the blocker (AUSL's own site fails the same test every league's does, and
was already failing it under the generic "Athletes Unlimited" entry) — the
real gap was that "Athletes Unlimited" is a four-sport brand, and only its
softball property has fixed, season-long team franchises to keyword-search
for. AU's other three disciplines (basketball, lacrosse, volleyball) use a
single-host-city season with teams re-drafted weekly by rotating captains,
with no stable team name to configure, and remain untracked for that
structural reason. `LEAGUES_EXAMINED_NOT_INCLUDED`'s "Athletes Unlimited"
entry is renamed accordingly to name only those three disciplines.

## 0009 — USL W League examined, NOT added: Ticketmaster coverage fails, not licensing (2026-09-16)

USL W League was evaluated as a fifth tracked league, same
research-before-bytes process as every league above, and does not become a
tracked league. Per `docs/LICENSES-AND-ATTRIBUTION.md`'s 2026-09-16 entry
and addendum:

- **Licensing was checked and is moot**, exactly as for every tracked
  league: uslsoccer.com's Terms of Use (governing all USL Family
  properties, USL W-League named explicitly) ban automated commercial
  collection and limit Content to personal/non-commercial use, but this
  was never going to matter — the pipeline never reads a league's own
  site, only Ticketmaster by team keyword (0006).
- **The real blocker is Ticketmaster coverage, checked empirically.** The
  2026 season fields 96 clubs across 16 divisions — a much larger and more
  volatile roster than any currently-tracked league (WNBA 15, NWSL 16,
  PWHL 12, AUSL 6 teams). A 16-club spot-check spanning both
  pro-affiliated clubs (the best case for Ticketmaster coverage) and small
  independent clubs found **zero** clubs with a confirmed, correctly-scoped,
  current Ticketmaster listing. The three clubs with any Ticketmaster
  presence at all either had zero events listed or listed only their
  affiliated men's team's games — a worse failure mode than plain absence,
  since a naive keyword match could surface the wrong team's games under
  this product's women's-league label.
- **Two 2026 USL W League clubs (Racing Louisville FC, North Carolina
  Courage U23) share or nearly share a name with an already-tracked NWSL
  franchise**, a separate structural problem that would need its own fix
  even if coverage were otherwise solid.
- With 96 clubs and a uniformly negative sample, no scoped subset (the way
  NCAA scoped to Big Ten, or AUSL scoped to six franchises) presents
  itself. `config.py`'s `LEAGUES_EXAMINED_NOT_INCLUDED` gets a "USL W
  League" entry; `LEAGUES` is unchanged. Revisit only if Ticketmaster's own
  listings for these clubs change.
