"""Which hosts a ticket link may point at (DECISIONS 0044).

A game's ticket link comes from Ticketmaster's Discovery API, which lists
events from more than one platform. The link is shown on the pages, in the
structured data and in every calendar feed, so it is kept only when it is an
https address on a host this file lists:

- Ticketmaster's own sites, and the one other site its event links are
  recorded going to (TICKETMASTER_DOMAINS, DISCOVERY_PARTNER_DOMAINS), on
  any of their subdomains; and
- the exact hosts this repository already records as a team's or league's
  official ticket seller (sellers.PRIMARY_SELLERS, official_tickets).

Anything else is left out: the game is still listed, with no ticket link,
which is absence and never a guessed or rewritten address. An http link is
left out too.

An Impact tracking link (impact.py) is judged by where it goes: its plain
destination must be on the list, and the tracking host must be one of
Impact's shared domains or itself on the list. A tracking link with no
destination to read cannot be judged and is left out.
"""

from __future__ import annotations

import re
from functools import cache
from urllib.parse import urlparse

from . import impact, official_tickets

# Ticketmaster's and Live Nation's own sites. An event link on any
# subdomain (www., am., concerts.) is theirs.
TICKETMASTER_DOMAINS = ("ticketmaster.com", "ticketmaster.ca", "livenation.com")
# A few Discovery events are a team's group offer on FEVO (sellers.py).
DISCOVERY_PARTNER_DOMAINS = ("gofevo.com",)
LISTED_DOMAINS = (*TICKETMASTER_DOMAINS, *DISCOVERY_PARTNER_DOMAINS)


def _bare(host: str) -> str:
    return host.lower().removeprefix("www.")


@cache
def recorded_seller_hosts() -> frozenset[str]:
    """The hosts of every official seller page and official ticket page this
    repository records, without a leading "www."."""
    # Imported here, not at the top: sellers imports normalize, and
    # normalize imports this module.
    from . import sellers

    pages = [s.team_page_url for s in sellers.PRIMARY_SELLERS.values()]
    pages += [p.url for p in official_tickets.OFFICIAL_TEAM_TICKETS.values()]
    pages += [p.url for p in official_tickets.OFFICIAL_LEAGUE_TICKETS.values()]
    return frozenset(_bare(urlparse(url).hostname or "") for url in pages) - {""}


def host_is_listed(host: str) -> bool:
    """True for a listed domain or any subdomain of one, or exactly a
    recorded seller host."""
    host = host.lower()
    if any(host == domain or host.endswith("." + domain) for domain in LISTED_DOMAINS):
        return True
    return _bare(host) in recorded_seller_hosts()


# Printable ASCII with no backslash: a browser reads "\" as "/" and drops
# tabs and line breaks, so an address holding one could name a different
# host to a browser than to this file.
_PLAIN_ADDRESS = re.compile(r"[\x21-\x5b\x5d-\x7e]+")
_HOST = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+")


def _https_host(url: object) -> str | None:
    """The host of a plain https address: default port, no user name or
    password, an ordinary host name. None for anything else."""
    if not isinstance(url, str) or not _PLAIN_ADDRESS.fullmatch(url):
        return None
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:  # an unbalanced "[", or a port that is not a number
        return None
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not _HOST.fullmatch(host):
        return None
    if parsed.username is not None or parsed.password is not None or port not in (None, 443):
        return None
    return host


def is_listed_https(url: object) -> bool:
    """True when `url` is a plain https address on a listed host."""
    host = _https_host(url)
    return host is not None and host_is_listed(host)


def is_allowed(url: object) -> bool:
    """True when a ticket link may be shown: a listed https address, or a
    tracking link to one (see the module docstring)."""
    if not isinstance(url, str):
        return False
    destination = impact.plain_url(url)
    if destination is None or not is_listed_https(destination):
        return False
    if destination == url:
        return True
    # A tracking link: its own host must be Impact's, or a listed one.
    host = _https_host(url)
    return host is not None and (impact.on_shared_domain(url) or host_is_listed(host))
