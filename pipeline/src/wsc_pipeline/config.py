"""Static registry of leagues and teams this product tracks, plus run config.

Every team here is tracked because it appears in the current (2026-09-13,
per [moved to private strategy notes] and Wikipedia season pages) roster of an
in-scope league. No league's own schedule feed is used (see
docs/LICENSES-AND-ATTRIBUTION.md and docs/DECISIONS.md 0006) -- these lists
exist only to drive Ticketmaster Discovery API keyword queries. Adding a
team or a league is a data change here, not a code change.

AUSL was added 2026-09-14 (docs/DECISIONS.md 0008) using the six permanent,
city-based franchises of its 2026 season, per
https://en.wikipedia.org/wiki/2026_AUSL_season (read 2026-09-14) and
https://www.espn.com/mlb/story/_/id/49000604/athletes-unlimited-softball-league-schedule-teams-players
(read 2026-09-14). AUSL is Athletes Unlimited's softball league; Athletes
Unlimited's other three disciplines (basketball, lacrosse, volleyball) are
NOT tracked -- see LEAGUES_EXAMINED_NOT_INCLUDED below for why.

WPBL (Women's Pro Baseball League) was examined 2026-09-16 (docs/DECISIONS.md
0009) and NOT added: it is a real, currently operating league with fixed
team franchises, so team identity was never the blocker, and licensing was
moot as usual -- but a direct Ticketmaster search for all four of its 2026
teams and the bare league name returned zero results across the board.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Team:
    slug: str
    name: str


@dataclass(frozen=True)
class League:
    slug: str
    name: str
    country_codes: tuple[str, ...]
    teams: tuple[Team, ...]
    schedule_source_used: bool = False
    schedule_source_note: str = ""


def _teams(*names: str) -> tuple[Team, ...]:
    return tuple(Team(slug=_slugify(n), name=n) for n in names)


def _slugify(name: str) -> str:
    return name.lower().replace(" ", "-").replace(".", "")


LEAGUES: tuple[League, ...] = (
    League(
        slug="wnba",
        name="WNBA",
        country_codes=("US",),
        teams=_teams(
            "Minnesota Lynx",
            "Golden State Valkyries",
            "Las Vegas Aces",
            "Atlanta Dream",
            "Indiana Fever",
            "New York Liberty",
            "Washington Mystics",
            "Dallas Wings",
            "Portland Fire",
            "Chicago Sky",
            "Los Angeles Sparks",
            "Phoenix Mercury",
            "Toronto Tempo",
            "Connecticut Sun",
            "Seattle Storm",
        ),
        schedule_source_used=False,
        schedule_source_note=(
            "WNBA's own schedule is not used: its Terms of Use §1 bans "
            "public or commercial reuse of site materials and no "
            "machine-readable feed exists. Games below are Ticketmaster "
            "Discovery API listings for WNBA teams, not a WNBA feed. "
            "See docs/LICENSES-AND-ATTRIBUTION.md."
        ),
    ),
    League(
        slug="nwsl",
        name="NWSL",
        country_codes=("US",),
        teams=_teams(
            "Angel City",
            "Bay FC",
            "Boston Legacy",
            "Chicago Stars",
            "Denver Summit",
            "Gotham FC",
            "Houston Dash",
            "Kansas City Current",
            "North Carolina Courage",
            "Orlando Pride",
            "Portland Thorns",
            "Racing Louisville",
            "San Diego Wave",
            "Seattle Reign",
            "Utah Royals",
            "Washington Spirit",
        ),
        schedule_source_used=False,
        schedule_source_note=(
            "NWSL's own schedule is not used: its Terms of Use page is an "
            "unreadable JavaScript shell (unknown = not used). Games below "
            "are Ticketmaster Discovery API listings for NWSL teams, not "
            "an NWSL feed. See docs/LICENSES-AND-ATTRIBUTION.md."
        ),
    ),
    League(
        slug="pwhl",
        name="PWHL",
        country_codes=("US", "CA"),
        teams=_teams(
            "Boston Fleet",
            "PWHL Detroit",
            "PWHL Hamilton",
            "PWHL Las Vegas",
            "Minnesota Frost",
            "Montreal Victoire",
            "New York Sirens",
            "Ottawa Charge",
            "PWHL San Jose",
            "Seattle Torrent",
            "Toronto Sceptres",
            "Vancouver Goldeneyes",
        ),
        schedule_source_used=False,
        schedule_source_note=(
            "PWHL's own schedule (the HockeyTech feed) is not used: its "
            "Terms of Use clause (xi) bans automated scripts and limits "
            "use to personal, non-commercial home use. Games below are "
            "Ticketmaster Discovery API listings for PWHL teams, not the "
            "PWHL/HockeyTech feed. See docs/LICENSES-AND-ATTRIBUTION.md."
        ),
    ),
    League(
        slug="ausl",
        name="AUSL",
        country_codes=("US",),
        teams=_teams(
            "Chicago Bandits",
            "Carolina Blaze",
            "Portland Cascade",
            "Oklahoma City Spark",
            "Utah Talons",
            "Texas Volts",
        ),
        schedule_source_used=False,
        schedule_source_note=(
            "AUSL's own schedule (theausl.com, operated by Athletes "
            "Unlimited) is not used: its Terms of Service ban automated "
            "access and commercial exploitation of site content, same as "
            "auprosports.com's terms. Games below are Ticketmaster "
            "Discovery API listings for AUSL teams, not an AUSL feed. See "
            "docs/LICENSES-AND-ATTRIBUTION.md."
        ),
    ),
)

LEAGUES_EXAMINED_NOT_INCLUDED: tuple[dict[str, str], ...] = (
    {
        "name": "NCAA women's sports",
        "reason": (
            "No unified machine-readable schedule across ~350 school "
            "athletic sites, and NCAA.com's Terms of Service ban "
            "commercial exploitation of NCAA Content. Not configured as a "
            "tracked league."
        ),
    },
    {
        "name": "Unrivaled",
        "reason": (
            "Terms of use ban automated collection and name \"collecting "
            "product prices\" as a prohibited commercial purpose. Not "
            "configured as a tracked league (team roster/Ticketmaster "
            "coverage not yet scoped)."
        ),
    },
    {
        "name": "LOVB (League One Volleyball)",
        "reason": (
            "Terms and conditions ban commercial use and data mining/robots. "
            "Not configured as a tracked league (team roster/Ticketmaster "
            "coverage not yet scoped)."
        ),
    },
    {
        "name": "Athletes Unlimited (basketball, lacrosse, volleyball)",
        "reason": (
            "AUSL, the softball league Athletes Unlimited operates, is a "
            "tracked league (see above) via Ticketmaster team-keyword "
            "search, same as WNBA/NWSL/PWHL -- added 2026-09-14, "
            "docs/DECISIONS.md 0008. Athletes Unlimited's other three "
            "disciplines are not tracked: basketball, lacrosse, and "
            "volleyball each play a single host-city season with teams "
            "re-drafted weekly by rotating captains (e.g. basketball's "
            "'Gold Rush'/'Rhythm'/'Glow'/'Eclipse'), so there is no "
            "fixed, season-long team name to keyword-search for, unlike a "
            "city franchise. Not a licensing gap -- theausl.com's own "
            "Terms of Service (same automated-access and commercial-use "
            "bans as auprosports.com) rules out AUSL's own site either "
            "way, since only Ticketmaster is queried."
        ),
    },
    {
        "name": "WPBL (Women's Pro Baseball League)",
        "reason": (
            "Real, currently operating league (inaugural season started "
            "2026-08-01) with four fixed city franchises -- same "
            "team-identity shape as WNBA/NWSL/PWHL/AUSL. Not a licensing "
            "gap: WPBL's own site has no Terms of Use page at all and a "
            "permissive robots.txt, the least restrictive of any league "
            "examined -- moot anyway, since no league's own site is ever "
            "read. Not configured as a tracked league because "
            "Ticketmaster coverage is zero: WPBL's own tickets page names "
            "TicketReturn, not Ticketmaster, as its ticketing partner, "
            "and a direct Ticketmaster search for all four 2026 teams "
            "plus the bare league name returned zero results across the "
            "board, confirmed 2026-09-16. See docs/DECISIONS.md 0009."
        ),
    },
)


def all_teams() -> list[tuple[League, Team]]:
    return [(league, team) for league in LEAGUES for team in league.teams]


def league_by_slug(slug: str) -> League:
    for league in LEAGUES:
        if league.slug == slug:
            return league
    raise KeyError(slug)
