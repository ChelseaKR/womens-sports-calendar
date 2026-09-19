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

NCAA women's basketball (Big Ten only) was added 2026-09-16 (docs/DECISIONS.md
0010) using the conference's 18 members for the 2026-27 season, per
https://bigten.org/wbb/article/60396/ (read 2026-09-16). Unlike a WNBA/NWSL/
PWHL/AUSL team name, a bare school nickname (e.g. "Iowa Hawkeyes") is shared
across every sport that school plays, so each team name below is suffixed
"Womens Basketball" to disambiguate the Ticketmaster keyword search --
matching the naming Ticketmaster's own artist pages already use (confirmed
per team before adding any of them, see docs/LICENSES-AND-ATTRIBUTION.md).
The other ~332 Division I women's basketball programs, and every NCAA
women's sport other than basketball, are NOT tracked -- see
LEAGUES_EXAMINED_NOT_INCLUDED below for why.

WPBL (Women's Pro Baseball League) was examined 2026-09-16 (docs/DECISIONS.md
0011) and NOT added: it is a real, currently operating league with fixed
team franchises, so team identity was never the blocker, and licensing was
moot as usual -- but a direct Ticketmaster search for all four of its 2026
teams and the bare league name returned zero results across the board.

USL W League was examined 2026-09-16 (docs/DECISIONS.md 0014) and NOT
added: its 96-club 2026 roster was checked against Ticketmaster and came
back with zero clubs carrying a confirmed, correctly-scoped, current
listing in a 16-club spot-check -- see LEAGUES_EXAMINED_NOT_INCLUDED below.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class Team:
    slug: str
    name: str
    # Longer names of OTHER teams that contain this team's name as a phrase,
    # so the participant check would otherwise accept their games (see
    # KEYWORD_COLLISIONS below and normalize.team_is_participant).
    not_this_team: tuple[str, ...] = ()


@dataclass(frozen=True)
class League:
    slug: str
    name: str
    country_codes: tuple[str, ...]
    teams: tuple[Team, ...]
    schedule_source_used: bool = False
    schedule_source_note: str = ""
    # For structured data (structured_data.py): the sport as schema.org's
    # free-text `sport`, and the real name of the organisation the teams
    # belong to (a league, or the Big Ten Conference). Empty = not stated.
    sport: str = ""
    organization_name: str = ""
    # An override of GAME_DURATIONS for this league (a league whose games run
    # longer or shorter than its sport's usual). None = use the sport's.
    game_duration: timedelta | None = None


# How long a game is assumed to last, per sport (League.sport), for the
# estimated end time of a calendar event: Ticketmaster publishes a start and
# never an end, so DTEND is an estimate and every event that carries one says
# so in its description (ics.END_ESTIMATE_NOTE). The values are rounded-up
# typical lengths, defaults the maintainer can change here or per league
# (League.game_duration), not measurements: a game that runs long or short
# still ends when it ends. A sport missing from this table gets no DTEND at
# all, never a guessed one (DECISIONS 0015).
GAME_DURATIONS: dict[str, timedelta] = {
    "Basketball": timedelta(hours=2, minutes=30),
    "Soccer": timedelta(hours=2),
    "Ice hockey": timedelta(hours=2, minutes=30),
    "Softball": timedelta(hours=2),
}


def estimated_duration(league: League) -> timedelta | None:
    """The assumed length of one of this league's games: its own override,
    else its sport's entry in GAME_DURATIONS, else None (no end time is
    written for it)."""
    if league.game_duration is not None:
        return league.game_duration
    return GAME_DURATIONS.get(league.sport)


# Other teams whose names contain a tracked team's name, found in live
# data rather than guessed. The live build of 2026-09-17 put six games of
# Monterey Bay FC (USL Championship, a men's club) on NWSL Bay FC's page
# and in its calendar: "Bay FC" is a contiguous phrase inside
# "Monterey Bay FC", so the phrase check (DECISIONS 0009) accepted them.
KEYWORD_COLLISIONS: dict[str, tuple[str, ...]] = {
    "Bay FC": ("Monterey Bay FC",),
}


def _teams(*names: str) -> tuple[Team, ...]:
    return tuple(Team(slug=_slugify(n), name=n, not_this_team=KEYWORD_COLLISIONS.get(n, ())) for n in names)


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
            "Discovery API listings for WNBA teams, not a WNBA feed."
        ),
        sport="Basketball",
        organization_name="Women's National Basketball Association",
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
            "an NWSL feed."
        ),
        sport="Soccer",
        organization_name="National Women's Soccer League",
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
            "PWHL/HockeyTech feed."
        ),
        sport="Ice hockey",
        organization_name="Professional Women's Hockey League",
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
            "Discovery API listings for AUSL teams, not an AUSL feed."
        ),
        sport="Softball",
        organization_name="Athletes Unlimited Softball League",
    ),
    League(
        slug="ncaaw-big-ten",
        name="NCAA Women's Basketball (Big Ten)",
        country_codes=("US",),
        teams=_teams(
            "Illinois Fighting Illini Womens Basketball",
            "Indiana Hoosiers Womens Basketball",
            "Iowa Hawkeyes Womens Basketball",
            "Maryland Terrapins Womens Basketball",
            "Michigan Wolverines Womens Basketball",
            "Michigan State Spartans Womens Basketball",
            "Minnesota Golden Gophers Womens Basketball",
            "Nebraska Cornhuskers Womens Basketball",
            "Northwestern Wildcats Womens Basketball",
            "Ohio State Buckeyes Womens Basketball",
            "Oregon Ducks Womens Basketball",
            "Penn State Nittany Lions Womens Basketball",
            "Purdue Boilermakers Womens Basketball",
            "Rutgers Scarlet Knights Womens Basketball",
            "UCLA Bruins Womens Basketball",
            "USC Trojans Womens Basketball",
            "Washington Huskies Womens Basketball",
            "Wisconsin Badgers Womens Basketball",
        ),
        schedule_source_used=False,
        schedule_source_note=(
            "No NCAA women's basketball schedule source -- not NCAA.com, "
            "not NCAA.org, not any individual school's athletics site -- "
            "is used: their Terms of Service ban commercial exploitation "
            "of their content (same blanket shape as every other league "
            "here) and there is no unified machine-readable feed across "
            "Division I programs. Games below are Ticketmaster Discovery "
            "API listings for Big Ten women's basketball teams, not any "
            "NCAA or school feed. Team names are suffixed 'Womens "
            "Basketball' to disambiguate the keyword search, since a "
            "school's nickname alone spans every sport it fields. Limited "
            "to the Big Ten's 18 teams, not all ~350 Division I programs."
        ),
        sport="Basketball",
        organization_name="Big Ten Conference",
    ),
)

LEAGUES_EXAMINED_NOT_INCLUDED: tuple[dict[str, str], ...] = (
    {
        "name": ("NCAA women's basketball outside the Big Ten, and NCAA women's sports other than basketball"),
        "reason": (
            "Big Ten women's basketball is a tracked league (see above) via "
            "Ticketmaster team-keyword search, same as WNBA/NWSL/PWHL/AUSL "
            "-- added 2026-09-16, after confirming "
            "real Ticketmaster inventory (dedicated '<School> Womens "
            "Basketball' artist pages carrying real dated 2026-27 games) "
            "across Big Ten programs, not just a couple of blue bloods. The "
            "other ~332 Division I women's basketball programs, and every "
            "NCAA women's sport other than basketball (soccer, volleyball, "
            "softball, etc.), remain untracked. Not a licensing gap -- "
            "NCAA.com's and NCAA.org's Terms of Service ban commercial "
            "exploitation of their own content, same shape as every other "
            "league here, but neither site is scraped either "
            "way, same as every tracked league. The gap is that "
            "Ticketmaster coverage and conference-by-conference team-roster "
            "stability have not been checked for the remaining programs or "
            "sports -- team roster/Ticketmaster coverage not yet scoped, "
            "same bucket as Unrivaled and LOVB below."
        ),
    },
    {
        "name": "Unrivaled",
        "reason": (
            'Terms of use ban automated collection and name "collecting '
            'product prices" as a prohibited commercial purpose. Not '
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
            "search, same as WNBA/NWSL/PWHL -- added 2026-09-14. "
            "Athletes Unlimited's other three "
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
            "board, confirmed 2026-09-16."
        ),
    },
    {
        "name": "USL W League",
        "reason": (
            "Examined 2026-09-16 and not added -- coverage, not licensing, "
            "is the reason (uslsoccer.com's Terms of Use would fail the "
            "same way every other league's do, but that was never the "
            "blocker). The 2026 "
            "season has 96 clubs across 16 divisions, a much larger and "
            "more volatile roster than any tracked league. A 16-club "
            "Ticketmaster spot-check spanning pro-affiliated and "
            "independent clubs found zero with a confirmed, "
            "correctly-scoped, current Ticketmaster listing; the few "
            "clubs with any Ticketmaster presence returned either no "
            "events or only their affiliated men's team's games. Two "
            "clubs (Racing Louisville FC, North Carolina Courage U23) "
            "also collide by name with already-tracked NWSL franchises. "
            "No scoped subset presented itself the way Big Ten (NCAA) or "
            "six franchises (AUSL) did."
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
