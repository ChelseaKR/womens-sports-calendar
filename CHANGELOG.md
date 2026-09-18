# Changelog

All notable changes to Next Home Game (this repository) are recorded here.
The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/).
No version has been released yet (see #28); everything so far is under
Unreleased, and it is what runs live at https://nexthomegame.com.

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
- Google Analytics 4 on the web pages. It is not loaded under Global
  Privacy Control or Do Not Track, ad features are off, and there's a
  `/privacy/` page (#15). A remembered "Opt out of analytics" control sits
  in every footer (#20). The calendar feeds are never tracked.

### Changed

- Calendar-first: no prices anywhere. Each game has one ticket link to the
  home team's official seller where it's known, otherwise to the
  Ticketmaster listing (#17).

### Fixed

- Ticketmaster keyword-search results are checked against the event's own
  participants, so games of unrelated teams no longer appear (#7).
- Live-site defects: duplicate rows, wrong-team games, references to the
  private repository, the repository slug in page titles, and unfetched
  schedules shown as "no games" (#12).
