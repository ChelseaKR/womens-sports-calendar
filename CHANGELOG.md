# Changelog

All notable changes to Next Home Game (this repository) are recorded here.
The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/).
No version has been released yet (see #7); everything so far is under
Unreleased, and it is what runs live at https://nexthomegame.com.
The repository was republished as a new public repository on 2026-09-18;
pull request numbers up to #38 below refer to the original, which is now
archived and private.

## [Unreleased]

### Added

- A build-time switch for the team-page block order, `TEAM_PAGE_NEXT_GAME_FIRST`
  in `site.py`, off as shipped: on, a team page with a next home game shows
  that game and its ticket link above the subscribe block. Off, pages are
  byte-identical to before (a golden test pins it); paid-link labels and the
  feeds are unaffected either way.
- A per-event removal switch: an event id listed in `REMOVED_EVENTS`
  (`pipeline/src/wsc_pipeline/config.py`) is left out of every page,
  calendar feed and data file even while Ticketmaster still lists it, so a
  Ticketmaster request to remove an event within 24 hours can be honoured
  with one entry and a re-run of the pages workflow. The publish guard
  reports the removal instead of refusing the build (`docs/adr/0006`).
- Affiliate links, off until the owner sets her ids (`docs/DECISIONS.md`
  0018). With her Impact tracking link set, "Buy tickets" links that already
  go to SeatGeek go through it, and team pages for 25 WNBA and NWSL teams
  get a "Team shop" link to the team's Fanatics store. Every such link is
  marked `rel="sponsored noopener"` with a visible "Paid link" label next to
  it, and the footer and privacy page say so. With no id set, the site is
  byte-for-byte unchanged; the calendar feeds never change.
- A team's URL slug, display name and search names are now separate
  settings (#24). A team that sets none of them publishes exactly what it
  always did (a build of the fixture site before and after is byte-identical,
  and a test pins every published slug and feed UID). A rename can keep the
  slug, show a new display name, and keep searching for the old name; a team
  whose URL must change serves the same feed at its former path and a notice
  page that points to the new one. See `docs/DECISIONS.md` 0017.
- Subscribable `.ics` calendar feeds per league and per team, and a static
  site with one page per league and team, built nightly from the
  Ticketmaster Discovery API (#1).
- Leagues tracked: WNBA, NWSL and PWHL (#1), AUSL (#3), and NCAA women's
  basketball, Big Ten (#4).
- Favicon, Open Graph and Twitter cards, and per-league social preview
  images (#2), and a visual identity built on the navy and gold brand (#10).
- Accessibility checks with pa11y on every page in CI (#1), run in
  parallel (#11).
- The real, fetched feeds are validated before each deploy (#13).
- A `/schedule/` page with every tracked league's listed games for the
  week ahead, day by day, linked from the home page (#35). Days are named
  by date from the build's fetch time, never "today", and the page says when
  its listings were fetched. A build that fetched nothing says so instead of
  showing an empty week; a time-TBA game shows no time; a listing with no
  parsed teams shows its own name. Filtering is by league page, and
  subscribing is from each league's page.
- Search discoverability: league and team pages titled "\<team\>
  \<season\> schedule: add to your calendar", with the season taken from
  the listed games; one-click subscribe buttons for Google Calendar, Apple
  Calendar and Outlook; the next home game on every team page; "Home" and
  "Away" labels where the listing says which; schema.org structured data
  (`SportsEvent` only for games with a known date and time, `SportsTeam`,
  `BreadcrumbList`, `WebSite`); and a sitemap whose `<lastmod>` is when each
  page's schedule last changed, never the build time. `make validate-seo`
  checks all of it before each deploy, and `make validate-fixture-site`
  runs the HTML, feed and structured-data validators on a populated site.
- Calendar feeds name themselves after the team or league, link back to
  their page, and ask apps to refresh daily. UIDs are unchanged, so
  subscribers get no duplicates.
- One calendar feed with every tracked league's games, at
  `/ics/all.ics` (#36). Each game in it is the same event, under the same
  UID, as in its league feed, so a subscriber who also has a league or team
  feed is never given a second copy of a game under another UID. No existing
  feed, URL or UID changes. `make validate-ics` checks the combined feed
  against the league feeds event by event. Nothing links to it yet.
- Google Analytics 4 on the web pages. It is not loaded under Global
  Privacy Control or Do Not Track, ad features are off, and there's a
  `/privacy/` page (#15). A remembered "Opt out of analytics" control sits
  in every footer (#20). The calendar feeds are never tracked.
- A publish guard: the nightly build reads back what the live site last
  published and refuses to publish (the last good deploy stays live) when a
  league would publish an empty calendar over a non-empty one, a league
  loses more than half of at least three upcoming games, or a team loses all
  of at least three, and names the team and games (#21). A season that
  simply ended vanishes nothing. Games with a date and no announced time,
  which the feeds carry as all-day events, are compared by their date.
  `COVERAGE.txt` lists every vanished game and says when the previous
  publish could not be read, and a refused build writes the same list to
  the job summary. The thresholds, a dated per-league override and a list
  of accepted event removals (`REMOVED_EVENTS`, which the 24-hour removal
  in #9 is to share) are in `config.py`.

### Changed

- Games with a known date and no announced start time (most of the Big Ten
  women's basketball schedule) now appear in the calendar feeds as all-day
  events on their date, with "(time TBA)" ending the title, no time shown and
  no end time. They keep the UID the timed event will have, so each becomes the
  same event with a start time when Ticketmaster lists one. How Apple, Google
  and Outlook calendars treat that change from all-day to timed is untested.
  Games with no date at all stay out of the feeds. The page no longer says
  these games are missing from the calendar feed, and the coverage report
  counts all-day and every other excluded game (#18, `docs/DECISIONS.md`
  0016).
- Timed events in the calendar feeds now have an end time, estimated from
  the sport's usual game length (basketball 2 h 30 min, soccer 2 h, ice
  hockey 2 h 30 min, softball 2 h), because Ticketmaster publishes only a
  start and some calendar apps draw an event with no end as a zero-length
  marker. Each such event says "End time estimated; not published by the
  ticket source." in its description. The lengths are defaults in
  `config.GAME_DURATIONS` and can be overridden per league (#20,
  `docs/DECISIONS.md` 0015).
- The repository is public as of 2026-09-18, and the code is licensed under
  the Elastic License 2.0. `NOTICE` lists what the license doesn't cover:
  schedule, event and price data, league and team marks, the fonts and the
  vendored standards.
- Calendar-first: no prices anywhere. Each game has one ticket link to the
  home team's official seller where it's known, otherwise to the
  Ticketmaster listing (#17).
- A ticket link that goes through an affiliate template carries
  `rel="sponsored noopener"`, so search engines can tell it is paid. No
  affiliate template is set, so no page changes today (#27).

### Fixed

- Once Ticketmaster wraps its event URLs in Impact affiliate tracking (it
  does that itself when a publisher id is on the developer account), no
  calendar feed carries one: each feed carries the address the link forwards
  to, byte for byte what it carries today, or no ticket link when there is
  none, and `make validate-ics` refuses a feed with a tracking link. On the
  pages such a link is marked "Paid link" with `rel="sponsored noopener"`,
  named by where it goes, and the footer and privacy page say so
  (`docs/DECISIONS.md` 0018, addendum).
- The `ticket_click` analytics event counts an affiliate link by where it
  goes, read from the link itself, whatever its tracking host, and reports
  that destination with `affiliate: true` instead of the tracking host. The
  "Team shop" link sends a `shop_click` event while it exists. Feeds stay
  untracked.

- The nightly site and calendar-feed rebuild failed every night from
  2026-09-20, so the published feeds stopped updating. Merging #20 reverted
  the #22 fix for an unrecognized venue time zone and left that fix's tests
  calling the feed writer without the build time. The fix is restored and
  the tests pass the build time; event UIDs and feed URLs are unchanged
  (#40).
- One event with an unrecognized venue time zone no longer stops the nightly
  build for every league (#22). The `.ics` writer now asks the same zone
  lookup the rest of the pipeline uses, so that game is written with its
  real UTC start and keeps its UID, and `COVERAGE.txt` and the run log name
  it. The venue's zone is never guessed. Games with a valid zone are
  written exactly as before.
- A canceled game was written to the calendar feeds as an ordinary
  confirmed event, so subscribers' calendars kept showing it. It now has
  `STATUS:CANCELLED` and "Canceled: " before its title; a postponed game has
  `STATUS:TENTATIVE` and "Postponed: " before its title; a rescheduled game
  says so in its description. Event UIDs and feed URLs are unchanged, so
  calendars update the events they already hold. `make validate-ics` fails
  when a feed lacks the status its page shows, including for the fixture
  site's canceled game (#19).
- Every event's `DTSTAMP` in the calendar feeds was the game's own start
  time, a date in the future for an upcoming game that moved with the game.
  It is now the time of the nightly build that wrote the feed (its fetch
  time), the same for every event and later each night. `make validate-ics`
  fails on a `DTSTAMP` after the build's fetch time. Event UIDs and feed
  URLs are unchanged (#20).
- The sitemap check in `make validate-seo` parses `sitemap.xml` with
  `defusedxml` and refuses a DTD or an entity, instead of the standard
  library parser Semgrep flags. `sitemap.py` escapes with `html.escape`,
  which gives the same output. The findings surfaced once the repository
  was public and CI could run.
- The nightly deploy stopped at `validate-html` on 2026-09-18: the new
  "Listings as of" time carried six fractional-second digits, which
  `<time datetime>` does not allow (#37). Fetch times are now also recorded
  in whole seconds, and `make validate-fixture-site` validates a populated
  build's HTML so a CI run would catch this.
- "Away at Home" listings were read with the visitor as the home team.
- A game whose home side is unknown no longer links to either team's
  seller as if it were that team's home game.

- Ticketmaster keyword-search results are checked against the event's own
  participants, so games of unrelated teams no longer appear (#7).
- Live-site defects: duplicate rows, wrong-team games, references to the
  private repository, the repository slug in page titles, and unfetched
  schedules shown as "no games" (#12).
- A title sponsor in front of a matchup ("McBride Homes Braggin' Rights:
  Illinois ... vs Missouri ...") and a game type after it ("... (Exhibition)",
  "- Game 2") are no longer welded onto a team name, and an "<event> at
  <venue>" name no longer names the venue as the home team (#23). The sponsor
  is published as an additive `event_title` and the game type as `game_type`
  (only on games that have one) and shown beside the matchup on the team
  page. A promotion in parentheses ("(Noche Latina Night)") and a ticket
  package after the away team ("Chicago Sky: Capital One Arena VIP
  Seating") are dropped from the team name, as #34 began. Measured on the
  live listings of 2026-09-20 against the previous parser: 11 of 230 games
  change on their pages and in their data (9 titles, 1 game type, 1 VIP
  package listing that now names its teams); a team's slug, feed path and
  every UID are unchanged, and a calendar event's summary still carries the
  full Ticketmaster name.
