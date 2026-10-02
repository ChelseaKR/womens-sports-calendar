# 0006. Publish guard: refuse a build that takes a league's or team's upcoming games away

Status: Proposed
Date: 2026-09-19 (revised 2026-10-02: all-day games, accepted event removals,
the job summary, and why the team rule needs three games)
Deciders: Chelsea Kelly-Reif

## Context

The nightly build refused to publish in two cases: a fetch failed, or every
tracked team in every league came back empty at once. If one league or one
team quietly came back with none of its games (a renamed team, a keyword
that stops matching, a change in how Ticketmaster catalogs a team's events),
the build succeeded and published an empty page and an empty feed for it.
Calendar apps mirror the feed, so subscribers lost those games from their
calendars the next time their app refreshed. The 30-hour freshness alarm
(ADR 0003) cannot see it, because the listings are new, only thinner.

Nothing in the build could tell "PWHL and AUSL have no listings because they
are off-season" from "the query broke", and neither could anyone reading
`COVERAGE.txt`.

The build is stateless (ADR 0005), so the only record of what was published
last is the live site. The same pattern already reads `lastmod.json` back.

## Decision

Every build that fetched listings reads the live site's
`data/<league>/<team>.json` files (one small request per tracked team) and
compares them with what it just fetched. A game has **vanished** when all of
these hold:

1. the previous publish listed it in the calendar feed: a timed event, or an
   all-day event for a game with a date and no announced time (a date-TBD
   game was never in any feed);
2. it was due to start more than 24 hours after this build. An all-day game
   is placed at 00:00 UTC on its date, which is no later than that date
   begins at any venue tracked, so it counts only when its date is after the
   day the 24 hours end;
3. the previous publish had not marked it cancelled or postponed (removal is
   what those look like);
4. its event id is not in `REMOVED_EVENTS` (see "Accepting a real shrink");
5. this build no longer lists it. A game that is still listed but now
   cancelled has not vanished; it is reported as a change.

All-day games matter: on 2026-10-02, 90 of the 101 Big Ten games and 6 of
the 7 WNBA games on the live site had no announced time. The first version
of this guard read only timed games and could not see a loss among them.

Condition 2 is what makes an ended season and an off-season league raise no
alarm: their previous games are in the past, so nothing vanishes, and no
season calendar is needed. A game a few hours away that Ticketmaster has
already delisted is the ordinary end of a listing and is not counted.

The build is **refused** (nothing is written to `--out`, so the last good
deploy stays live) when, for a league with no active override:

| Rule | Fires when | Number |
| --- | --- | --- |
| league would be empty | the league's calendar would hold no games although the previous publish had at least one upcoming game | no minimum: an empty feed is never published over a non-empty one |
| league share | at least 3 upcoming games before, and more than 50% of them vanished | `min_previous_upcoming = 3`, `max_league_vanished_share = 0.5` |
| team lost everything | a team had at least 3 upcoming games before and every one vanished | `min_previous_upcoming = 3` |

Smaller losses are listed in `COVERAGE.txt` (the "Publish guard" section) and
never block. Vanished games for a team whose fetch was cut short (Ticketmaster
results are read in date order, and a truncated read leaves out the later
ones) are listed separately and not counted.

The numbers live in one place, `PUBLISH_GUARD` in `config.py`, with the
reasoning next to them. **They were chosen, not measured**: there is no
history of night-to-night listing churn to measure against. They are meant
to be slow to fire. One broken team keyword loses a team's whole schedule
(the team rule), and a broken league query loses most of a league's (the
share rule); losing a game or two is ordinary churn.

### Why the team rule needs three games

Issue #21 proposed refusing whenever a team loses all of its future games,
however few. The owner chose to keep a minimum of three, because a team can
lose its last one or two listed games for ordinary reasons. The clearest
case is the WNBA playoffs: Ticketmaster lists the "if necessary" games of a
series (games 4 and 5 of a best-of-five) and removes them, without marking
them cancelled, when the series ends early. On 2026-10-02 the semifinal
between the Liberty and the Dream listed two of them, for 2026-10-11 and
2026-10-14. With a minimum of one, each series that ends early would refuse
the whole nightly deploy until someone accepted the removal, and the 30-hour
alarm would fire if nobody did. A team whose keyword breaks loses every one
of its games, which outside the last days of a season is more than two. A
team with only one or two games left is still covered when its league would
go empty (that rule has no minimum). What this leaves unguarded: a team with
one or two upcoming games losing them while the rest of its league keeps
its games. They are listed in `COVERAGE.txt` but do not block.

### Accepting a real shrink

Two tools in `config.py`, both empty today.

`REMOVED_EVENTS` accepts removals one event at a time: an
`EventRemoval(event_id, recorded, reason)` per Ticketmaster event id. A
listed game named there that disappears is reported as an accepted removal
and is not counted toward any rule; the games it does not name still are.
This is the tool for a playoff series that ended early or a single withdrawn
listing. It is the per-event list the data-governance work in #9 needs for
removal within 24 hours of a request: that work is to read the same list to
keep an event out of the publish. Until then, an entry does not hide a game
that is still listed. Entries stay: Ticketmaster does not reuse an event id.

`PUBLISH_GUARD_OVERRIDES` is for a whole league. To accept a league-wide
shrink you have checked is real, add a `GuardOverride(league_slug, reason,
until)`. While
it is active the guard still measures and prints the league's vanished games
(`ACCEPTED BY OVERRIDE`, with the reason) but does not refuse. It stops
applying by itself after `until`, and the build says so once it has, so an
off-season override cannot leave the league unguarded forever.

### What a refusal does

The whole nightly deploy stops, not one league's part of it. GitHub Pages
publishes one artifact, and the previous publish is the only copy of the other
files, so keeping one league's last-good files while publishing the rest
would mean re-publishing files read back from the live site under a new
`lastmod.json`, `index.html` and `site.json`. That mixes two builds in one
deploy and is much harder to reason about than "nothing changed tonight".
The cost is that one league's problem freezes every league for the night; the
30-hour alarm then opens an incident if it is not resolved.

The run log carries `BUILD FAILED: the publish guard refused this build`,
one line per violation naming the team and the vanished games, what to check,
and how to accept the removal; under GitHub Actions each is also an error
annotation. A refused build writes no `COVERAGE.txt`, which `pages.yml`
copies into the job summary only after a good build, so the refusal and the
guard's full section (every team's vanished games) are written to the job
summary directly.

### What is and is not guarded

Guarded: a fetch that fails or returns nothing at all (unchanged); a league or
team whose upcoming games mostly or wholly vanish between two nights.

Not guarded: a team losing one or two games while its league keeps games
(see "Why the team rule needs three games"), a team with three or more losing
fewer than all of them, or a league losing half or
less of its games, in one night; games that Ticketmaster changes rather than
removes (a wrong venue, a moved time); a slow decline across many nights
(each night compared only with the last); an event id that changes while the
game stays (that shows as vanished games, and refuses once it is large
enough). A previous publish that cannot be read is not compared and never
blocks (the same fail-open as the sitemap's), but it is named in the run log
and in `COVERAGE.txt`, never skipped silently.

## Consequences

- A broken team or league query stops the deploy the night it breaks instead
  of emptying subscribers' calendars, and says which team and which games.
- Legitimate removals need a config change to publish when they trip a rule.
  Known cases: a playoff series that ends early removes its "if necessary"
  games (an entry in `REMOVED_EVENTS` per game, needed only when the team
  had three or more upcoming games or the league would go empty);
  Ticketmaster withdrawing a league's listings (a league override).
- The build makes up to 67 small requests to its own site before fetching from
  Ticketmaster (fewer if the site does not answer: it gives up after five
  consecutive failures). It sends no secret.
- The check reads the live site, so like the freshness alarm it cannot run in
  a pull request against real data; its tests use fixture sites and mock
  transports.

## Open decisions for the owner

- The numbers above, and whether a refusal should stop the whole deploy or
  (with the trade-off described above) hold only the flagged league.

Decided on 2026-10-02: the team rule keeps its minimum of three (see above),
and a per-event acceptance list, `REMOVED_EVENTS`, sits alongside the
per-league override and is shared with the 24-hour removal work (#9).
