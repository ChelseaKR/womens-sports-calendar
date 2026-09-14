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
