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
so no feed changes.

Adding a seller here needs evidence, not a guess: each entry records who
says the seller is the team's primary or official one, and when that was
checked. Only plain links are used, which need no licence (DECISIONS 0003
covers reusing data; nothing is read from these sellers).
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, urlparse

from . import config
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
}

# The single config point for affiliate links: seller name -> a URL template
# with "{url}" where the (percent-encoded) destination goes, e.g. an Impact
# tracking link. Empty on purpose: no affiliate programme is active, so every
# link is the seller's plain URL and the footer says this site is not paid
# for them. Adding an entry here is the whole change needed once an
# application is approved. These follow from it automatically: the buy link's
# URL (with_affiliate), the commission disclosure in the footer and on the
# privacy page (site.AFFILIATE_NOTE_ACTIVE), and rel="sponsored noopener" on
# exactly the links that went through a template (is_affiliate_link, used by
# site._buy_link). The ticket_click event does not: analytics.py matches a
# link by its host, so an affiliate host needs its own entry there.
AFFILIATE_LINK_TEMPLATES: dict[str, str] = {}

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
    names = {h.removeprefix("www.").split(".")[0] for h in hosts if h}
    return tuple(sorted(names))


def affiliate_links_active() -> bool:
    return bool(AFFILIATE_LINK_TEMPLATES)


def is_affiliate_link(seller: str) -> bool:
    """True when a buy link for this seller went through with_affiliate, that
    is, when AFFILIATE_LINK_TEMPLATES has a non-empty template for it. Keyed
    on the same seller name buy_link passes to with_affiliate (the "seller"
    of a `buy` dict), so the render step can mark exactly the links that were
    rewritten without a new field in the published data."""
    return bool(AFFILIATE_LINK_TEMPLATES.get(seller))


def with_affiliate(url: str, seller: str) -> str:
    if not is_affiliate_link(seller):
        return url
    return AFFILIATE_LINK_TEMPLATES[seller].format(url=quote(url, safe=""))


def seller_label_for_url(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    for domain, label in _HOST_LABELS.items():
        if host == domain or host.endswith("." + domain):
            return label
    return host.removeprefix("www.") or "the seller"


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
