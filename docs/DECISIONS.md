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

*Superseded 2026-09-17 by 0012 (Google Analytics 4 on the HTML pages).*

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

*Superseded for display by 0013 (2026-09-17): the site shows no prices.*

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
*Status, 2026-09-17:* registered 2026-09-14 and live on GitHub Pages; see
README "Where it runs" for what is still open (www record, HTTPS
enforcement).
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

## 0010 — Fifth tracked league: NCAA women's basketball, Big Ten only (2026-09-16)

NCAA women's basketball is added as a tracked league, same Ticketmaster-only
pattern as WNBA/NWSL/PWHL/AUSL, scoped to the Big Ten's 18 teams for the
2026-27 season. Per `docs/LICENSES-AND-ATTRIBUTION.md`'s 2026-09-16
addendum, the original 2026-09-13 "NCAA women's sports" entry bundled two
different things under one verdict: NCAA Content's own commercial-use ban
(real, but moot -- no league's own site is ever read, per 0006) and "no
unified feed across ~350 schools" (also moot under the same reasoning -- no
tracked league has ever had a unified feed). Neither was actually the
blocker once separated out.

What was actually checked before adding this league:

1. **Team identity is fixed**, unlike AU's non-softball disciplines -- a
   university's basketball program doesn't get re-drafted weekly. This was
   always true of NCAA basketball; the original entry didn't turn on it.
2. **NCAA/school trademark posture** (checked fresh, since this is the
   first governing-body-plus-member-institutions source examined): NCAA.org
   and a university athletics licensing page both restrict marks/logos and
   commercial reproduction of their own content, same shape as every other
   league -- moot, since neither is scraped. Naming a team in text (never
   its logo) to search and link to Ticketmaster is nominative fair use,
   the same legal footing every existing tracked-league team name already
   stands on.
3. **Ticketmaster coverage, verified empirically, not assumed.** Six Big
   Ten programs spot-checked (Iowa, Ohio State, Indiana, Nebraska,
   Michigan, Rutgers) each have a dedicated Ticketmaster artist page
   titled "<School> Womens Basketball", several carrying real dated
   2026-27 events; South Carolina's own athletics department confirms
   Ticketmaster as its official single-game-ticket seller. This rules out
   the real risk that college tickets sell only through university box
   offices (Paciolan/Evenue systems exist alongside Ticketmaster, not
   instead of it).

Team names are suffixed "Womens Basketball" in `config.py` (e.g. "Iowa
Hawkeyes Womens Basketball") because, unlike a WNBA/NWSL/PWHL/AUSL city
franchise, a bare school nickname is shared across every sport that school
fields -- this matches Ticketmaster's own artist-page naming, not an
invented convention.

The Big Ten, not all ~350 Division I programs, is the starting scope: it is
the conference with the most direct positive coverage evidence gathered
here, not the only eligible one. The other ~332 programs and every NCAA
women's sport besides basketball remain in `LEAGUES_EXAMINED_NOT_INCLUDED`
-- not a licensing gap, just not yet scoped, same bucket as Unrivaled and
LOVB.

## 0011 — WPBL examined and not added: zero Ticketmaster coverage, not a licensing block (2026-09-16)

WPBL (Women's Pro Baseball League) — a real, currently operating
professional women's baseball league that began its inaugural season
2026-08-01, with four fixed city-franchise teams (Boston Hunters, New York
Heights, Los Angeles Queens, San Francisco Firebells) — was evaluated as a
further tracked league and **not added**.

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

## 0012 — Google Analytics 4 on the HTML pages; calendar feeds stay untracked (2026-09-17)

Supersedes 0002. Numbered 0012, not 0011: open PR #5 (WPBL) already uses
0011 on its branch and open PR #6 (USL W League) uses 0009, which main
already has, so 0011 is not free once #5 lands.

**Decision (owner, 2026-09-17):** Google Analytics 4 on every public site in
the portfolio, with privacy pages updated to match, chosen knowing it
reverses this product's recorded "none" posture (0002) and its "No account,
no tracking" copy. Property 554878764, web stream measurement ID
`G-YKGPZ76LVE`, provisioned 2026-09-17 with 14-month event-data retention
and Google signals disabled on the property itself.

What ships (`pipeline/src/wsc_pipeline/analytics.py`):

- **The ID is site configuration**, committed as
  `analytics.GA4_MEASUREMENT_ID` (it is public; every page that loads GA
  sends it to the browser). Empty means the build emits no GA at all: no
  `<script>`, no reference to Google, and the footer and `/privacy/` say the
  site runs no analytics. A malformed ID fails the build.
- **HTML pages only.** One inline loader in the `<head>` of every generated
  page: home, privacy, 404, every league and every team page.
- **GPC and DNT honoured by not loading GA at all.** When
  `navigator.globalPrivacyControl === true`, or Do Not Track is on
  (`navigator.doNotTrack`, `window.doNotTrack` or `navigator.msDoNotTrack`
  is `"1"` or `"yes"`), the loader returns before `dataLayer`, the gtag.js
  request, or any listener exists: no request to Google, no cookie.
- **Ads features off.** `gtag('config', …)` sets
  `allow_google_signals: false` and `allow_ad_personalization_signals:
  false`. Consent Mode v2 defaults deny `ad_storage`, `ad_user_data` and
  `ad_personalization` everywhere; `analytics_storage` is denied for the
  EEA, the UK and Switzerland (via `region`, 32 country codes) and granted
  elsewhere. There is no consent banner, so those defaults are never
  updated: visitors in those regions get no GA cookies, though gtag.js
  still sends Google cookieless measurement pings.
- **Production host only.** The loader also returns unless it is served from
  the base URL's own hostname, so local previews and CI's pa11y sweep (over
  127.0.0.1) never load GA or send hits to the real property.
- **Clicks are observed, links are not touched.** A click listener sends
  `ticket_click` (a link in `<main>` to a `ticketmaster.*` host) and
  `calendar_subscribe` (a `webcal:` link or a path ending `.ics`). Ticket
  links stay the plain URLs Ticketmaster publishes, never wrapped in a GA
  or other redirect.
- **Feeds untracked.** The `.ics` feeds and `data/*.json` are written
  without the ID and are byte-identical with or without it
  (`tests/test_analytics.py`); no tracking of any kind is added to a feed.

Where 0002 said "Affiliate revenue is plain URLs with an affiliate id, which
needs no script and no cookie on our side": still true of the affiliate
link itself. The analytics script and its cookies are a separate, measured
choice made here. Likewise 0001's "nothing leaves your browser" no longer
describes the pages (it still describes the feeds); 0001's static,
no-runtime architecture is unchanged.

`README.md`, the site footer, the index lede, the new `/privacy/` page
(linked from every footer) and the repo description were updated so no
"no tracking" / "no cookies" claim remains false.

*Addendum 2026-09-18 (owner decision, all four sites):* every footer carries
a public "Opt out of analytics" control, remembered per browser in
localStorage (`nexthomegame:analytics-opt-out` = `"1"`, never to be renamed)
and checked before gtag.js is requested. It toggles to "Opt back in", which
removes the flag, and `/privacy/` describes it. Opting out also sets
Google's `window["ga-disable-<ID>"]` property for the page it happens on.
It is a `<button>` rather than a link, because it changes a setting instead
of navigating, and it stays `hidden` without JavaScript, where GA never runs
either. The cookieless pings that EEA/UK/CH visitors' browsers still send
under denied `analytics_storage` are accepted as they are.

## 0013 — Calendar-first, no prices; each ticket link goes to the home team's seller (2026-09-17)

Owner decision, 2026-09-17. The site stops showing ticket prices and stops
promising them. It leads with the subscribable calendars instead.

Why:

- **The promise was empty everywhere.** The homepage, meta descriptions and
  social cards promised "the Ticketmaster price range before you click".
  The live build of 2026-09-17 had a price on 0 of 182 rows (about 105
  unique games): Ticketmaster Discovery returned no `priceRanges` for any
  of them. A promise that is empty on every row is the "absence rendered as
  a value" defect in the headline.
- **No other price source clears DECISIONS 0003 without contacting
  someone.** [moved to private strategy notes]
- **A price shown would have to be the all-in price** under 16 CFR 464.2.
  Ticketmaster's face-value ranges would not meet that.

What changes:

- **Pages carry no price anywhere:** no price column, no hero price, no
  price copy, no price in meta descriptions, social cards or the site
  JSON. Team pages put the subscribe block first.
- **Each game keeps one plain "Buy tickets" link** (`sellers.py`).
  - Where the home team's primary seller is known and is not Ticketmaster,
    the link goes to that team's page at that seller:
    - AXS: Las Vegas Aces, Los Angeles Sparks;
    - SeatGeek: Portland Thorns, Utah Royals, Minnesota Frost.

    Each entry records its evidence and the date it was checked. Per-game
    URLs there are unknown, so the link text names the seller and says it
    is that team's official seller.
  - Otherwise the link is Ticketmaster's event URL, labelled with the host
    it actually points to.
  - Oakland Soul (SeatGeek) is not a tracked team (USL W League is not
    added). AUSL's primary seller is the league's own ticketing, with
    StubHub as its marketplace, so AUSL keeps the event link for now.
- **Links are plain, with no affiliate IDs.**
  `sellers.AFFILIATE_LINK_TEMPLATES` is the single place one would be added
  once [moved to private strategy notes]. The footer's disclosure is rendered from that same table,
  so it says "affiliate" exactly when a link is one. Today it says the
  links are plain and the site is not paid for them.
- **The `.ics` feeds do not change.** They still carry the Ticketmaster
  event URL and the existing description line. A build from the same data
  on `main` and on this change produced byte-identical feeds.

Revisit if a price source passes 0003 with an all-in total price that
allows nightly caching, indexed display, and `.ics` redistribution.

## 0014 — USL W League examined, NOT added: Ticketmaster coverage fails, not licensing (2026-09-16)

USL W League was evaluated as a further tracked league, same
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

## 0015 — Calendar events carry an estimated end time, labeled as an estimate (2026-09-19)

Ticketmaster publishes a start time and never an end. An event with no
`DTEND` or `DURATION` ends the moment it starts (RFC 5545 §3.6.1), which some
calendar apps draw as a zero-length marker. The maintainer decided the feeds
should carry an estimated end rather than leave it out (issue #20).

- Each timed event gets a `DTEND` one assumed game length after its start.
  The length is per sport, in `config.GAME_DURATIONS` (basketball 2 h 30 min,
  soccer 2 h, ice hockey 2 h 30 min, softball 2 h), and a league can override
  it with `League.game_duration`. The values are rounded-up typical lengths
  chosen as defaults, not measurements; change them in one place.
- Every event with a `DTEND` says so in its description: "End time estimated;
  not published by the ticket source." `validate_ics` requires the line
  wherever a `DTEND` is written and a `DTEND` wherever the line appears.
- A sport with no entry in the table gets no `DTEND` at all, never a guessed
  one, and a test fails when a tracked league's sport has no entry.
- No `DTEND` is written for a game whose start time is not announced (0016).
- `DTSTAMP` is the build's fetch time, passed into `build_calendar`. There
  is still no `SEQUENCE` or `LAST-MODIFIED`: either would need the previous
  published data to compare against, and a value derived without it would
  change on every build for every event.

## 0016 — Games with a known date and no announced time are all-day calendar events (2026-09-19)

The README used to say games with no exact start were left out of the feeds
because "RFC 5545 has no clean TBD representation". It has one for a known
date with no time: a `DTSTART;VALUE=DATE`, which calendar apps draw as an
all-day event. On the live site most of the Big Ten women's basketball
schedule is time-TBA, so its feeds carried a handful of events (issue #18).
The maintainer decided to include these games.

- A game with a real date and no announced time (`time_tba`, or no instant and
  no local time) is an all-day event on its local date. Its summary ends with
  " (time TBA)" and its description says the time is not announced. It has no
  `DTEND` and no "end estimated" line (0015), and no time is shown or implied.
- Its UID is `tm-<event id>@...` like every event's, so when Ticketmaster
  lists the time it is the same event with a date-time start and a subscriber's
  calendar can update it in place. **How Apple, Google and Outlook calendars
  treat a change from an all-day start to a timed one under the same UID has
  not been tested.**
- A `time_tba` game is never published as a timed event, even when
  Ticketmaster sends a placeholder `dateTime` with it (`normalize.feed_start`).
- A game with no date at all (`date_tbd`) stays out of the feeds, and the
  page still says why. A game with a local time but no exact instant also
  stays out, as before.
- The page's `in_calendar_feed` and the feed read the same rule, so they
  agree, and `validate_ics` fails on any game whose feed entry shows a time
  its page says is not announced.
