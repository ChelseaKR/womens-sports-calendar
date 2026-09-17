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

## 0009 — Validate Discovery API keyword-search results against the event's own participants (2026-09-16)

A production bug (NWSL's "Angel City" team page showing a WHL hockey game,
"Everett Silvertips vs Tri-City Americans" at "Angel Of The Winds Arena")
showed that Discovery API's `keyword` search is a broad full-text match, not
an exact team/attraction-name match — it matches on venue names and other
metadata, not just who is actually playing. `classificationName=Sports`
(already in place since 0006) only narrows the segment; it does nothing
against a wrong sport within Sports, or a same-sport wrong team (confirmed
separately live: a "Bay FC" search also returned a real match between two
unrelated clubs, "Tampa Bay Sun FC" and "DC Power FC").

Every raw Discovery API result is now checked with
`normalize.team_is_participant()` before being trusted: the event's own name
and `_embedded.attractions` (never the venue) must contain the searched
team's name as a contiguous phrase, in either direction (so a real
Ticketmaster shorthand like "Mystics" still matches "Washington Mystics",
without accepting a same-city, different-team collision like "Minnesota
Timberwolves" for "Minnesota Frost"). A result that fails is dropped, not
published, and counted per team in the coverage report (`teams with
mismatched events`) so the exclusion is visible rather than silent. Checked
against a full pull of nexthomegame.com's live production data
(2026-09-16): 140 of 304 published games across all four leagues were
false-positive keyword matches (wrong sport, wrong team, or non-sporting
events -- horse racing, MMA, concerts) and are now excluded; the 2
legitimate abbreviated-name games in that pull still pass.

Known residual gap: two teams in different leagues/sports that share an
identical or near-identical name (a hypothetical NWSL "Utah Royals" vs
MLB's "Kansas City Royals") could still collide on the "Royals" phrase
alone. Closing that fully needs a verified sport/genre check using
Discovery API's per-event `classifications` field — not added here because
its exact genre taxonomy values were not confirmed against a live call in
this session (see PR description), and guessing at that string risks
silently returning zero results for a team, which is worse than the residual
gap it would close.

## 0011 — WPBL examined and not added: zero Ticketmaster coverage, not a licensing block (2026-09-16)

WPBL (Women's Pro Baseball League) — a real, currently operating
professional women's baseball league that began its inaugural season
2026-08-01, with four fixed city-franchise teams (Boston Hunters, New York
Heights, Los Angeles Queens, San Francisco Firebells) — was evaluated as a
fifth tracked league and **not added**.

Team-identity shape passed (fixed, season-long rosters, same as
WNBA/NWSL/PWHL/AUSL, unlike AU's redrafted disciplines). Licensing turned
out to be moot, same as every other league (DECISIONS 0006: no league's own
site is ever read) — and WPBL's own site is, if anything, the *least*
restrictive found in this whole survey: no Terms of Use page exists at all,
its Privacy Policy has no automated-access or commercial-use clause, and
its robots.txt is a permissive WordPress default. None of that matters,
because the actual blocker is structural and empirical: WPBL's own tickets
page names **TicketReturn** (ticketreturn.com), not Ticketmaster, as its
ticketing partner, and a direct Ticketmaster search for all four 2026 teams
plus the bare league name returned **zero results across the board** —
100% of the league checked, not a sample, confirmed 2026-09-16. This is a
clean, total absence (contrast the AUSL addition, DECISIONS 0008, where a
spot-check found real per-venue inventory before it was tracked). Adding
WPBL under the current Ticketmaster-only data model (DECISIONS 0006) would
ship team and league pages, and `.ics` feeds, that can never contain a real
game or price — the "absence rendered as a value" failure mode this
portfolio treats as a real defect elsewhere, not an acceptable degraded
state to ship on purpose.

Recorded in `docs/LICENSES-AND-ATTRIBUTION.md` §1 (WPBL entry) and §5
(summary table); `LEAGUES_EXAMINED_NOT_INCLUDED` in
`pipeline/src/wsc_pipeline/config.py` gets a WPBL entry alongside NCAA/
Unrivaled/LOVB. Nothing in `config.py`'s tracked `LEAGUES` tuple changes.
Re-check if WPBL ever signs with Ticketmaster or a future season adds
teams/venues that do.
