"""Static registry of leagues and teams this product tracks, plus run config.

Every team here is tracked because it appears in the current (2026-09-13,
per [moved to private strategy notes] and Wikipedia season pages) roster of an
in-scope league. No league's own schedule feed is used (see
docs/LICENSES-AND-ATTRIBUTION.md and docs/DECISIONS.md 0006) -- these lists
exist only to drive Ticketmaster Discovery API keyword queries. Adding a
team or a league is a data change here, not a code change.
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
        "name": "Athletes Unlimited",
        "reason": (
            "Terms of service ban automated access and commercial "
            "exploitation of content. Not configured as a tracked league "
            "(team roster/Ticketmaster coverage not yet scoped)."
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
