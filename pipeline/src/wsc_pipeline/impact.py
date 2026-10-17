"""Recognise an Impact affiliate tracking link, and find where it goes.

Impact runs the affiliate programmes this site can use (DECISIONS 0018 and
docs/LICENSES-AND-ATTRIBUTION.md §3). Its tracking links have this shape:

    https://<tracking host>/c/<partner id>/<ad id>/<program id>?u=<destination>

with the percent-encoded destination in the `u` parameter. The tracking host
is either a subdomain of one of Impact's shared domains (seatgeek.pxf.io,
ticketmaster.evyy.net, ...) or a brand's own custom domain, so a link is
recognised by that path shape on any host, not by a list of hosts. A host on
a shared domain is also treated as tracking whatever its path, because
Impact's short links (https://<brand>.pxf.io/<code>) have no `/c/` path and
no `u` to read.

Ticketmaster wraps the Discovery API's `event.url` in this tracking itself,
server-side, once an Impact publisher id is on the developer account (§3).
So a link can arrive already paid, with no setting in this repository:

- the .ics feeds never carry one (plain_url: the decoded destination, or
  nothing when there is no plain destination to give);
- on the pages it is a paid link, labelled like every other one
  (sellers.is_affiliate_link).

What this cannot recognise: a short link on a brand's custom domain. It has
neither the path nor a shared host. No source this site reads publishes one.
"""

from __future__ import annotations

import re
from urllib.parse import ParseResult, parse_qs, urlparse

# The path of a tracking link: /c/<partner id>/<ad id>/<program id>.
IMPACT_PATH_RE = re.compile(r"/c/[0-9]+/[0-9]+/[0-9]+/?")
# Impact's shared tracking domains: a tracking host is a subdomain of one of
# them unless the brand set up its own. Not exhaustive, which is why the path
# above is the main rule.
IMPACT_SHARED_DOMAINS = ("pxf.io", "sjv.io", "evyy.net", "7eer.net", "ojrq.net")
# How many tracking links deep a destination is followed before giving up.
MAX_HOPS = 3


def _parse(url: str) -> ParseResult | None:
    try:
        return urlparse(url)
    except ValueError:  # e.g. an unbalanced "[" in the host
        return None


def on_shared_domain(url: str) -> bool:
    parsed = _parse(url)
    host = (parsed.hostname or "").lower() if parsed else ""
    return any(host == domain or host.endswith("." + domain) for domain in IMPACT_SHARED_DOMAINS)


def is_impact_link(url: str | None) -> bool:
    """True when `url` is an Impact tracking link: the /c/<n>/<n>/<n> path on
    any host, or any address on one of Impact's shared domains."""
    parsed = _parse(url) if url else None
    if parsed is None:
        return False
    return bool(IMPACT_PATH_RE.fullmatch(parsed.path)) or on_shared_domain(url or "")


def _deep_link(url: str) -> str | None:
    """The tracking link's `u` parameter, decoded, when it has exactly one
    and it is an http(s) address with a host."""
    parsed = _parse(url)
    values = parse_qs(parsed.query).get("u", []) if parsed else []
    if len(values) != 1:
        return None
    target = _parse(values[0])
    if target is None or target.scheme not in ("http", "https") or not target.hostname:
        return None
    return values[0]


def plain_url(url: str) -> str | None:
    """`url` itself when it is not a tracking link. Otherwise the plain
    http(s) address it forwards to (followed through at most MAX_HOPS
    tracking links), or None when it names none: a short link, a link with
    no `u`, or a `u` that is not a web address. Never a guessed address."""
    for _ in range(MAX_HOPS + 1):
        if not is_impact_link(url):
            return url
        target = _deep_link(url)
        if target is None:
            return None
        url = target
    return None
