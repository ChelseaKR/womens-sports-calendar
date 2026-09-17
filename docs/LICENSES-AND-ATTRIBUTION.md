# Sources, terms, attribution

Read 2026-09-13. Per DECISIONS 0003: a league's schedule is used only if its
published terms permit reuse in a commercial (affiliate-monetised) product.
Unknown means not used. Nobody was contacted — every finding below comes from
fetching the source's own published terms and robots.txt with an identifying
User-Agent (`womens-sports-calendar/0.1 (licence research; +https://github.com/ChelseaKR)`),
one request at a time, ≥1.2s apart. Raw fetched pages are not committed to this
repo (private terms text is not ours to republish verbatim as a full document);
this table quotes the operative clauses and their URLs so the determination is
checkable against the live pages.

## 0. Bottom line

**Every league's own schedule source fails the licence test — either its terms
explicitly ban automated/commercial reuse, or its terms could not be read at
all (JS-rendered, no accessible text).** Zero leagues pass on their own
schedule feed. The Ticketmaster Discovery API is the only source that passes,
and it becomes the *sole* source of game data, not a price overlay joined to a
separately-fetched schedule — see `docs/DECISIONS.md` 0006. **Leagues examined:
8. Leagues in: 0 (own schedule). Games sourced: 100% via Ticketmaster Discovery
API home-game listings, filtered by team keyword.** (WPBL, examined
2026-09-16, is the eighth — licence-wise it is the one outlier with no
restrictive terms found, but it is still not tracked: see its entry in §1 and
`docs/DECISIONS.md` 0009 for the actual, dispositive reason — zero
Ticketmaster coverage.)

## 1. League schedule sources — examined, not used

### WNBA

- **What would be taken:** game date/time, teams, venue, from `https://www.wnba.com/schedule`.
- **Machine-readable feed:** none found. The schedule page is JS-rendered; the
  API backing it is not exposed in the page HTML (confirmed by direct fetch —
  the raw HTML contains a `<a href="/schedule">` link and no embedded JSON/ICS).
- **Terms:** `https://www.wnba.com/terms-of-use`, **Last Updated: June 13, 2023**, read 2026-09-13.
  - §1 (OWNERSHIP AND USE RESTRICTIONS): *"You may not, however, distribute,
    reproduce, republish, upload, display, modify, transmit, reuse, repost,
    link to, or use any materials of the Services for public or commercial
    purposes on any other websites or otherwise without the written permission
    of the Operator."* "Basketball Content" is defined earlier in §1 as
    *"video, audio, photos, text, images, statistics, updated scores, logos and
    other intellectual property related to the WNBA and its teams."*
  - §9 (NBA STATISTICS): *"The NBA Statistics may only be used, displayed, or
    published for legitimate news reporting or private, non-commercial
    purposes... the NBA Statistics may not be used in connection with any
    website, product, or service that features a database... of comprehensive,
    regularly updated statistics."*
  - No clause names "automated," "robot," "spider," "scrape," "crawl," or "bot"
    anywhere in the document — but §1's blanket "no public or commercial
    purposes" ban on *any materials* covers a schedule regardless of how it is
    collected.
  - `https://www.wnba.com/robots.txt` returned **HTTP 403** to our identifying
    UA (as did `/terms-of-use` on a second, unrelated fetch) — the site blocks
    non-browser user agents outright, which is itself informative even though
    robots.txt is a courtesy signal, not a licence.
- **Verdict: NOT USED.** §1's blanket commercial-use ban applies to Basketball
  Content generally (schedule facts are not carved out), there is no official
  machine-readable feed, and the only path to schedule data would be scraping
  a site that returns 403 to automated requests.

### PWHL

- **What would be taken:** game date/time, teams, venue, broadcaster, via the
  HockeyTech feed the league's own site embeds
  (`https://lscluster.hockeytech.com/feed/?feed=modulekit&view=schedule&...&client_code=pwhl&key=...`).
  This is the best machine-readable data of any league surveyed — full JSON,
  broadcasters, ticket URLs — and it is the one that fails hardest on terms.
- **Terms:** `https://www.thepwhl.com/en/terms-of-use`, **Last Updated:
  August 25, 2023**, read 2026-09-13.
  - "PWHL Digital Properties" is defined as *"this Website, applications, and
    all materials contained in this Website and/or otherwise accessible via
    other PWHL-controlled products or services or PWHL-operated interactive
    media locations."* The HockeyTech feed is accessed with a key embedded on
    PWHL's own site and scoped to `client_code=pwhl`; it is a PWHL-controlled
    product under this definition even though the JSON is served from
    `hockeytech.com`.
  - Prohibited-uses list, clause **(xi)**: *"use automated scripts to collect
    information from or otherwise interact with the PWHL Digital
    Properties."* — a blanket ban on exactly the kind of fetch a pipeline runs,
    with no size or frequency threshold.
  - Licence grant: *"Except for downloading one copy of the PWHL Digital
    Properties on any single device for your personal, non-commercial home
    use, you must not reproduce, prepare derivative works based upon,
    distribute, perform or display the PWHL Digital Properties without first
    obtaining the written permission of PWHL."*
  - `https://www.thepwhl.com/robots.txt` is permissive (`Allow: /` for `*`),
    and HockeyTech's own `robots.txt` at `lscluster.hockeytech.com` returns
    404 (no file at all) — neither fact grants a licence; clause (xi) governs
    regardless of robots.txt, and HockeyTech itself publishes no terms of its
    own to fall back on.
- **Verdict: NOT USED.** Clause (xi) is a direct, on-point ban on automated
  collection, and the licence is expressly personal/non-commercial. This
  matches `docs/DECISIONS.md` 0003 and the research doc §0 item 1 — accepting
  this ToS as a contract risk was explicitly rejected in favour of the
  Ticketmaster-only design (research §6 Rank 1).

### NWSL

- **What would be taken:** game date/time, teams, venue, from
  `https://www.nwslsoccer.com/schedule`.
- **Machine-readable feed:** none found. `https://www.nwslsoccer.com/llms.txt`
  exists but is a one-line site description, not a schedule or a licence. The
  only calendar sync available is a third-party ECAL widget
  (`https://nwslsoccer.ecal.com/`), which carries **its own** terms (below) —
  not the league's.
- **Terms:** attempted at three URLs. `/terms-of-service` → 404.
  `/terms-and-conditions` was not tried directly but `/terms` → **HTTP 200,
  but the page is a JavaScript navigation shell**: the "Terms of Use" section
  renders only a heading and links to sibling policy pages (Privacy Policy,
  Copyright Policy, Anti-Harassment Policy); no clause text is present in the
  fetched HTML. Direct fetch cannot read NWSL's terms at all.
- **Verdict: NOT USED — unknown, not hostile.** Per DECISIONS 0003, unknown
  means not used. This matches the research doc's own finding (§4.3, §8):
  "the league's own site is JS-rendered under terms that could not be read."
  Note for a future re-check: if NWSL ever ships a readable terms page or an
  official feed, re-run this determination — do not infer permission from
  the absence of a readable prohibition.

### ECAL (third-party calendar sync used by NWSL and some WNBA teams)

Checked because it is the only "official-adjacent" calendar path for two
leagues. Not a bypass — it is worse than the leagues' own terms.

- **Terms:** `https://ecal.com/terms-of-use/`, **Last updated 3rd June 2025**.
  - *"HyperKu makes the ECAL service available for your personal use only.
    End Users must not display, distribute, license, perform, publish,
    reproduce, duplicate, copy, create derivative works from, modify, sell,
    resell, exploit, transfer or upload for any commercial purposes, any
    portion of the ECAL service."*
  - *"You agree not to (or permit anyone else to) use any data mining,
    robots, scraping or similar data gathering or collection tools or
    methods in connection with the ECAL service."*
- **Verdict: NOT USED.** Personal-use-only and a blanket automated-collection
  ban, same shape as the leagues it fronts for.

### NCAA women's sports

- **What would be taken:** game date/time, teams, venue — no unified official
  feed exists; NCAA women's schedules are split across ~350 individual school
  athletic sites with no common API. Not pursued as a data source for that
  reason alone (fails the pipeline's own "one source, no per-school scraping"
  design before terms are even dispositive).
- **Terms (for the record):** `https://www.ncaa.com/tos`, **last updated
  February 21, 2023**. *"You may not modify, reproduce, publish, transmit,
  participate in the transfer or sale, create derivative works, use for
  commercial purposes, or in any way exploit, any of the NCAA Content, in
  whole or in part except as provided in these Terms of Service."* Same
  blanket-commercial-ban shape as the others.
- **Verdict: NOT USED.** No unified feed, and the terms would forbid
  commercial reuse of NCAA Content in any case.

### Unrivaled (3x3 basketball league)

Checked because research §6 idea 1 named it as a candidate league.

- **Terms:** `https://www.unrivaled.basketball/legal/terms-of-use`,
  **Effective Date: 2025-11-19**.
  - *"will not monitor, gather, copy, or distribute the Content... by using
    any robot, rover, 'bot', spider, scraper, crawler, spyware, engine,
    device, software, extraction tool, or any other automatic device,
    utility, or manual process of any kind."*
  - *"you will not: (i) use the Services for any commercial purpose
    (including, without limitation, for purposes of advertising, soliciting
    funds, collecting product prices, and selling products)."*
- **Verdict: NOT USED.** Both an automated-collection ban and an explicit
  commercial-purpose ban, the latter naming "collecting product prices" —
  precisely this product's shape.

### LOVB (League One Volleyball)

Checked for the same reason.

- **Terms:** `https://www.lovb.com/legal/terms-and-conditions`, **Effective
  August 1, 2022**.
  - Licence grant excludes *"(a) sell, resell or use commercially the
    Services or Site Content... (d) use any data mining, robots or similar
    data gathering or extraction methods."*
- **Verdict: NOT USED.**

### Athletes Unlimited

Checked for the same reason.

- **Terms:** `https://auprosports.com/tos/` (last-updated date not printed on
  the page as fetched).
  - *"you will not access the Site through automated or non-human means,
    whether through a bot, script, or otherwise."*
  - *"Engage in any automated use of the system, such as using scripts...
    or using any data mining, robots, or similar data gathering and
    extraction tools."*
  - *"no part of the Site and no Content or Marks may be copied, reproduced,
    aggregated, republished, uploaded, posted, publicly displayed, encoded,
    translated, transmitted, distributed, sold, licensed, or otherwise
    exploited for any commercial purpose whatsoever."*
  - *"Use the Site as part of any effort to compete with us or otherwise use
    the Site and/or the Content for any revenue-generating endeavor or
    commercial enterprise."*
- **Verdict: NOT USED** — for AU's own site/schedule content, same as WNBA
  and PWHL above. This did not, on its own, rule out tracking an
  Athletes Unlimited property the way WNBA/NWSL/PWHL are tracked (via
  Ticketmaster team-keyword search, never the league's own site) — see
  the 2026-09-14 addendum immediately below.

### Addendum, read 2026-09-14: Athletes Unlimited is a multi-sport brand;
### only AUSL (softball) is added as a tracked league

Re-examined before adding a fourth tracked league, per this repo's
licence-before-bytes rule (`docs/DECISIONS.md` 0003).

- **theausl.com terms, checked separately:** `https://theausl.com/terms-of-service/`,
  **Last Updated: August 12, 2025**, read 2026-09-14. theausl.com is
  Athletes Unlimited's own softball-specific site (operated by
  auprosports.com, confirmed via its footer). Its terms carry the same
  two bans as auprosports.com/tos/ above: *"you will not access the Site
  through automated or non-human means, whether through a bot, script, or
  otherwise"* and *"no part of the Site and no Content or Marks may be
  copied, reproduced, aggregated, republished... for any commercial
  purpose whatsoever."* **Verdict: NOT USED**, identical reasoning and
  outcome to the auprosports.com verdict above — AUSL's own site/schedule
  is not read by this pipeline either.
- **What changed the outcome for AUSL specifically:** per
  `docs/DECISIONS.md` 0006, no league's own schedule source was ever
  going to be used — WNBA, NWSL, and PWHL are already tracked leagues
  despite an identical "NOT USED" verdict for their own sites, because
  tracking means querying Ticketmaster Discovery API by team name, never
  reading the league's site. The open question for Athletes Unlimited was
  never licensing (already settled, same as every other league); it was
  whether AU has a *fixed, season-long team roster* to keyword-search
  for, the same way "Indiana Fever" or "Boston Fleet" names a stable
  franchise all season. Checked 2026-09-14:
  - **AUSL (softball):** as of the 2026 season, six **permanent
    city-based franchises** — Chicago Bandits, Carolina Blaze, Portland
    Cascade, Oklahoma City Spark, Utah Talons, Texas Volts — each with a
    real home venue for a full regular season (June 9 – July 20, 2026).
    Source: `https://en.wikipedia.org/wiki/2026_AUSL_season` and
    `https://www.espn.com/mlb/story/_/id/49000604/athletes-unlimited-softball-league-schedule-teams-players`,
    both read 2026-09-14. This is the same shape as WNBA/NWSL/PWHL, so
    AUSL is added as a tracked league (`pipeline/src/wsc_pipeline/config.py`,
    `docs/DECISIONS.md` 0008). Spot-checked that Ticketmaster carries
    inventory at AUSL venues, e.g. Parkway Bank Sports Complex (Chicago
    Bandits) at `ticketmaster.com/parkway-bank-sports-complex-tickets-rosemont/venue/33188`
    and Dell Diamond (Texas Volts) at
    `ticketmaster.com/the-dell-diamond-tickets-round-rock/venue/99114` —
    both read 2026-09-14 — so the same `keyword=<team name>,
    classificationName=Sports` query WNBA/NWSL/PWHL use would plausibly
    surface AUSL events too.
  - **AU basketball, lacrosse, volleyball:** none has fixed franchises.
    Each plays a single-host-city season (e.g. basketball at Nashville
    Municipal Auditorium) where 40-odd athletes are re-drafted onto
    color- or captain-named teams *every week* (basketball's
    Gold Rush/Rhythm/Glow/Eclipse; lacrosse and volleyball the same
    weekly-captain-draft shape). There is no team name that persists for
    a season, so there is nothing stable to hand-author into
    `config.py` or keyword-search on Ticketmaster the way a city
    franchise's name works — a search for a common word like "Rhythm"
    would also be a poor keyword regardless. **Not configured as tracked
    leagues; this is a structural gap, not a licensing one** (their own
    sites were never going to be read either way, same reasoning as
    every other league in this document).

### WPBL (Women's Pro Baseball League)

Checked 2026-09-16 as a candidate fifth tracked league — its inaugural season
started 2026-08-01, so unlike Unrivaled/LOVB/AU it is a *currently playing*
league, not just announced.

- **What WPBL actually is, confirmed fresh (not assumed):** a real,
  currently operating independent professional women's baseball league (no
  MLB affiliation), co-founded by Justine Siegal, the first woman to coach
  for an MLB organization (then-Oakland Athletics). It is the first
  professional baseball league for women since the All-American Girls
  Professional Baseball League dissolved in 1954. Its inaugural 2026 season
  has four teams with fixed, season-long identities and rosters (players
  drafted centrally in November 2025, signed to one-season contracts, 15
  active + 2 inactive per team) — the same "fixed team roster" shape
  WNBA/NWSL/PWHL/AUSL all have, unlike Athletes Unlimited's other three
  disciplines, which were correctly excluded above for lacking one:
  - Boston Hunters (Boston, MA)
  - New York Heights (New York, NY)
  - Los Angeles Queens (Los Angeles, CA)
  - San Francisco Firebells (San Francisco, CA)

  Structural note: unlike every currently-tracked league, WPBL's 2026 season
  uses a single neutral hub venue — Robin Roberts Stadium in Springfield,
  Illinois — for every game of every team, rather than each team hosting at
  its own city's venue. This does not by itself break the pipeline's query
  mechanism (`pipeline/src/wsc_pipeline/ticketmaster.py` does a team-name
  keyword search with no venue/city filter, so a hub model would not stop a
  match), but it is a real structural difference from the pattern worth
  recording. The league has stated plans to expand to six or eight clubs;
  not evaluated here since only the four 2026 teams currently exist.
  Sources: `https://en.wikipedia.org/wiki/Women%27s_Pro_Baseball_League` and
  `https://www.espn.com/mlb/story/_/id/49533662/2026-womens-pro-baseball-league-where-watch-schedule-more`,
  both read 2026-09-16.
- **Terms:** WPBL's own site carries **no Terms of Use / Terms of Service
  page at all** — `https://www.womensprobaseballleague.com/terms-of-use/`
  and `/terms-of-service/` both → **HTTP 404**, and the footer (fetched
  2026-09-16) links only a Privacy Policy, no separate terms page. The
  Privacy Policy (`https://www.womensprobaseballleague.com/privacy-policy/`,
  no effective date shown, read 2026-09-16) contains no clause on automated
  access, scraping, bots, commercial use, or reproduction/republishing —
  it covers only personal-data handling. `https://www.womensprobaseballleague.com/robots.txt`
  returned **HTTP 200** with a standard, permissive WordPress default
  (`Disallow: /wp-admin/` plus a WPForms block; no blanket disallow, no
  bot-specific rule). This is the **first league in this survey with no
  readable restriction found anywhere** — every other league examined
  either has a blanket commercial/automated-use ban or unreadable terms.
  Per `docs/DECISIONS.md` 0003, "unknown means not used" is about the
  *absence of an affirmative grant*, not about a ban — but there being
  nothing to read at all (no terms page exists to grant or deny) is a
  meaningfully different shape than NWSL's unreadable-JS-shell case, so it
  is called out separately here rather than folded into "NOT USED — unknown"
  language that would imply we found and couldn't parse a page. In any
  case this is **moot regardless of how it's characterized**, per the
  standing rule (DECISIONS 0006): no league's own site is ever read by this
  pipeline, WPBL's schedule included — only Ticketmaster is queried, and
  team names in text are nominative fair use, the same footing every
  already-tracked team name stands on.
- **Ticketmaster coverage — checked empirically, not assumed:** WPBL's own
  tickets page (`https://www.womensprobaseballleague.com/tickets/`, read
  2026-09-16) names its ticketing partner explicitly: single-game tickets
  "starting at $22" and group tickets are sold through **TicketReturn**
  (`ticketreturn.com`), not Ticketmaster — Ticketmaster is not named or
  linked anywhere on that page. Spot-checked Ticketmaster's own search
  directly for all four 2026 teams (100% of the league, not a partial
  sample) plus the bare league name, 2026-09-16:
  - `ticketmaster.com/search?q=Boston Hunters WPBL` → **0 results**
  - `ticketmaster.com/search?q=New York Heights WPBL` → **0 results**
  - `ticketmaster.com/search?q=Los Angeles Queens WPBL` → **0 results**
  - `ticketmaster.com/search?q=San Francisco Firebells` → **0 results**
  - `ticketmaster.com/search?q=WPBL` → **0 results**
  - No listing found for the venue itself either (Robin Roberts Stadium,
    Springfield, IL) under a Ticketmaster venue page.

  Every result returned Ticketmaster's own "no upcoming events" message,
  not merely a thin result. This is a clean, total absence, not a sparse
  one — the opposite of the AUSL spot-check (2026-09-14 addendum above),
  which found real per-venue inventory before AUSL was added.
- **Verdict: NOT ADDED.** Team-identity shape holds up (fixed franchises,
  same as WNBA/NWSL/PWHL/AUSL) and the licence question turns out moot
  either way (no site is ever read, and WPBL's own terms are in any case
  the least restrictive found in this survey). The pipeline's entire data
  model is "Ticketmaster Discovery API event for a tracked team's keyword
  search, or nothing" (DECISIONS 0006) — with confirmed **zero**
  Ticketmaster inventory across all four teams and the league name itself,
  adding WPBL would ship four team pages and `.ics` feeds that can never
  contain a game or a price, which is exactly the "absence rendered as
  emptiness presented as if it were coverage" failure mode this repo
  avoids elsewhere. See `docs/DECISIONS.md` 0009.

## 2. Ticket data and prices — Ticketmaster Discovery API

- **What we take:** event id, venue, date/time (with TZID), price range
  (`priceRanges[].min/max/currency`), event purchase URL — nothing else.
- **Terms:** `https://developer.ticketmaster.com/support/terms-of-use/`
  ("General Terms of Use – The Ticketmaster Developer Portal"), **Last
  Updated: June 27, 2023**.
  - Prohibited: *"Sell, lease, or sublicense the Ticketmaster API or access
    thereto or derive revenues from the use or provision of the Ticketmaster
    API, whether for direct commercial or monetary gain or otherwise, except
    as set forth below."* The document does not spell out what "below"
    refers to; read together with the FAQ's affiliate-programme section
    (next bullet), this is treated as preserving the officially operated
    Impact affiliate programme as the sanctioned revenue route — not as
    banning affiliate commission. **This is an inference, not a verbatim
    guarantee** — flagged as the one interpretive judgment call in this
    table.
  - Prohibited: *"Use the Ticketmaster API for any application that
    replicates or attempts to replace the unique essential user experience
    of Ticketmaster.com or the Ticketmaster apps."* We never sell tickets
    ourselves; every purchase link leaves our site for Ticketmaster's own
    checkout. Compliant by construction.
  - Storage: *"Cache or store any Event Content other than for reasonable
    periods in order to provide the service you are providing."* A nightly
    rebuild (DECISIONS 0001) that replaces yesterday's data is "reasonable
    periods... to provide the service."
  - Obligation: *"Remove from your application within 24 hours any Event
    Content or other information or tickets that the owner asks you to
    remove."* We have no standing process for this yet beyond the nightly
    rebuild naturally dropping anything Ticketmaster itself stops returning —
    **flagged as an open item**: Chelsea needs a reachable contact channel
    (e.g. an email in the site footer) so such a request has somewhere to
    land; see §6.
  - Rate limiting: *"we reserve the right to rate limit or block
    applications that make a large number of calls to the API that are not
    primarily in response to direct user actions."* Our nightly batch fetch
    is not per-visitor-triggered, so we stay well under the numeric quota
    (below) and keep requests to the minimum needed for one nightly build.
  - No clause anywhere in this document, the FAQ, or the Discovery API
    reference restricts displaying price ranges, requires "Powered by
    Ticketmaster" branding, or mandates a logo/link-back — searched for
    "price," "powered by," "attribution," "logo," "trademark": only generic
    IP-ownership boilerplate found. We attribute anyway (§4) because it is
    honest, low-cost, and the affiliate relationship depends on it.
- **Rate limit:** `https://developer.ticketmaster.com/support/faq/` — *"By
  default, all applications are granted access to our Public APIs, which
  come with a quota of 2 requests per second and 5000 requests per day."*
  The Discovery API reference and Getting Started pages both instead state
  *"The default quota is 5000 API calls per day and rate limitation of 5
  requests per second."* **The two official pages disagree (2 vs 5 req/s);
  5000/day agrees everywhere.** Per the crawl-budget constraint below, the
  pipeline self-limits to **1 request/second**, under both published
  numbers, and reports actual calls made and bytes received every run (§3 of
  `pipeline/`).
- **Verdict: USED**, for schedule (home games), venue, date/time, and price
  range — this is the sole data source in this product (see §0). Discovery
  API events for each of our tracked teams stand in for the league schedule
  itself, since no league passed §1.

## 3. Ticketmaster affiliate programme (via Impact)

- **Source:** FAQ "Affiliates" section (same page as above) plus
  `https://developer.ticketmaster.com/partners/distribution-partners/affiliate-sign-up/`.
- **How it works:** *"Upon approval into the program, Ticketmaster will
  provide eligible publishers with... An Impact publisher ID. An API key or
  other content tools to access the Discovery API or Discovery Feed... you'll
  use your Impact publisher ID to wrap destination URLs in Impact click
  tracking... If you opt to utilize our API or Feed, this click tracking
  will be automatically applied to your links once you add your affiliate
  publisher ID to your developer account."*
- **What this means for us:** once Chelsea's Ticketmaster developer account
  carries the Impact publisher ID, the `url` field the Discovery API already
  returns per event **is** the affiliate link — Impact tracking is applied
  server-side by Ticketmaster, not by any script or wrapper we write. The
  site renders `event.url` as a plain `<a href>`; nothing runs, nothing sets
  a cookie on our side (DECISIONS 0002). This is the entire monetisation
  mechanism.
- **Revenue rule:** *"Our program rewards partners based on actual sales
  generated, not just traffic referrals."* *"Ticketmaster does not provide
  commission for primary ticket sales during presales or within the initial
  24 hours following a public onsale."* Commission rate: not published
  anywhere reachable (research §8; still unverified here).
- **Approval is discretionary:** *"Is the Ticketmaster affiliate program
  right for me? ... websites and apps capable of bringing distinct and
  unique audiences to Ticketmaster's Marketplace... we invite you to submit
  an application."* Sign-up is a form (linked above); nobody was contacted to
  produce this table, and the form itself is Chelsea's step, not ours (§6).
- **Verdict: USED as the sole monetisation mechanism**, per DECISIONS 0002
  and 0004.

## 4. Attribution shown on the site

No source above contractually requires attribution text (none was found for
Ticketmaster; the leagues are not used at all, so their attribution
requirements are moot). The site footer nonetheless credits Ticketmaster by
name and links to its terms, because the product depends entirely on its API
and affiliate programme and because the accessibility/attribution footer is
part of this repo's own design (`docs/DECISIONS.md`, README). See
`site/` for the rendered footer.

## 5. Summary table

| Source | What we'd take | Schedule reuse OK? | Why | Rate limit / attribution |
|---|---|---|---|---|
| WNBA official site | schedule | **No** | ToS §1 blanket "no public or commercial purposes"; no machine-readable feed; robots.txt/terms 403 to automated UA | — |
| PWHL (HockeyTech feed) | schedule, broadcaster | **No** | ToS clause (xi) bans "automated scripts"; personal non-commercial licence | — |
| NWSL official site | schedule | **No — unknown** | Terms page is a JS shell, unreadable; no machine-readable feed | — |
| ECAL (NWSL/team calendar sync) | schedule | **No** | Personal-use-only + explicit data-mining/robots ban | — |
| NCAA women's | schedule | **No** | No unified feed; ToS bans commercial exploitation of NCAA Content | — |
| Unrivaled | schedule | **No** | Automated-collection ban + explicit "commercial purpose... collecting product prices" ban | — |
| LOVB | schedule | **No** | Commercial-use + data-mining/robots ban | — |
| Athletes Unlimited | schedule | **No** | Automated-access ban + commercial-exploitation ban | — |
| WPBL | schedule | **No — moot** | No terms page exists at all (least-restrictive site found, but no league site is ever read); **not tracked anyway — zero Ticketmaster coverage across all 4 teams, confirmed 2026-09-16** | — |
| **Ticketmaster Discovery API** | event id, venue, date/time, price range, purchase URL | **Yes — sole source** | No ban on affiliate-monetised display of price ranges; nightly caching is "reasonable periods"; we never replicate Ticketmaster.com | 1 req/s self-imposed (published: 2–5 req/s conflicting, 5000/day agreed); attribution shown though not required |
| Impact (Ticketmaster affiliate) | plain affiliate URL, applied server-side to `event.url` | **Yes** | Sanctioned monetisation route per TM's own FAQ | Impact publisher ID configured in TM developer account; approval discretionary |

**Leagues examined: 8 (WNBA, PWHL, NWSL, NCAA women's, Unrivaled, LOVB,
Athletes Unlimited, WPBL). Leagues whose own schedule is used: 0.** All game,
venue, date, and price data in this product comes from the Ticketmaster
Discovery API, per league via team-name filtering — see `docs/DECISIONS.md`
0006 and `pipeline/README.md` for the mechanism. WPBL is examined but not
tracked: see its §1 entry — the blocker is zero Ticketmaster coverage, not
licensing.

## 6. What remains unknown

- Ticketmaster affiliate commission rate — not published anywhere reachable
  without an approved account.
- Whether Impact/Ticketmaster affiliate approval will be granted to a new,
  no-traffic site — the FAQ says approval is discretionary.
- The exact process for honouring a Ticketmaster 24-hour content-removal
  request — no contact channel exists yet; needs an owner decision (§ below,
  and `docs/DECISIONS.md`).
- Whether NWSL's terms, if ever machine-readable, would permit schedule
  reuse — currently unknowable, re-check if the page changes.
- SeatGeek and other secondary ticket sources were not evaluated; out of
  scope per DECISIONS 0004 (Ticketmaster Discovery only).
