"""Each team's and league's OFFICIAL ticket page, for the "Get tickets" link
on team and league pages.

A game's own "Buy tickets" link (sellers.py) exists only while Ticketmaster
lists that game. Between seasons a team page lists nothing, and a fan who
lands on it still wants to know where tickets are sold. This module answers
with one plain link per team (and per league) to the page the team or
league itself publishes for tickets. It is never a resale marketplace and
never a guess (DECISIONS 0013, 0018).

Rules for an entry:

- The URL is on the team's or league's own site, or is the address the
  league's own site links as that team's ticket page. Each entry says
  where the link was found ("evidence").
- It was fetched on CHECKED_ON and returned HTTP 200 with a ticket page's
  title. A candidate that 404'd, redirected somewhere else (a football
  ticket page), or served a placeholder title ("@title") is left out.
- A team with no entry gets no link. Rutgers has none: its "TicketCentral"
  address now redirects to football tickets, and no women's basketball
  ticket page was found on scarletknights.com.

Affiliate links: AFFILIATE_TEMPLATES below maps a destination host to a URL
template with "{url}" where the percent-encoded official URL goes. It is
empty: Chelsea has not joined a ticket affiliate program. While it is empty
every link here is the plain official URL, with no rel and no label. When
she adds one (a reviewed pull request, like sellers.SEATGEEK_IMPACT_LINK),
exactly the links to that host go through it, and they are labelled "Paid
link" with rel="sponsored noopener" like every other paid link on the site
(site._paid_link), and the footer and privacy disclosure turn on
(sellers.affiliate_links_active). Never add a value that varies per reader.

The ticket_click event (analytics.py) counts a click on any link inside the
section these links are rendered in (OFFICIAL_SECTION_SELECTOR), whether or
not a template wraps them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote, urlparse

CHECKED_ON = "2026-10-31"
# The CSS class of the "Get tickets" section (site._official_tickets_block);
# analytics.py counts a click on a link inside it as an official ticket click.
OFFICIAL_SECTION_CLASS = "official-tickets"
OFFICIAL_SECTION_SELECTOR = "." + OFFICIAL_SECTION_CLASS


@dataclass(frozen=True)
class OfficialTicketPage:
    url: str
    evidence: str
    # What the page is, in the link text, when it is narrower than the
    # team's general ticket page ("season tickets").
    kind: str = "tickets"


_WNBA_LINKED = "Linked as this team's tickets page from wnba.com/teams, read " + CHECKED_ON + "."
_PWHL_LINKED = "Linked from thepwhl.com/en/tickets, the league's own ticket page, read " + CHECKED_ON + "."
_NWSL_LINKED = "Linked from nwslsoccer.com/tickets, the league's own ticket page, read " + CHECKED_ON + "."
_NWSL_CLUB_SITE = (
    "The tickets page of the club site nwslsoccer.com/teams links for this club; fetched " + CHECKED_ON + "."
)
_AUSL_TEAM = "Linked from this team's page on theausl.com, the league's own site, read " + CHECKED_ON + "."
_SCHOOL_WBB = (
    "Linked from the school's official athletics site (women's basketball or main menu), read " + CHECKED_ON + "."
)

# (league slug, team slug) -> the team's official ticket page.
OFFICIAL_TEAM_TICKETS: dict[tuple[str, str], OfficialTicketPage] = {
    # WNBA: every team's page as wnba.com/teams links it.
    ("wnba", "atlanta-dream"): OfficialTicketPage("https://dream.wnba.com/tickets/", _WNBA_LINKED),
    ("wnba", "chicago-sky"): OfficialTicketPage("https://sky.wnba.com/tickets/", _WNBA_LINKED),
    ("wnba", "connecticut-sun"): OfficialTicketPage("https://sun.wnba.com/tickets", _WNBA_LINKED),
    ("wnba", "dallas-wings"): OfficialTicketPage("https://wings.wnba.com/tickets", _WNBA_LINKED),
    ("wnba", "golden-state-valkyries"): OfficialTicketPage("https://valkyries.com/tickets", _WNBA_LINKED),
    ("wnba", "indiana-fever"): OfficialTicketPage("https://fever.wnba.com/tickets/", _WNBA_LINKED),
    ("wnba", "las-vegas-aces"): OfficialTicketPage("https://aces.wnba.com/tickets/", _WNBA_LINKED),
    ("wnba", "los-angeles-sparks"): OfficialTicketPage("https://sparks.wnba.com/tickets/", _WNBA_LINKED),
    ("wnba", "minnesota-lynx"): OfficialTicketPage("https://lynx.wnba.com/tickets/", _WNBA_LINKED),
    ("wnba", "new-york-liberty"): OfficialTicketPage("https://liberty.wnba.com/tickets/", _WNBA_LINKED),
    ("wnba", "phoenix-mercury"): OfficialTicketPage("https://mercury.wnba.com/tickets/", _WNBA_LINKED),
    ("wnba", "portland-fire"): OfficialTicketPage("https://fire.wnba.com/tickets", _WNBA_LINKED),
    ("wnba", "seattle-storm"): OfficialTicketPage("https://storm.wnba.com/tickets", _WNBA_LINKED),
    ("wnba", "toronto-tempo"): OfficialTicketPage("https://tempobasketball.com/ticket-central/", _WNBA_LINKED),
    ("wnba", "washington-mystics"): OfficialTicketPage("https://mystics.wnba.com/tickets", _WNBA_LINKED),
    # NWSL
    ("nwsl", "angel-city"): OfficialTicketPage("https://angelcity.com/tickets", _NWSL_CLUB_SITE),
    ("nwsl", "bay-fc"): OfficialTicketPage("https://bayfc.com/tickets/", _NWSL_CLUB_SITE),
    ("nwsl", "boston-legacy"): OfficialTicketPage("https://bostonlegacyfc.com/pages/tickets", _NWSL_CLUB_SITE),
    ("nwsl", "chicago-stars"): OfficialTicketPage("https://chicagostars.com/tickets/", _NWSL_LINKED),
    ("nwsl", "denver-summit"): OfficialTicketPage(
        "https://www.denversummitfc.com/season-tickets/",
        "Linked from the home page of denversummitfc.com (the club site nwslsoccer.com/teams links); "
        "the site has no general tickets page (/tickets is a 404). Read " + CHECKED_ON + ".",
        kind="season tickets",
    ),
    ("nwsl", "gotham-fc"): OfficialTicketPage("https://www.gothamfc.com/tickets", _NWSL_LINKED),
    ("nwsl", "houston-dash"): OfficialTicketPage(
        "https://www.houstondynamofc.com/houstondash/tickets/", _NWSL_CLUB_SITE
    ),
    ("nwsl", "kansas-city-current"): OfficialTicketPage("https://www.kansascitycurrent.com/tickets", _NWSL_LINKED),
    ("nwsl", "north-carolina-courage"): OfficialTicketPage("https://www.nccourage.com/tickets", _NWSL_CLUB_SITE),
    ("nwsl", "orlando-pride"): OfficialTicketPage("https://www.orlandocitysc.com/pride/tickets/", _NWSL_CLUB_SITE),
    ("nwsl", "portland-thorns"): OfficialTicketPage("https://www.thorns.com/tickets", _NWSL_CLUB_SITE),
    ("nwsl", "racing-louisville"): OfficialTicketPage("https://www.racingloufc.com/tickets/", _NWSL_CLUB_SITE),
    ("nwsl", "san-diego-wave"): OfficialTicketPage("https://sandiegowavefc.com/tickets/", _NWSL_CLUB_SITE),
    ("nwsl", "seattle-reign"): OfficialTicketPage("https://www.reignfc.com/tickets", _NWSL_LINKED),
    ("nwsl", "utah-royals"): OfficialTicketPage("https://www.rsl.com/utahroyals/tickets/", _NWSL_LINKED),
    ("nwsl", "washington-spirit"): OfficialTicketPage("https://washingtonspirit.com/tickets/", _NWSL_CLUB_SITE),
    # PWHL: the league hosts each team's ticket page.
    ("pwhl", "boston-fleet"): OfficialTicketPage("https://www.thepwhl.com/en/teams/boston-fleet/tickets", _PWHL_LINKED),
    ("pwhl", "pwhl-detroit"): OfficialTicketPage("https://www.thepwhl.com/en/teams/detroit/tickets", _PWHL_LINKED),
    ("pwhl", "pwhl-hamilton"): OfficialTicketPage("https://www.thepwhl.com/en/teams/hamilton/tickets", _PWHL_LINKED),
    ("pwhl", "pwhl-las-vegas"): OfficialTicketPage("https://www.thepwhl.com/en/teams/las-vegas/tickets", _PWHL_LINKED),
    ("pwhl", "minnesota-frost"): OfficialTicketPage(
        "https://www.thepwhl.com/en/teams/minnesota-frost/tickets", _PWHL_LINKED
    ),
    ("pwhl", "montreal-victoire"): OfficialTicketPage(
        "https://www.thepwhl.com/en/teams/montreal-victoire/tickets", _PWHL_LINKED
    ),
    ("pwhl", "new-york-sirens"): OfficialTicketPage(
        "https://www.thepwhl.com/en/teams/new-york-sirens/tickets", _PWHL_LINKED
    ),
    ("pwhl", "ottawa-charge"): OfficialTicketPage(
        "https://www.thepwhl.com/en/teams/ottawa-charge/tickets", _PWHL_LINKED
    ),
    ("pwhl", "pwhl-san-jose"): OfficialTicketPage("https://www.thepwhl.com/en/teams/san-jose/tickets", _PWHL_LINKED),
    ("pwhl", "seattle-torrent"): OfficialTicketPage(
        "https://www.thepwhl.com/en/teams/seattle-torrent/tickets", _PWHL_LINKED
    ),
    ("pwhl", "toronto-sceptres"): OfficialTicketPage(
        "https://www.thepwhl.com/en/teams/toronto-sceptres/tickets", _PWHL_LINKED
    ),
    ("pwhl", "vancouver-goldeneyes"): OfficialTicketPage(
        "https://www.thepwhl.com/en/teams/vancouver-goldeneyes/tickets", _PWHL_LINKED
    ),
    # AUSL: each team's page on theausl.com links only its 2027 season ticket
    # deposits page (its /tickets/ page is an empty "Loading..." shell).
    ("ausl", "chicago-bandits"): OfficialTicketPage(
        "https://theausl.com/bandits/season-ticket-deposits/", _AUSL_TEAM, kind="2027 season tickets"
    ),
    ("ausl", "carolina-blaze"): OfficialTicketPage(
        "https://theausl.com/blaze/season-ticket-deposits/", _AUSL_TEAM, kind="2027 season tickets"
    ),
    ("ausl", "portland-cascade"): OfficialTicketPage(
        "https://theausl.com/cascade/season-ticket-deposits/", _AUSL_TEAM, kind="2027 season tickets"
    ),
    ("ausl", "oklahoma-city-spark"): OfficialTicketPage(
        "https://theausl.com/spark/season-ticket-deposits/", _AUSL_TEAM, kind="2027 season tickets"
    ),
    ("ausl", "utah-talons"): OfficialTicketPage(
        "https://theausl.com/talons/season-ticket-deposits/", _AUSL_TEAM, kind="2027 season tickets"
    ),
    ("ausl", "texas-volts"): OfficialTicketPage(
        "https://theausl.com/volts/season-ticket-deposits/", _AUSL_TEAM, kind="2027 season tickets"
    ),
    # Big Ten women's basketball: the school's own athletics site. A
    # women's-basketball ticket page where the school has one, otherwise its
    # main ticket page. No entry for Rutgers (see the module docstring).
    ("ncaaw-big-ten", "illinois-fighting-illini-womens-basketball"): OfficialTicketPage(
        "https://fightingillini.com/sports/2023/1/8/tickets-womens-basketball", _SCHOOL_WBB
    ),
    ("ncaaw-big-ten", "indiana-hoosiers-womens-basketball"): OfficialTicketPage(
        "https://iuhoosiers.com/tickets", _SCHOOL_WBB
    ),
    ("ncaaw-big-ten", "iowa-hawkeyes-womens-basketball"): OfficialTicketPage(
        "https://hawkeyesports.com/tickets/wbb/", _SCHOOL_WBB
    ),
    ("ncaaw-big-ten", "maryland-terrapins-womens-basketball"): OfficialTicketPage(
        "https://umterps.com/sports/2020/6/16/wbb-ticket-information", _SCHOOL_WBB
    ),
    ("ncaaw-big-ten", "michigan-wolverines-womens-basketball"): OfficialTicketPage(
        "https://mgoblue.com/feature/womens-basketball-tickets", _SCHOOL_WBB
    ),
    ("ncaaw-big-ten", "michigan-state-spartans-womens-basketball"): OfficialTicketPage(
        "https://msuspartans.com/tickets", _SCHOOL_WBB
    ),
    ("ncaaw-big-ten", "minnesota-golden-gophers-womens-basketball"): OfficialTicketPage(
        "https://gophersports.com/WBBTickets", _SCHOOL_WBB
    ),
    ("ncaaw-big-ten", "nebraska-cornhuskers-womens-basketball"): OfficialTicketPage(
        "https://huskers.com/tickets/wbb", _SCHOOL_WBB
    ),
    ("ncaaw-big-ten", "northwestern-wildcats-womens-basketball"): OfficialTicketPage(
        "https://nusports.com/tickets", _SCHOOL_WBB
    ),
    ("ncaaw-big-ten", "ohio-state-buckeyes-womens-basketball"): OfficialTicketPage(
        "https://ohiostatebuckeyes.com/feature/womens-basketball-tickets", _SCHOOL_WBB
    ),
    ("ncaaw-big-ten", "oregon-ducks-womens-basketball"): OfficialTicketPage(
        "https://goducks.com/sports/2021/4/6/womens-basketball-tickets", _SCHOOL_WBB
    ),
    ("ncaaw-big-ten", "penn-state-nittany-lions-womens-basketball"): OfficialTicketPage(
        "https://gopsusports.com/tickets", _SCHOOL_WBB
    ),
    ("ncaaw-big-ten", "purdue-boilermakers-womens-basketball"): OfficialTicketPage(
        "https://purduesports.com/purdue-tickets-purdue-boilermakers", _SCHOOL_WBB
    ),
    ("ncaaw-big-ten", "ucla-bruins-womens-basketball"): OfficialTicketPage(
        "https://uclabruins.com/tickets", _SCHOOL_WBB
    ),
    ("ncaaw-big-ten", "usc-trojans-womens-basketball"): OfficialTicketPage(
        "https://usctrojans.com/sports/2022/7/6/usc-trojans-womens-basketball-tickets-information", _SCHOOL_WBB
    ),
    ("ncaaw-big-ten", "washington-huskies-womens-basketball"): OfficialTicketPage(
        "https://gohuskies.com/sports/2026/7/2/tickets", _SCHOOL_WBB
    ),
    ("ncaaw-big-ten", "wisconsin-badgers-womens-basketball"): OfficialTicketPage(
        "https://uwbadgers.com/sports/2015/8/21/GEN_20140101130",
        'Where uwbadgers.com/tickets redirects ("Ticket Central - Wisconsin Athletic Ticket Office"); '
        "fetched " + CHECKED_ON + ".",
    ),
}

# league slug -> the league's own ticket page. No entry for the Big Ten:
# tickets are sold by each school.
OFFICIAL_LEAGUE_TICKETS: dict[str, OfficialTicketPage] = {
    "wnba": OfficialTicketPage(
        "https://www.wnba.com/tickets", "Linked from wnba.com/teams; fetched " + CHECKED_ON + "."
    ),
    "nwsl": OfficialTicketPage(
        "https://www.nwslsoccer.com/tickets", "Linked from the nwslsoccer.com menu; fetched " + CHECKED_ON + "."
    ),
    "pwhl": OfficialTicketPage(
        "https://www.thepwhl.com/en/tickets", "Linked from the thepwhl.com menu; fetched " + CHECKED_ON + "."
    ),
    "ausl": OfficialTicketPage(
        "https://theausl.com/tickets/", "The league's own tickets page on theausl.com; fetched " + CHECKED_ON + "."
    ),
}

# Destination host -> affiliate URL template with "{url}" where the
# percent-encoded official URL goes. Empty: no ticket affiliate program is
# joined. See the module docstring.
AFFILIATE_TEMPLATES: dict[str, str] = {}

# A template is an https URL with exactly one "{url}", no other brace, and
# no fragment. Anything else fails at import, so a typo never reaches a page.
_TEMPLATE_RE = re.compile(r"https://(?:[a-z0-9-]+\.)+[a-z]{2,}/[^{}#\s]*\{url\}[^{}#\s]*")


def _check() -> None:
    """Every URL is a plain https address with no query or fragment (so it
    carries no tracking of anyone's), and every template has the shape
    above. Run at import, so a bad edit fails every build and test."""
    pages = [*OFFICIAL_TEAM_TICKETS.values(), *OFFICIAL_LEAGUE_TICKETS.values()]
    for page in pages:
        parsed = urlparse(page.url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
            raise ValueError(f"official ticket URL must be plain https with no query: {page.url}")
        if not page.evidence or not page.kind:
            raise ValueError(f"official ticket URL needs evidence and a kind: {page.url}")
    for host, template in AFFILIATE_TEMPLATES.items():
        if not _TEMPLATE_RE.fullmatch(template) or template.count("{url}") != 1:
            raise ValueError(f"affiliate template for {host} must be https://... with one {{url}}: {template!r}")


_check()


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def affiliate_on() -> bool:
    """True when some official ticket link can be paid (a template is set)."""
    return any(AFFILIATE_TEMPLATES.values())


def link_for(page: OfficialTicketPage | None) -> tuple[str, bool] | None:
    """(href, paid) for an official ticket page: the plain URL, or the URL
    through the template for its host when one is set. None for no page."""
    if page is None:
        return None
    template = AFFILIATE_TEMPLATES.get(_host(page.url))
    if not template:
        return page.url, False
    return template.format(url=quote(page.url, safe="")), True


def team_page(league_slug: str, team_slug: str) -> OfficialTicketPage | None:
    return OFFICIAL_TEAM_TICKETS.get((league_slug, team_slug))


def league_page(league_slug: str) -> OfficialTicketPage | None:
    return OFFICIAL_LEAGUE_TICKETS.get(league_slug)


def display_host(url: str) -> str:
    """The site a link goes to, as the link's note names it: "mercury.wnba.com"."""
    return _host(url).removeprefix("www.")
