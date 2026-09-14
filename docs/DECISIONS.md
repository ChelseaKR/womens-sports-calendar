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
