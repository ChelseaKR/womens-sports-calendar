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
    names = {h.removeprefix("www.").split(".")[0] for h in hosts if h}
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
