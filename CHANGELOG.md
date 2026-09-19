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
- Google Analytics 4 on the web pages. It is not loaded under Global
  Privacy Control or Do Not Track, ad features are off, and there's a
  `/privacy/` page (#15). A remembered "Opt out of analytics" control sits
  in every footer (#20). The calendar feeds are never tracked.

### Changed

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

### Fixed

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
