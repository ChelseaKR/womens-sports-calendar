"""Google Analytics 4 on the HTML pages, and nowhere else (DECISIONS 0012,
which supersedes 0002's "no analytics" posture).

GA4_MEASUREMENT_ID below is the one place the property's measurement ID
goes. It is public (every page that loads GA sends it to the browser), so it
is committed here as site configuration rather than kept as a secret. While
it is empty the build emits no GA at all: no <script>, no reference to
Google, and the privacy copy says the site runs no analytics.

What ga4_head_snippet() emits when an ID is set, on every HTML page:

- One inline <script>. It does nothing unless the page is being served from
  the site's real hostname (the host of --base-url), so a local preview,
  CI's pa11y sweep over 127.0.0.1, or a copy served elsewhere never loads GA
  or sends a hit to the real property.
- It returns before loading anything when the browser sends Global Privacy
  Control (navigator.globalPrivacyControl === true) or Do Not Track
  (navigator.doNotTrack / window.doNotTrack / navigator.msDoNotTrack is
  "1" or "yes"): no Google script, no request to Google, no cookie.
- Consent Mode v2 defaults: ad_storage, ad_user_data and ad_personalization
  are denied everywhere; analytics_storage is denied in the EEA, the UK and
  Switzerland (via `region`) and granted elsewhere. There is no consent
  banner, so nothing ever updates those defaults.
- gtag config with allow_google_signals and allow_ad_personalization_signals
  both false.
- A click listener that sends a gtag event for a "Buy tickets" link (any
  link inside <main> whose host starts "ticketmaster." or contains
  ".ticketmaster.": ticket_click) or a calendar-subscribe link (webcal:, or
  a path ending .ics: calendar_subscribe). It keys on the link's own URL,
  not on template markup, and it only observes the click: the link stays a
  plain URL, is never rewritten, and never routed through a Google
  redirect. (GA4's own enhanced-measurement outbound-click event, if the
  web stream has it on, also records ticket clicks under the name "click".)

The .ics feeds and data/*.json never pass through this module: build.py
writes them before and independently of any HTML, and
tests/test_analytics.py checks they are byte-identical with and without an
ID.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

# The one place the measurement ID goes. Empty ("") = no GA anywhere.
# G-YKGPZ76LVE is the nexthomegame.com web stream of GA4 property 554878764
# (provisioned 2026-09-17, DECISIONS 0012).
GA4_MEASUREMENT_ID = "G-YKGPZ76LVE"
# What /privacy/ tells visitors about retention. It must match the property's
# Admin > Data collection and modification > Data retention setting.
GA4_DATA_RETENTION = "14 months"

# GA4 web-stream measurement IDs are "G-" plus uppercase letters and digits.
# Checked strictly because the value is interpolated into an inline script.
MEASUREMENT_ID_RE = re.compile(r"G-[A-Z0-9]{4,20}")

# analytics_storage defaults to denied for visitors in these regions (ISO
# 3166-1 alpha-2): the 27 EU member states, the three other EEA states
# (Iceland, Liechtenstein, Norway), the United Kingdom, and Switzerland.
EU_MEMBER_STATES = (
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE",
    "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
)  # fmt: skip
ANALYTICS_DENIED_REGIONS = (*EU_MEMBER_STATES, "IS", "LI", "NO", "GB", "CH")

GTAG_JS_URL = "https://www.googletagmanager.com/gtag/js"

_SNIPPET_TEMPLATE = r"""<script>
(function () {
  var w = window, n = navigator, d = document;
  if (w.location.hostname !== __HOST__) return;
  if (n.globalPrivacyControl === true) return;
  var dnt = n.doNotTrack || w.doNotTrack || n.msDoNotTrack;
  if (dnt === "1" || dnt === "yes") return;
  w.dataLayer = w.dataLayer || [];
  function gtag() { w.dataLayer.push(arguments); }
  gtag("consent", "default", {
    ad_storage: "denied", ad_user_data: "denied", ad_personalization: "denied",
    analytics_storage: "denied", region: __DENIED_REGIONS__
  });
  gtag("consent", "default", {
    ad_storage: "denied", ad_user_data: "denied", ad_personalization: "denied",
    analytics_storage: "granted"
  });
  gtag("js", new Date());
  gtag("config", __ID__, { allow_google_signals: false, allow_ad_personalization_signals: false });
  var s = d.createElement("script");
  s.async = true;
  s.src = __GTAG_SRC__;
  d.head.appendChild(s);
  d.addEventListener("click", function (ev) {
    var a = ev.target && ev.target.closest ? ev.target.closest("a[href]") : null;
    if (!a) return;
    if (a.closest("main") && /(^|\.)ticketmaster\./i.test(a.hostname)) {
      gtag("event", "ticket_click", { link_url: a.href, link_domain: a.hostname });
    } else if (a.protocol === "webcal:" || /\.ics$/.test(a.pathname)) {
      gtag("event", "calendar_subscribe", { link_url: a.href });
    }
  });
})();
</script>
"""


def measurement_id(value: str | None) -> str | None:
    """None for an unset/blank ID; the ID itself when it is well formed.
    Raises ValueError on anything else rather than emitting it into a
    script -- a typo should fail the build, not ship a broken tag."""
    if value is None or not value.strip():
        return None
    value = value.strip()
    if not MEASUREMENT_ID_RE.fullmatch(value):
        raise ValueError(f"not a GA4 measurement ID (expected G-XXXXXXXXXX): {value!r}")
    return value


def ga4_head_snippet(ga4_id: str | None, *, base_url: str) -> str:
    """The <head> markup for one page: "" when no ID is set, otherwise the
    guarded inline loader described in the module docstring."""
    mid = measurement_id(ga4_id)
    if mid is None:
        return ""
    host = urlparse(base_url).hostname
    if not host:
        raise ValueError(f"cannot load GA4 without a hostname in the base URL: {base_url!r}")
    replacements = {
        "__HOST__": json.dumps(host),
        "__DENIED_REGIONS__": json.dumps(list(ANALYTICS_DENIED_REGIONS)),
        "__ID__": json.dumps(mid),
        "__GTAG_SRC__": json.dumps(f"{GTAG_JS_URL}?id={mid}"),
    }
    snippet = _SNIPPET_TEMPLATE
    for token, value in replacements.items():
        snippet = snippet.replace(token, value)
    return snippet
