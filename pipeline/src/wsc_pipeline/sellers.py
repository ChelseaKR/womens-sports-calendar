"""Where each game's "Buy tickets" link goes, and the one place an affiliate
ID would be applied to it (DECISIONS 0013).

The site shows no prices (DECISIONS 0013). Each game gets one plain link to
wherever its tickets are sold:

- If the home team's primary seller is known and is not Ticketmaster
  (PRIMARY_SELLERS below), the link goes to that team's page at that seller.
  Ticketmaster often lists these games too, but from resale or the venue,
  not from the team's own box office. Per-game URLs at these sellers are not
  known (this pipeline reads only Ticketmaster), so the link lands on the
  team's page there, and the link text says so.
- Otherwise the link is the event URL Ticketmaster publishes, labelled with
  the site it actually points to (a few Discovery events point at gofevo.com,
  not ticketmaster.com).

The .ics feeds do not use this module. They keep the Ticketmaster event URL,
so no feed changes. (When Ticketmaster has already wrapped that URL in Impact
tracking, the feeds carry its decoded destination instead: impact.py.)

Adding a seller here needs evidence, not a guess: each entry records who
says the seller is the team's primary or official one, and when that was
checked. Only plain links are used, which need no licence (DECISIONS 0003
covers reusing data; nothing is read from these sellers).

Affiliate links (DECISIONS 0018): SEATGEEK_IMPACT_LINK and
FANATICS_IMPACT_LINK below hold the owner's Impact tracking links, and both
are empty. While they are empty no link anywhere on the site changes. Once
SEATGEEK_IMPACT_LINK is set, only the links that already go to SeatGeek
(the teams whose official seller it is) are sent through it; which seller a
game links to never changes. FANATICS_IMPACT_LINK drives the team-page shop
link in team_shops.py. A Ticketmaster event URL can also arrive already
wrapped in Impact tracking (Ticketmaster does that server-side once an
Impact publisher id is on the developer account): it is labelled by where it
goes and marked as paid like the others (is_affiliate_link), with no setting
here.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import quote, urlparse

from . import config, impact, official_tickets
from .normalize import Game, team_is_participant


@dataclass(frozen=True)
class Seller:
    name: str
    team_page_url: str
    evidence: str


# (league slug, team slug) -> the home team's primary ticket seller.
PRIMARY_SELLERS: dict[tuple[str, str], Seller] = {
    ("wnba", "las-vegas-aces"): Seller(
        name="AXS",
        team_page_url="https://www.axs.com/teams/1104736/las-vegas-aces-tickets",
        evidence=(
            "AXS and the Aces extended their ticketing partnership for Michelob "
            "ULTRA Arena (solutions.axs.com, 2025-06-05); AXS team page found "
            "by search 2026-09-17."
        ),
    ),
    ("wnba", "los-angeles-sparks"): Seller(
        name="AXS",
        team_page_url="https://www.axs.com/teams/113921/la-sparks-tickets",
        evidence=(
            "The Sparks' ticket FAQ (sparks.wnba.com/ticket-faq) names AXS.com; "
            "AXS team page found by search 2026-09-17."
        ),
    ),
    ("nwsl", "portland-thorns"): Seller(
        name="SeatGeek",
        team_page_url="https://seatgeek.com/portland-thorns-fc-tickets",
        evidence=(
            "thorns.com: the club extended SeatGeek as its primary ticketing "
            "technology platform; seatgeek.com labels the page 'Official "
            "Ticketing Partner'. Checked 2026-09-17."
        ),
    ),
    ("nwsl", "utah-royals"): Seller(
        name="SeatGeek",
        team_page_url="https://seatgeek.com/utah-royals-fc-tickets",
        evidence=(
            "rsl.com/utahroyals: 'Utah Royals Choose SeatGeek as the Club's "
            "Primary Ticketing Technology Platform'; 2026 games on seatgeek.com "
            "are labelled 'Official Ticketing Partner'. Checked 2026-09-17."
        ),
    ),
    ("pwhl", "minnesota-frost"): Seller(
        name="SeatGeek",
        team_page_url="https://seatgeek.com/minnesota-frost-tickets",
        evidence=(
            "The Frost's arena, Grand Casino Arena, moved all ticketing to "
            "SeatGeek (nhl.com/wild, 2026-06-18); seatgeek.com's Frost page "
            "says 'Official Ticketing Partner'. Checked 2026-09-17."
        ),
    ),
    ("pwhl", "vancouver-goldeneyes"): Seller(
        name="Ticket Leader",
        team_page_url="https://ticketleader.evenue.net/events/PWHL26",
        evidence=(
            "thepwhl.com/en/teams/vancouver-goldeneyes/tickets links only "
            "ticketleader.evenue.net (Ticket Leader on Paciolan), including "
            "this page. Checked 2026-11-05."
        ),
    ),
    ("nwsl", "gotham-fc"): Seller(
        name="SI Tickets",
        team_page_url="https://www.gothamfc.com/tickets",
        evidence=(
            "gothamfc.com/tickets sells through sitickets.com (playoff match, "
            "2027 memberships); SI Tickets has no Gotham team page, so this is "
            "the club's own ticket page. Checked 2026-11-05."
        ),
    ),
    ("ncaaw-big-ten", "minnesota-golden-gophers-womens-basketball"): Seller(
        name="Paciolan",
        team_page_url="https://gophersports.evenue.net/list/WBB",
        evidence=("gophersports.com/WBBTickets links this gophersports.evenue.net page. Checked 2026-11-05."),
    ),
    ("ncaaw-big-ten", "purdue-boilermakers-womens-basketball"): Seller(
        name="Paciolan",
        team_page_url="https://purduesports.evenue.net/list/WBB",
        evidence=(
            "purduesports.com/purdue-tickets-purdue-boilermakers links "
            "purduesports.evenue.net (groupCode=WBB), which opens this page. "
            "Checked 2026-11-05."
        ),
    ),
    ("ncaaw-big-ten", "indiana-hoosiers-womens-basketball"): Seller(
        name="Paciolan",
        team_page_url="https://iuhoosiers.evenue.net/list/WBM",
        evidence=("iuhoosiers.com/tickets links iuhoosiers.evenue.net (groupCode=WBM). Checked 2026-11-05."),
    ),
    ("ncaaw-sec", "arkansas-razorbacks-womens-basketball"): Seller(
        name="Paciolan",
        team_page_url="https://arkansasrazorbacks.evenue.net/list/WB",
        evidence=(
            "arkansasrazorbacks.com/sport/w-baskbl/tickets links this "
            "arkansasrazorbacks.evenue.net page. Checked 2026-11-05."
        ),
    ),
    ("wnba", "dallas-wings"): Seller(
        name="AXS",
        team_page_url="https://www.axs.com/artists/1109710/dallas-wings-tickets",
        evidence=(
            "wings.wnba.com/tickets links this axs.com artist page, including 2027 season tickets. Checked 2026-11-05."
        ),
    ),
    ("wnba", "minnesota-lynx"): Seller(
        name="Jump",
        team_page_url="https://go.lynxbasketball.com/tickets/single",
        evidence=(
            "lynx.wnba.com/tickets links this page and "
            "tickets.lynxbasketball.com; the team named Jump its exclusive "
            "ticketing provider in July 2025, replacing AXS. Checked "
            "2026-11-05."
        ),
    ),
    ("nwsl", "racing-louisville"): Seller(
        name="SeatGeek",
        team_page_url="https://seatgeek.com/racing-louisville-fc-tickets",
        evidence=("racingloufc.com/tickets links this seatgeek.com page. Checked 2026-11-05."),
    ),
    ("nwsl", "bay-fc"): Seller(
        name="Tixr",
        team_page_url="https://www.tixr.com/groups/bayfc",
        evidence=("bayfc.com/tickets links this tixr.com group. Checked 2026-11-05."),
    ),
    ("nwsl", "houston-dash"): Seller(
        name="Tixr",
        team_page_url="https://www.tixr.com/groups/houstondash",
        evidence=("houstondynamofc.com/houstondash/tickets links this tixr.com group. Checked 2026-11-05."),
    ),
    ("nwsl", "denver-summit"): Seller(
        name="Jump",
        team_page_url="https://tickets.denversummitfc.com",
        evidence=(
            "denversummitfc.com/season-tickets links "
            "tickets.denversummitfc.com, a Jump store (judged from its page "
            "assets, not a stated partnership). Checked 2026-11-05."
        ),
    ),
    ("nwsl", "north-carolina-courage"): Seller(
        name="Jump",
        team_page_url="https://tickets.nccourage.com/?tab=single-match",
        evidence=(
            "nccourage.com/tickets links this page, a Jump store (judged from "
            "its page assets, not a stated partnership). Checked 2026-11-05."
        ),
    ),
    ("pwhl", "pwhl-las-vegas"): Seller(
        name="AXS",
        team_page_url="https://www.axs.com/events/1579186/pwhl-las-vegas-season-2026-27-tickets",
        evidence=(
            "thepwhl.com/en/teams/las-vegas/tickets links axs.com only, "
            "including this season page (no AXS team page found). Checked "
            "2026-11-05."
        ),
    ),
    ("ausl", "chicago-bandits"): Seller(
        name="AUSL",
        team_page_url="https://theausl.com/bandits/tickets/",
        evidence=(
            "The AUSL sells its own tickets on theausl.com (SquadUP checkout on "
            "this page); StubHub is its official marketplace. Checked "
            "2026-11-05."
        ),
    ),
    ("ausl", "carolina-blaze"): Seller(
        name="AUSL",
        team_page_url="https://theausl.com/blaze/tickets/",
        evidence=(
            "The AUSL sells its own tickets on theausl.com (SquadUP checkout on "
            "this page); StubHub is its official marketplace. Checked "
            "2026-11-05."
        ),
    ),
    ("ausl", "portland-cascade"): Seller(
        name="AUSL",
        team_page_url="https://theausl.com/cascade/tickets/",
        evidence=(
            "The AUSL sells its own tickets on theausl.com (SquadUP checkout on "
            "this page); StubHub is its official marketplace. Checked "
            "2026-11-05."
        ),
    ),
    ("ausl", "oklahoma-city-spark"): Seller(
        name="AUSL",
        team_page_url="https://theausl.com/spark/tickets/",
        evidence=(
            "The AUSL sells its own tickets on theausl.com (SquadUP checkout on "
            "this page); StubHub is its official marketplace. Checked "
            "2026-11-05."
        ),
    ),
    ("ausl", "utah-talons"): Seller(
        name="AUSL",
        team_page_url="https://theausl.com/talons/tickets/",
        evidence=(
            "The AUSL sells its own tickets on theausl.com (SquadUP checkout on "
            "this page); StubHub is its official marketplace. Checked "
            "2026-11-05."
        ),
    ),
    ("ausl", "texas-volts"): Seller(
        name="AUSL",
        team_page_url="https://theausl.com/volts/tickets/",
        evidence=(
            "The AUSL sells its own tickets on theausl.com (SquadUP checkout on "
            "this page); StubHub is its official marketplace. Checked "
            "2026-11-05."
        ),
    ),
    ("ncaaw-big-ten", "illinois-fighting-illini-womens-basketball"): Seller(
        name="Paciolan",
        team_page_url="https://fightingillini.evenue.net/events/WBB",
        evidence=(
            "fightingillini.com's women's basketball ticket page links "
            "fightingillini.evenue.net (groupCode=WBB), which opens this page. "
            "Checked 2026-11-05."
        ),
    ),
    ("ncaaw-big-ten", "iowa-hawkeyes-womens-basketball"): Seller(
        name="Paciolan",
        team_page_url="https://hawkeyesports.evenue.net/events/WBBSG",
        evidence=(
            "hawkeyesports.com/tickets/wbb links this hawkeyesports.evenue.net single-game page. Checked 2026-11-05."
        ),
    ),
    ("ncaaw-big-ten", "maryland-terrapins-womens-basketball"): Seller(
        name="Paciolan",
        team_page_url="https://umterps.evenue.net/list/WB",
        evidence=(
            "umterps.com's women's basketball ticket page links this umterps.evenue.net page. Checked 2026-11-05."
        ),
    ),
    ("ncaaw-big-ten", "michigan-wolverines-womens-basketball"): Seller(
        name="Paciolan",
        team_page_url="https://mgoblue.evenue.net/events/womens-basketball-single-game-tickets",
        evidence=(
            "mgoblue.com/feature/womens-basketball-tickets links this "
            "mgoblue.evenue.net single-game page. Checked 2026-11-05."
        ),
    ),
    ("ncaaw-big-ten", "nebraska-cornhuskers-womens-basketball"): Seller(
        name="Paciolan",
        team_page_url="https://huskers.evenue.net/events/2026-27-womens-basketball",
        evidence=("huskers.com/tickets/wbb links this huskers.evenue.net page. Checked 2026-11-05."),
    ),
    ("ncaaw-big-ten", "rutgers-scarlet-knights-womens-basketball"): Seller(
        name="Paciolan",
        team_page_url="https://scarletknights.evenue.net/list/WBB",
        evidence=("scarletknights.com/tickets sends buyers to scarletknights.evenue.net. Checked 2026-11-05."),
    ),
    ("ncaaw-big-ten", "ucla-bruins-womens-basketball"): Seller(
        name="Paciolan",
        team_page_url="https://ucla.evenue.net/list/WBB",
        evidence=(
            "uclabruins.com/tickets links ucla.evenue.net (groupCode=WBB), which opens this page. Checked 2026-11-05."
        ),
    ),
    ("ncaaw-big-ten", "usc-trojans-womens-basketball"): Seller(
        name="Paciolan",
        team_page_url="https://usctrojans.evenue.net/events/WBBI",
        evidence=(
            "usctrojans.com's women's basketball ticket page links this usctrojans.evenue.net page. Checked 2026-11-05."
        ),
    ),
    ("ncaaw-big-ten", "washington-huskies-womens-basketball"): Seller(
        name="Paciolan",
        team_page_url="https://gohuskies.evenue.net/list/WB",
        evidence=("gohuskies.com/sports/2026/7/2/tickets links this gohuskies.evenue.net page. Checked 2026-11-05."),
    ),
    ("ncaaw-big-ten", "wisconsin-badgers-womens-basketball"): Seller(
        name="Paciolan",
        team_page_url="https://uwbadgers.evenue.net/cgi-bin/ncommerce3/SEGetGroupList?linkID=wisc",
        evidence=(
            "uwbadgers.com's ticket page links this uwbadgers.evenue.net page "
            "(all sports; no women's-basketball-only page found). Checked "
            "2026-11-05."
        ),
    ),
    ("ncaaw-sec", "alabama-crimson-tide-womens-basketball"): Seller(
        name="Paciolan",
        team_page_url="https://rolltide.evenue.net/list/WBK",
        evidence=(
            "rolltide.com's women's basketball ticket page links this rolltide.evenue.net page. Checked 2026-11-05."
        ),
    ),
    ("ncaaw-sec", "auburn-tigers-womens-basketball"): Seller(
        name="Paciolan",
        team_page_url="https://auburntigers.evenue.net/events/WBSG",
        evidence=(
            "auburntigers.com/tickets/wbb links this auburntigers.evenue.net single-game page. Checked 2026-11-05."
        ),
    ),
    ("ncaaw-sec", "georgia-bulldogs-womens-basketball"): Seller(
        name="Paciolan",
        team_page_url="https://georgiadogs.evenue.net/events/WBBNEW",
        evidence=(
            "georgiadogs.com/buytickets sends buyers to georgiadogs.evenue.net; "
            "this is its women's basketball page. Checked 2026-11-05."
        ),
    ),
    ("ncaaw-sec", "lsu-tigers-womens-basketball"): Seller(
        name="Paciolan",
        team_page_url="https://lsusports.evenue.net/events/WBB",
        evidence=("lsusports.net/tickets/wbball links this lsusports.evenue.net page. Checked 2026-11-05."),
    ),
    ("ncaaw-sec", "mississippi-state-bulldogs-womens-basketball"): Seller(
        name="Paciolan",
        team_page_url="https://hailstate.evenue.net/list/WBSING",
        evidence=("hailstate.com's ticket page links this hailstate.evenue.net single-game page. Checked 2026-11-05."),
    ),
    ("ncaaw-sec", "oklahoma-sooners-womens-basketball"): Seller(
        name="Paciolan",
        team_page_url="https://soonersports.evenue.net/list/WB",
        evidence=("soonersports.com's ticket page links this soonersports.evenue.net page. Checked 2026-11-05."),
    ),
    ("ncaaw-sec", "ole-miss-rebels-womens-basketball"): Seller(
        name="Paciolan",
        team_page_url="https://olemisssports.evenue.net/event/WB26/WBS",
        evidence=(
            "olemisssports.com's women's basketball schedule links this "
            "olemisssports.evenue.net page. Checked 2026-11-05."
        ),
    ),
    ("ncaaw-sec", "texas-longhorns-womens-basketball"): Seller(
        name="Paciolan",
        team_page_url="https://texaslonghorns.evenue.net/list/WB",
        evidence=(
            "texaslonghorns.com's women's basketball ticket page links this "
            "texaslonghorns.evenue.net page. Checked 2026-11-05."
        ),
    ),
    ("ncaaw-sec", "texas-am-aggies-womens-basketball"): Seller(
        name="Paciolan",
        team_page_url="https://12thmanfoundation.evenue.net/list/TAMU",
        evidence=(
            "12thmanfoundation.com/tickets links 12thmanfoundation.evenue.net "
            "(groupCode=TAMU), which opens this page (all sports; no "
            "women's-basketball-only page found). Checked 2026-11-05."
        ),
    ),
    ("ncaaw-sec", "vanderbilt-commodores-womens-basketball"): Seller(
        name="Paciolan",
        team_page_url="https://vucommodores.evenue.net/events/WBSING",
        evidence=(
            "vucommodores.com/wbb-ticketing links this vucommodores.evenue.net single-game page. Checked 2026-11-05."
        ),
    ),
}

# The owner's Impact tracking links (DECISIONS 0018), one per programme,
# exactly as Impact's "Create a link" screen gives them with no landing page
# filled in: "https://<tracking host>/c/<partner id>/<ad id>/<program id>".
# Empty = that programme is off, and the site renders exactly as it did
# before this setting existed. They are public (every rewritten link carries
# one), so they are committed here like analytics.GA4_MEASUREMENT_ID: a
# change goes through review and the whole test suite before it is live.
# Never add anything that varies per reader (no sub-ids, no click ids).
SEATGEEK_IMPACT_LINK = ""
FANATICS_IMPACT_LINK = ""

# Only the fixed shape above is accepted; anything else fails at import, so a
# typo can never reach a page. No query string, no fragment, no braces.
IMPACT_LINK_RE = re.compile(r"https://(?:[a-z0-9-]+\.)+[a-z]{2,}/c/[0-9]+/[0-9]+/[0-9]+")

# The seller whose links SEATGEEK_IMPACT_LINK may rewrite, and the one host
# its destinations must be on. A template is never applied to any other
# seller, so a resale marketplace or Ticketmaster link can never become an
# affiliate link through this setting.
SEATGEEK = "SeatGeek"
SEATGEEK_HOST = "seatgeek.com"


def impact_template(link: str, *, setting: str) -> str | None:
    """The URL template for one Impact tracking link: the link plus Impact's
    deep-link parameter `u`, with "{url}" where the percent-encoded
    destination goes. None when the setting is empty. ValueError when it is
    not the bare tracking-link shape."""
    if not link:
        return None
    if not IMPACT_LINK_RE.fullmatch(link):
        raise ValueError(
            f"{setting} must be an Impact tracking link of the form "
            f"https://<host>/c/<digits>/<digits>/<digits> with nothing after it; got {link!r}"
        )
    return link + "?u={url}"


def _affiliate_templates() -> dict[str, str]:
    template = impact_template(SEATGEEK_IMPACT_LINK, setting="sellers.SEATGEEK_IMPACT_LINK")
    return {SEATGEEK: template} if template else {}


# The single config point for buy-link affiliates: seller name -> a URL
# template with "{url}" where the (percent-encoded) destination goes. Built
# from SEATGEEK_IMPACT_LINK, so it is empty while that is, and then every link
# is the seller's plain URL and the footer says this site is not paid for
# them. These follow from it automatically: the buy link's URL
# (with_affiliate), the visible "Paid link" label and rel="sponsored
# noopener" on exactly the links that went through a template
# (is_affiliate_link, used by site._buy_link), and the disclosure in the
# footer and on the privacy page (site.affiliate_note). The ticket_click
# event reads the destination out of a tracking link's `u` parameter, so it
# counts a rewritten link whatever the tracking host is (analytics.py).
AFFILIATE_LINK_TEMPLATES: dict[str, str] = _affiliate_templates()
FANATICS_TEMPLATE: str | None = impact_template(FANATICS_IMPACT_LINK, setting="sellers.FANATICS_IMPACT_LINK")

# Labels for the hosts Ticketmaster Discovery event URLs point at.
_HOST_LABELS = {
    "ticketmaster.com": "Ticketmaster",
    "ticketmaster.ca": "Ticketmaster",
    "livenation.com": "Live Nation",
    "gofevo.com": "FEVO",
}


def ticket_host_names() -> tuple[str, ...]:
    """The site names ("seatgeek", "axs", "ticketmaster", ...) a "Buy
    tickets" link can point at: every primary seller's host plus every
    labelled Ticketmaster-event host. analytics.py builds its ticket_click
    matcher from this, so a new seller is counted without a second edit."""
    hosts = [urlparse(s.team_page_url).hostname or "" for s in PRIMARY_SELLERS.values()]
    hosts += list(_HOST_LABELS)
    # The label just left of the top-level domain: "evenue" for every
    # Paciolan school (gophersports.evenue.net), "nccourage" for a team-run
    # store (tickets.nccourage.com). The first label would give a school's
    # name or a generic "tickets"/"go" that matches unrelated hosts.
    names = {h.split(".")[-2] for h in hosts if h.count(".") >= 1}
    return tuple(sorted(names))


def affiliate_links_active() -> bool:
    """True when any link on the site can be an affiliate link: a buy-link
    template, the Fanatics shop link, or an official-ticket-page template
    (official_tickets.AFFILIATE_TEMPLATES). The footer and privacy disclosure
    follow this."""
    return any(AFFILIATE_LINK_TEMPLATES.values()) or bool(FANATICS_TEMPLATE) or official_tickets.affiliate_on()


def is_affiliate_link(seller: str, url: str = "") -> bool:
    """True when a buy link is paid: it went through with_affiliate (that is,
    AFFILIATE_LINK_TEMPLATES has a non-empty template for its seller), or its
    URL is an Impact tracking link, which is how a Ticketmaster event URL
    arrives once Ticketmaster wraps it (impact.py). Keyed on the same seller
    name buy_link passes to with_affiliate (the "seller" of a `buy` dict) and
    on the link itself, so the render step can mark exactly the paid links
    without a new field in the published data."""
    return bool(AFFILIATE_LINK_TEMPLATES.get(seller)) or impact.is_impact_link(url)


def any_paid_buy_link(games: Iterable[Game]) -> bool:
    """True when some game's "Buy tickets" link is paid. With no template
    set that can only be a Ticketmaster URL that arrived already wrapped, so
    the build asks this of its games and turns the pages' disclosure on
    (site.py's `paid_links`) for what the data holds, not only for what is
    configured."""
    return any(b is not None and is_affiliate_link(b["seller"], b["url"]) for b in map(buy_link, games))


def with_affiliate(url: str, seller: str) -> str:
    """The seller's template applied to `url`; `url` unchanged when the
    seller has none, or when `url` is already a tracking link (never wrapped
    twice)."""
    if not AFFILIATE_LINK_TEMPLATES.get(seller) or impact.is_impact_link(url):
        return url
    return AFFILIATE_LINK_TEMPLATES[seller].format(url=quote(url, safe=""))


def seller_label_for_url(url: str) -> str:
    """The name of the site a link goes to. A tracking link is named by its
    destination (Ticketmaster), never by the tracking host."""
    host = (urlparse(impact.plain_url(url) or url).hostname or "").lower()
    for domain, label in _HOST_LABELS.items():
        if host == domain or host.endswith("." + domain):
            return label
    return host.removeprefix("www.") or "the seller"


def team_primary_seller(league_slug: str, team_slug: str) -> Seller | None:
    """The team's recorded primary seller when it is not Ticketmaster
    (PRIMARY_SELLERS), else None. Team pages use this to say why a team
    can have no Ticketmaster listings: this pipeline reads only Ticketmaster,
    so it cannot promise that this team's next game will appear."""
    return PRIMARY_SELLERS.get((league_slug, team_slug))


def home_team_seller(game: Game) -> tuple[config.Team, Seller] | None:
    """The primary seller of this game's home team, if one is recorded.
    Only the home team counts: an Aces game at Seattle is sold by Seattle's
    seller, not by AXS. When the event name does not say which side is at
    home (the teams came from Ticketmaster's attraction list), no team's
    seller is assumed: the link stays the event's own listing."""
    if not game.home_team or not game.home_away_known:
        return None
    for (league_slug, team_slug), seller in PRIMARY_SELLERS.items():
        if league_slug != game.league_slug:
            continue
        team = next(t for t in config.league_by_slug(league_slug).teams if t.slug == team_slug)
        if team_is_participant(team.name, {"name": game.home_team}, team.not_this_team):
            return team, seller
    return None


def buy_link(game: Game) -> dict[str, str] | None:
    """{"url", "seller", "home_team"} for the game's one ticket link, or None
    when there is nowhere to send a buyer. "home_team" is set (non-empty)
    only when the link goes to the home team's seller page rather than to
    this specific event."""
    found = home_team_seller(game)
    if found is not None:
        team, seller = found
        return {
            "url": with_affiliate(seller.team_page_url, seller.name),
            "seller": seller.name,
            "home_team": team.name,
        }
    if game.ticket_url:
        label = seller_label_for_url(game.ticket_url)
        return {"url": with_affiliate(game.ticket_url, label), "seller": label, "home_team": ""}
    return None
