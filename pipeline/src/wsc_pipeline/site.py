"""Static HTML generator. The only script that runs on any page is the
guarded Google Analytics 4 loader from analytics.py (DECISIONS 0012,
superseding 0002), and only when analytics.GA4_MEASUREMENT_ID is set: with
no ID, no page emitted here contains an executable <script>; with one,
exactly one inline <script> that honours Global Privacy Control and Do Not
Track -- both checked by tests/test_site_html.py and tests/test_analytics.py.
The other <script> element a page may carry is a
<script type="application/ld+json"> structured-data block
(structured_data.py): data for search engines, which browsers never
execute and which loads nothing. Nothing else here is
third-party: STYLE_CSS's @font-face rules point at self-hosted files under
pipeline/assets/fonts/ (copied into dist/fonts/ by build.py), never a Google
Fonts <link>. The privacy copy (footer note and /privacy/) is rendered from
the same ID, so it says "no analytics" exactly when there is none.

WCAG 2.2 AA per STANDARDS/ACCESSIBILITY-STANDARD.md: semantic landmarks,
table headers with scope, link text that names its destination, sufficient
color contrast (checked values noted inline), no color-only distinctions.

Visual design: the "Floodlight" identity (DECISIONS 0035) -- a scoreboard-black
chrome with one floodlight-lime highlight, the same two colors as
pipeline/assets/favicon.svg and scripts/render_social_assets.py (a lime
ticket on a scoreboard plate). Lime keeps the single meaning gold had
before it: "this is a real next game". See the palette comment on
STYLE_CSS below.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, date, datetime
from html import escape as e
from typing import Any
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

from . import config, feeds, official_tickets, structured_data
from .analytics import GA4_DATA_RETENTION, ga4_head_snippet, measurement_id
from .config import history_note_for, league_names_for, title_name_for
from .ics import COMBINED_FEED_PATH, TIME_TBA_NOTE, TIME_TBA_SUFFIX, calendar_name
from .normalize import display_date
from .sellers import (
    AFFILIATE_LINK_TEMPLATES,
    affiliate_links_active,
    is_affiliate_link,
    team_primary_seller,
    with_affiliate,
)
from .site_data import kept_out_of_search, schedule_window
from .team_shops import shop_links_on, team_shop_url

CSS_PATH = "/style.css"
PRIVACY_PATH = "/privacy/"
ACCESSIBILITY_PATH = "/accessibility/"
TERMS_PATH = "/terms/"
HELP_PATH = "/help/"
# The status line docs/a11y/STATEMENT.md opens with. The page renders this
# exact sentence and tests/test_accessibility_page.py asserts the two agree,
# so the published statement and the committed one cannot drift apart.
ACCESSIBILITY_STATUS = (
    "WCAG 2.2 AA target. Automated checks pass on every page of every build. "
    "No human assistive-technology review has been done yet."
)
ACCESSIBILITY_CONTACT_URL = "https://chelseakr.com/contact"
# The address a removal or correction request can reach (roadmap decision B;
# Ticketmaster's terms ask for a way to request removal of an event). Every
# page's footer carries one sentence with a mailto link to it. None drops the
# sentence and gives the footer it had before this setting existed.
# REMOVED_EVENTS (config.py, ADR 0006) is the switch a request is honoured with.
REMOVAL_CONTACT_EMAIL: str | None = "chelsea@chelseakr.com"
_EMAIL_SHAPE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
# The "Updated" date printed on /privacy/, /accessibility/, /terms/ and /help/, and their
# sitemap <lastmod>: one value each, so the two cannot disagree. Change it
# whenever that page's text changes.
PRIVACY_UPDATED = date(2026, 11, 5)
ACCESSIBILITY_UPDATED = date(2026, 11, 5)
TERMS_UPDATED = date(2026, 11, 3)
HELP_UPDATED = date(2026, 11, 6)
# One-click subscribe links. Each takes the feed's webcal:// address; Google
# and Outlook then fetch the feed themselves and keep it subscribed.
# Google's "add by URL" prompt:
GOOGLE_SUBSCRIBE_URL = "https://calendar.google.com/calendar/u/0/r?cid="
# Outlook's "Subscribe from web" dialog, for personal (Outlook.com) and for
# work or school (Microsoft 365) accounts:
OUTLOOK_COM_SUBSCRIBE_URL = "https://outlook.live.com/calendar/0/addfromweb/?"
OUTLOOK_365_SUBSCRIBE_URL = "https://outlook.office.com/calendar/0/addfromweb/?"
# The name visitors see: the header brand, <title> suffix, and og:site_name
# all use this one string. It was the repo slug ("womens-sports-calendar")
# in <title>/og:site_name while the header already said "Next Home Game",
# the domain's name (nexthomegame.com, DECISIONS 0007).
SITE_NAME = "Next Home Game"

# The site-wide default social card, and one per tracked league (see
# wsc_pipeline.config.LEAGUES) -- hand-authored SVG rendered to a 1200x630
# PNG by scripts/render_social_assets.py, committed under pipeline/assets/
# and copied into dist/ by build.py::_write_static. Both dimensions are
# declared below (og:image:width/height) because they are real, not
# assumed -- see scripts/render_social_assets.py's module docstring for
# the rendering pipeline and the checked contrast ratios of everything
# drawn into it.
DEFAULT_OG_IMAGE = "og-image.png"
# Raw Unicode curly quotes, not &lsquo;/&rsquo; entities: this string is
# passed through html.escape() in _base() below, which would mangle a
# literal "&lsquo;" into "&amp;lsquo;" (escaping its leading "&"). A raw
# U+2018/U+2019 character isn't one of html.escape()'s special characters,
# so it passes through untouched and renders correctly under this page's
# declared UTF-8 charset.
DEFAULT_OG_IMAGE_ALT = (
    "A calendar with three highlighted game days, each marked with a "
    "small ball or puck icon for WNBA, NWSL, and PWHL, next to the text "
    "‘Your next home game.’"
)
LEAGUE_OG_IMAGES: dict[str, tuple[str, str]] = {
    "wnba": (
        "og-image-wnba.png",
        "A calendar with one highlighted game day marked by a basketball "
        "icon, next to the text ‘Your next WNBA home game.’",
    ),
    "nwsl": (
        "og-image-nwsl.png",
        "A calendar with one highlighted game day marked by a soccer-ball "
        "icon, next to the text ‘Your next NWSL home game.’",
    ),
    "pwhl": (
        "og-image-pwhl.png",
        "A calendar with one highlighted game day marked by a hockey-puck "
        "icon, next to the text ‘Your next PWHL home game.’",
    ),
}


def _feed_for(feed_keys: frozenset[str], key: str, base_url: str) -> tuple[str, str] | None:
    """The (title, URL) to advertise for feed `key`, or None when this build
    wrote no such feed (feeds.py writes a feed only when it has entries)."""
    if key not in feed_keys:
        return None
    return feeds.feed_title(key), f"{base_url}/{feeds.feed_path(key)}"


def _base(
    *,
    title: str,
    description: str,
    canonical_url: str,
    base_url: str,
    body: str,
    og_type: str = "website",
    og_image: str = DEFAULT_OG_IMAGE,
    og_image_alt: str = DEFAULT_OG_IMAGE_ALT,
    noindex: bool = False,
    ga4_id: str | None = None,
    paid_links: bool = False,
    jsonld: str = "",
    refresh_to: str | None = None,
    feed: tuple[str, str] | None = None,
) -> str:
    """feed is (title, absolute URL) of an Atom feed to advertise (feeds.py).
    jsonld is a structured_data.script_block(); it goes last in <head>
    before the GA4 loader, which must close <head> (tests/test_analytics.py)."""
    image_url = f"{base_url}/{og_image}"
    analytics_head = ga4_head_snippet(ga4_id, base_url=base_url)
    robots_meta = '<meta name="robots" content="noindex">\n' if noindex else ""
    # An instant client-side redirect, for a page that only points elsewhere
    # (render_moved_team): a static host cannot send a real redirect.
    if refresh_to:
        robots_meta += f'<meta http-equiv="refresh" content="0; url={e(refresh_to)}">\n'
    # A noindexed page (the 404) carries no canonical: pointing it at another
    # URL would declare it a duplicate of a page it is not.
    canonical_link = "" if noindex else f'<link rel="canonical" href="{e(canonical_url)}">\n'
    feed_link = (
        f'<link rel="alternate" type="application/atom+xml" title="{e(feed[0])}" href="{e(feed[1])}">\n' if feed else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name='impact-site-verification' content='672c11dd-230b-463d-b029-e09ce84f1050'>
<title>{e(title)}</title>
{robots_meta}<meta name="description" content="{e(description)}">
{canonical_link}{feed_link}<meta name="theme-color" content="#16131d">
<link rel="preload" href="/fonts/public-sans-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="/fonts/big-shoulders-display-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="/fonts/big-shoulders-text-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="{CSS_PATH}">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="icon" href="/favicon-32.png" sizes="32x32" type="image/png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta property="og:site_name" content="{e(SITE_NAME)}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:type" content="{e(og_type)}">
<meta property="og:url" content="{e(canonical_url)}">
<meta property="og:image" content="{e(image_url)}">
<meta property="og:image:type" content="image/png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="{e(og_image_alt)}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{e(title)}">
<meta name="twitter:description" content="{e(description)}">
<meta name="twitter:image" content="{e(image_url)}">
<meta name="twitter:image:alt" content="{e(og_image_alt)}">
{jsonld}{analytics_head}</head>
<body>
<a class="skip-link" href="#main">Skip to main content</a>
<header class="site-header">
<div class="site-header-inner">
<a class="brand" href="/"><img class="brand-mark" src="/favicon.svg" alt="" width="32" height="32">{e(SITE_NAME)}</a>
{SITE_NAV}
</div>
</header>
<main id="main">
{body}
</main>
{_footer(analytics_on=bool(analytics_head), paid_links=paid_links)}
</body>
</html>
"""


# The header's three site links, on every page: the league list on the home
# page, the week-ahead schedule, and the calendar help page (DECISIONS 0036).
# Plain links; the current page is not marked, so every page renders the
# same header.
SITE_NAV = (
    '<nav class="site-nav" aria-label="Site">'
    '<ul><li><a href="/#leagues">Leagues</a></li>'
    '<li><a href="/schedule/">This week</a></li>'
    f'<li><a href="{HELP_PATH}">Help</a></li></ul></nav>'
)


# The footer's privacy note, in the two states the build can be in. Each is
# literal about what happens; /privacy/ has the detail.
PRIVACY_NOTE_ANALYTICS = """This site's pages use Google Analytics to count
visits and clicks on ticket and calendar links, with Google's advertising
features switched off. It is not loaded at all if your browser sends Global
Privacy Control or Do Not Track, or once you opt out here. The calendar
feeds themselves carry no analytics. A
&ldquo;Buy tickets&rdquo; link goes to the ticket seller's own site and tells
them we sent you."""
PRIVACY_NOTE_NO_ANALYTICS = """This site runs no analytics, no scripts, and
sets no cookies, and the calendar feeds carry no analytics either. A &ldquo;Buy
tickets&rdquo; link goes to the ticket seller's own site and tells them we
sent you."""

# Rendered from _any_paid() (the buy-link templates, the Fanatics shop link,
# and any Ticketmaster link the build found already wrapped in Impact
# tracking), so the disclosure is true by construction: it says "affiliate"
# exactly when some link is one (DECISIONS 0013, 0018).
AFFILIATE_NOTE_ACTIVE = (
    "Links marked &ldquo;Paid link&rdquo; are affiliate links: if you buy through one, "
    "this site earns a commission. Every other link is plain, and this site is not paid for it."
)
AFFILIATE_NOTE_INACTIVE = "They are plain links, and this site is not paid for them."
# The rel tokens on a link that went through an affiliate template
# (sellers.is_affiliate_link, team_shops.team_shop_url). "sponsored" is the
# search-engine signal for a paid link; "noopener" is harmless on a link that
# opens in the same tab and keeps the pair safe if a link is ever made to
# open in a new one.
AFFILIATE_LINK_REL = ("sponsored", "noopener")
# The visible label right after every affiliate link, and only after one.
# The FTC's endorsement-guides FAQ says "Paid link" next to an affiliate link
# should be an adequate disclosure, and that the closer the disclosure is to
# the link, the better; the footer note alone would not be (DECISIONS 0018).
PAID_LINK_TEXT = "Paid link"
PAID_LINK_LABEL = f'<span class="paid-link">{PAID_LINK_TEXT}</span>'


def _paid_link(href: str, text_html: str, *, css_class: str = "") -> str:
    """An affiliate link: rel="sponsored noopener", then the visible label."""
    class_attr = f' class="{css_class}"' if css_class else ""
    rel = " ".join(AFFILIATE_LINK_REL)
    return f'<a{class_attr} href="{e(href)}" rel="{rel}">{text_html}</a> {PAID_LINK_LABEL}'


def _buy_links_paid(paid_links: bool = False) -> bool:
    """True when some "Buy tickets" link can be an affiliate link (not just
    the team-shop link): the privacy page's ticket-link paragraph turns on it.
    `paid_links` is the build's own finding (sellers.any_paid_buy_link): a
    Ticketmaster event URL that arrived already wrapped in Impact tracking."""
    return paid_links or any(AFFILIATE_LINK_TEMPLATES.values())


def _any_paid(paid_links: bool = False) -> bool:
    """True when some link on the site can be an affiliate link: one a
    setting makes paid (sellers.affiliate_links_active) or one the build
    found already paid (`paid_links`). The footer and privacy disclosure and
    the label's CSS follow this, so they say "affiliate" exactly when a link
    can be one. Every page renderer takes `paid_links` from the build."""
    return paid_links or affiliate_links_active()


# The footer's "Opt out of analytics" control, only on pages that carry the
# GA4 loader. `hidden` until that loader's script wires it on
# DOMContentLoaded (analytics.py), so a browser without JavaScript -- which
# never runs GA either -- is never shown a button that does nothing. A
# <button>, not a link: it changes a setting rather than going anywhere.
ANALYTICS_CHOICE = (
    '<span class="analytics-choice" data-analytics-choice hidden>'
    '<button type="button" class="analytics-toggle">Opt out of analytics</button> '
    '<span class="analytics-status" role="status"></span></span>'
)


def _removal_contact() -> str:
    """One footer paragraph naming where to send a removal or correction
    request, or "" while REMOVAL_CONTACT_EMAIL is unset. A value that is not a
    plain address stops the build rather than publishing a broken link."""
    address = REMOVAL_CONTACT_EMAIL
    if address is None:
        return ""
    if not _EMAIL_SHAPE.match(address):
        raise ValueError(f"REMOVAL_CONTACT_EMAIL is not a plain email address: {address!r}")
    return (
        '\n<p class="privacy-note">To ask for a game to be removed from this site, '
        f'or to report a mistake, email <a href="mailto:{e(address)}">{e(address)}</a>.</p>'
    )


def _footer(*, analytics_on: bool, paid_links: bool = False) -> str:
    note = PRIVACY_NOTE_ANALYTICS if analytics_on else PRIVACY_NOTE_NO_ANALYTICS
    choice = f"\n{ANALYTICS_CHOICE}" if analytics_on else ""
    affiliate_note = AFFILIATE_NOTE_ACTIVE if _any_paid(paid_links) else AFFILIATE_NOTE_INACTIVE
    return f"""<footer class="site-footer">
<h2>Sources and terms</h2>
<p>{e(feeds.INDEPENDENCE_LINE)}</p>
<p>Game data, venues, and dates are read from the
<a href="https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/">Ticketmaster Discovery API</a>,
under its
<a href="https://developer.ticketmaster.com/support/terms-of-use/">Terms of Use</a>.
No league's own schedule is used on this site &mdash; each league page says
why. This site does not show ticket prices. Each game's &ldquo;Buy
tickets&rdquo; link goes to the home team's official ticket seller where we
know it, and otherwise to the game's Ticketmaster listing.
{affiliate_note}</p>
<p class="privacy-note">{note}
<a href="{PRIVACY_PATH}">Privacy: what this site measures and what it never does</a>.{choice}</p>
<p class="privacy-note"><a href="{HELP_PATH}">Calendar help</a> &middot; <a href="{ACCESSIBILITY_PATH}">Accessibility statement</a> &middot; <a href="{TERMS_PATH}">Terms of use</a>.</p>{_removal_contact()}
</footer>
"""


def _webcal(ics_https_url: str) -> str:
    return ics_https_url.replace("https://", "webcal://", 1).replace("http://", "webcal://", 1)


def subscribe_links(*, ics_https_url: str, cal_name: str) -> dict[str, str]:
    """The one-click subscribe URL for each calendar app, all pointing at the
    same feed. Apple Calendar opens webcal:// itself; Google and Outlook are
    handed the webcal:// address through their own "add by URL" pages."""
    webcal = _webcal(ics_https_url)
    outlook_query = urlencode({"url": webcal, "name": cal_name})
    return {
        "google": GOOGLE_SUBSCRIBE_URL + quote(webcal, safe=""),
        "apple": webcal,
        "outlook_com": OUTLOOK_COM_SUBSCRIBE_URL + outlook_query,
        "outlook_365": OUTLOOK_365_SUBSCRIBE_URL + outlook_query,
    }


def _subscribe_block(*, ics_https_url: str, subject: str, cal_name: str) -> str:
    """One button per calendar app. Kept short so the next-game hero below
    it still starts above the fold on a phone; the raw feed address and the
    by-hand steps are further down the page (_other_apps_block)."""
    links = subscribe_links(ics_https_url=ics_https_url, cal_name=cal_name)
    return f"""<section class="subscribe" aria-labelledby="subscribe-heading">
<h2 id="subscribe-heading">Add {e(subject)} to your calendar</h2>
<p>Subscribe once: new games and time changes reach your calendar on their
own. The calendar is rebuilt every night.</p>
<ul class="subscribe-buttons">
<li><a class="subscribe-cta" href="{e(links["google"])}">Add to Google Calendar</a></li>
<li><a class="subscribe-cta" href="{e(links["apple"])}">Add to Apple Calendar</a></li>
<li><a class="subscribe-cta" href="{e(links["outlook_com"])}">Add to Outlook.com</a></li>
<li><a class="subscribe-cta" href="{e(links["outlook_365"])}">Add to Outlook for work or school</a></li>
</ul>
<p class="subscribe-feed">Another app? <a href="#other-apps-heading">Use the calendar address</a>.</p>
</section>
"""


def _other_apps_block(*, ics_https_url: str) -> str:
    """The feed's own address and the by-hand steps, for any calendar app
    the buttons do not cover, or a button that does not open."""
    return f"""<section class="other-apps" aria-labelledby="other-apps-heading">
<h2 id="other-apps-heading">Other calendar apps</h2>
<p>Subscribe to this address (most calendar apps also open
<code>webcal://</code> links):
<a href="{e(ics_https_url)}">{e(ics_https_url)}</a></p>
<ul class="subscribe-instructions">
<li><strong>iPhone/iPad:</strong> Settings &rsaquo; Calendar &rsaquo; Accounts &rsaquo; Add Account &rsaquo; Other &rsaquo; Add Subscribed Calendar, then paste the address above.</li>
<li><strong>Google Calendar:</strong> on the left, next to &ldquo;Other calendars,&rdquo; select the + icon &rsaquo; From URL, then paste the address above.</li>
<li><strong>Outlook:</strong> Add calendar &rsaquo; Subscribe from web, then paste the address above.</li>
</ul>
<p><a href="{HELP_PATH}">Step-by-step help for each calendar app, and how to unsubscribe</a>.</p>
</section>
"""


def _buy_link(game: Mapping[str, Any], matchup: str, *, css_class: str = "", short: bool = False) -> str | None:
    """The one "Buy tickets" link for a game, from site_data's `buy`
    (sellers.buy_link), with link text naming where it goes. None when
    there is nowhere to buy; callers say so in words. No price is ever
    shown (DECISIONS 0013).

    `short` is for a games-table row, where the matchup and date are already
    in the row: the visible text is "Tickets (<seller>)", so the link still
    names where it goes (DECISIONS 0013, 0018), and the matchup and date are
    in a visually hidden span inside the link, so a screen reader's link list
    still names each game.
    The visible word starts the accessible name, so voice control's "click
    Tickets" still works (WCAG 2.5.3). The hero keeps the full sentence."""
    buy = game.get("buy")
    if not buy:
        return None
    official = f", the official seller for {buy['home_team']} home games" if buy.get("home_team") else ""
    if short:
        hidden = f" for {matchup} on {game['start_display']}"
        if official:
            hidden += f"; {buy['seller']} is the official seller for {buy['home_team']} home games"
        text_html = f'{e(SHORT_TICKET_TEXT)} ({e(buy["seller"])})<span class="sr-only">{e(hidden)}</span>'
    else:
        text_html = e(f"Buy tickets for {matchup} on {game['start_display']} from {buy['seller']}{official}")
    # An affiliate link is marked as one for search engines (Google asks that
    # paid and affiliate links say so) and for the reader, with the visible
    # "Paid link" label right after it (the footer note is not enough on its
    # own). Derived here from the seller and the URL (a Ticketmaster URL
    # can arrive already wrapped in Impact tracking), never stored in
    # the page records. The link text still names the seller, not the tracking
    # host it goes through. A plain link gets no rel attribute and no label
    # at all.
    if is_affiliate_link(buy["seller"], buy["url"]):
        return _paid_link(buy["url"], text_html, css_class=css_class)
    class_attr = f' class="{css_class}"' if css_class else ""
    return f'<a{class_attr} href="{e(buy["url"])}">{text_html}</a>'


# The visible text of a games-table row's ticket link (_buy_link short=True).
SHORT_TICKET_TEXT = "Tickets"


def _matchup_text(game: Mapping[str, Any]) -> str:
    """ "Home vs Away" when both were parsed; otherwise Ticketmaster's own
    event name. Never "TBD vs TBD": the live site showed that for events
    whose names carry no "vs" (e.g. "Washington Spirit Premium
    Experiences", tournament listings), stating two unknown teams when the
    real listing name was right there."""
    if game["home_team"] and game["away_team"]:
        return f"{game['home_team']} vs {game['away_team']}"
    return game.get("event_name") or "Event name not published by Ticketmaster"


def _hero_game_type(game: Mapping[str, Any]) -> str:
    """The game type as plain text after the matchup in the next-game
    hero ("Exhibition" is worth knowing before buying); empty when none."""
    return f" ({game['game_type']})" if game.get("game_type") else ""


def _game_labels_html(game: Mapping[str, Any]) -> str:
    """What the event name said around the matchup, beside it and never
    inside a team's name: the game type ("Exhibition") as a small label, and
    the event's own title (a title sponsor's "Braggin' Rights") on a line
    under it. Empty for a game whose name had neither."""
    html = ""
    if game.get("game_type"):
        html += f' <span class="home-away game-type">{e(game["game_type"])}</span>'
    if game.get("event_title"):
        html += f'<br><span class="event-title">{e(game["event_title"])}</span>'
    return html


def _month_day(iso_date: str | None) -> tuple[str, str] | None:
    """('JUN', '15') from a "start_local_date" ISO string -- parses the
    real date.date, never the human "start_display" string, so a tzid or
    "(time TBA)" suffix can never leak into what's meant to be two short
    tokens for the hero's date-chip."""
    if not iso_date:
        return None
    d = date.fromisoformat(iso_date)
    return (d.strftime("%b").upper(), str(d.day))


NOT_FETCHED_MSG = (
    "This build did not fetch a schedule from Ticketmaster, so no games are "
    "shown. That is not the same as there being no games."
)


def _possibly_incomplete_note(subject: str) -> str:
    return (
        '<p class="schedule-source-note schedule-incomplete-note">'
        f"Ticketmaster returned more matching listings for {e(subject)} than this "
        "build reads, so this list and its calendar feed may be missing later "
        "games.</p>"
    )


def _when_html(game: Mapping[str, Any]) -> str:
    """The game's date and time as the page shows them, in a <time> element
    whose datetime is only ever what is known: the full start with its UTC
    offset, just the date when the time is TBA, and no <time> at all when
    the date is TBD. A Ticketmaster status (cancelled, postponed,
    rescheduled) is said in words next to it."""
    shown = e(game["start_display"])
    machine = game.get("start_local_datetime") or (None if game.get("date_tbd") else game.get("start_local_date"))
    when = f'<time datetime="{e(machine)}">{shown}</time>' if machine else shown
    status = game.get("status")
    if status:
        when += f' <strong class="game-status">{e(status)}</strong>'
    return when


def _feed_note(game: Mapping[str, Any]) -> str:
    """Why a listed game is not in the calendar feed: its date is TBD, or (a
    rare listing) it has a local time but no exact start. A game whose date
    is known and whose time is not announced IS in the feed, as an all-day
    event (normalize.feed_start), so it gets no note."""
    if game["in_calendar_feed"]:
        return ""
    if game.get("date_tbd") or not game.get("start_local_date"):
        return " (date TBD &mdash; not yet in the calendar feed)"
    return " (not yet in the calendar feed)"


def _venue_text(game: Mapping[str, Any]) -> str:
    return ", ".join(p for p in (game["venue_name"], game["venue_city"], game["venue_state"]) if p) or (
        "Venue not available"
    )


def _home_away_tag(game: Mapping[str, Any]) -> str:
    """ "Home" / "Away" on a team page's rows, only when the event name said
    which side was at home (site_data.tracked_team_is_home)."""
    flag = game.get("tracked_team_is_home")
    if flag is None:
        return ""
    label = "Home" if flag else "Away"
    return f' <span class="home-away home-away--{label.lower()}">{label}</span>'


def _seller_sentences(team: Mapping[str, Any]) -> str:
    """The two sentences that say who sells a team's tickets and where to
    look (HTML), for a team whose primary seller is not Ticketmaster
    (sellers.PRIMARY_SELLERS); "" for any other team. It names the seller and
    links the team's official ticket page (official_tickets.py), or the
    seller's team page when no official page was verified. It never says
    tickets are unavailable."""
    seller = team_primary_seller(team["league_slug"], team["team_slug"])
    if seller is None:
        return ""
    owner = "the school's" if team["league_slug"].startswith("ncaaw-") else "the team's"
    official = official_tickets.link_for(official_tickets.team_page(team["league_slug"], team["team_slug"]))
    if official is not None:
        href, paid = official
        text = f"{e(owner)} official ticket page"
        link = _paid_link(href, text) if paid else f'<a href="{e(href)}">{text}</a>'
    else:
        url = with_affiliate(seller.team_page_url, seller.name)
        text = f"{e(owner)} page at {e(seller.name)}"
        link = _paid_link(url, text) if is_affiliate_link(seller.name, url) else f'<a href="{e(url)}">{text}</a>'
    owner_cap = owner[0].upper() + owner[1:]
    return (
        f"{e(owner_cap)} main ticket seller is {e(seller.name)}, {e(seller.contrast)}, so its\n"
        f"home games may not show up here or in your calendar. Check {link} for home games."
    )


def _sells_elsewhere_msg(team: Mapping[str, Any]) -> str:
    """The empty next-game message for a team whose primary ticket seller is
    not Ticketmaster, as HTML; "" for any other team. This pipeline reads
    only Ticketmaster, so for these teams the usual promise that the next
    game will reach the calendar on its own would be false."""
    sentences = _seller_sentences(team)
    if not sentences:
        return ""
    return f"No {e(team['team_name'])} games are listed by Ticketmaster right now.\n{sentences}"


def _next_game_hero(team: Mapping[str, Any]) -> str:
    """The dominant visual moment on a team page, right under the subscribe
    buttons and above the fold on a phone: the soonest listed home game. When no listed game is known to be at
    home, it says so and shows the next listed game under a label that
    says what it is. Never a fabricated date standing in for a real one,
    and never "none listed" when this build did not look (fetched=False)."""
    team_name = team["team_name"]
    games = team["games"]
    if not team.get("fetched", True):
        return f"""<section class="next-game next-game--empty" aria-labelledby="next-game-heading">
<h2 id="next-game-heading" class="next-game-label">Next home game</h2>
<p class="next-game-empty-msg">{e(NOT_FETCHED_MSG)}</p>
</section>
"""
    if not games:
        elsewhere = _sells_elsewhere_msg(team)
        if elsewhere:
            return f"""<section class="next-game next-game--empty" aria-labelledby="next-game-heading">
<h2 id="next-game-heading" class="next-game-label">Next home game</h2>
<p class="next-game-empty-msg">{elsewhere}</p>
</section>
"""
        return f"""<section class="next-game next-game--empty" aria-labelledby="next-game-heading">
<h2 id="next-game-heading" class="next-game-label">Next home game</h2>
<p class="next-game-empty-msg">No {e(team_name)} games are listed by
Ticketmaster right now. Subscribe above and the next one will show up in
your calendar automatically &mdash; nothing to check back for.</p>
</section>
"""
    home = next((g for g in games if g["event_id"] == team.get("next_home_event_id")), None)
    note = ""
    if home is not None:
        g, label = home, "Next home game"
    else:
        g = games[0]
        label = "Next game, away" if g.get("tracked_team_is_home") is False else "Next listed game"
        sellers_note = _seller_sentences(team)
        sellers_note = f"\n{sellers_note}" if sellers_note else ""
        note = f'<p class="next-game-note">No {e(team_name)} home game is listed by Ticketmaster right now.{sellers_note}</p>\n'
    month_day = _month_day(g["start_local_date"])
    matchup = _matchup_text(g)
    when = _when_html(g) + _feed_note(g)
    if month_day:
        month, day = month_day
        date_chip = f'<div class="next-game-date" aria-hidden="true"><span class="next-game-month">{e(month)}</span><span class="next-game-day">{e(day)}</span></div>'
    else:
        date_chip = '<div class="next-game-date next-game-date--tbd" aria-hidden="true"><span class="next-game-month">Date</span><span class="next-game-day">TBD</span></div>'
    cta = _buy_link(g, matchup, css_class="next-game-cta") or (
        '<p class="next-game-cta next-game-cta--unavailable">No ticket link published for this game yet</p>'
    )
    return f"""<section class="next-game" aria-labelledby="next-game-heading">
<h2 id="next-game-heading" class="next-game-label">{label}</h2>
{note}{date_chip}
<div class="next-game-details">
<p class="next-game-matchup">{e(matchup)}{e(_hero_game_type(g))}</p>
<p class="next-game-when">{when}</p>
<p class="next-game-venue">{e(_venue_text(g))}</p>
{cta}
</div>
</section>
"""


def _games_table_wrap_open(caption_id: str) -> str:
    """The games table's wrapper, which scrolls sideways on a phone. A
    keyboard user can only scroll a box they can focus (Safari, and Chrome
    before 130, never focus one on their own), so it is a focusable region
    named by the table's caption (WCAG 2.1.1; axe scrollable-region-focusable).
    The caption id must be unique on the page."""
    return f'<div class="games-table-wrap" role="region" tabindex="0" aria-labelledby="{e(caption_id)}">'


def _games_table(
    games: list[dict[str, Any]], *, buy_link_subject: str, fetched: bool = True, home_away: bool = False
) -> str:
    if not fetched:
        return f'<p class="no-games-message">{e(NOT_FETCHED_MSG)}</p>'
    if not games:
        return '<p class="no-games-message">No upcoming games found from Ticketmaster right now.</p>'
    rows = []
    for g in games:
        matchup = _matchup_text(g)
        date_note = _feed_note(g)
        buy = (
            _buy_link(g, matchup, short=True) or '<span class="ticket-unavailable">no ticket link published yet</span>'
        )
        tag = _home_away_tag(g) if home_away else ""
        rows.append(
            "<tr>"
            f'<td><span class="game-date">{_when_html(g)}</span>{date_note}</td>'
            f"<td>{e(matchup)}{tag}{_game_labels_html(g)}</td>"
            f"<td>{e(_venue_text(g))}</td>"
            f"<td>{buy}</td>"
            "</tr>"
        )
    return f"""{_games_table_wrap_open("games-caption")}
<table class="games-table">
<caption id="games-caption" class="sr-caption">Upcoming {e(buy_link_subject)} games, from Ticketmaster</caption>
<thead>
<tr>
<th scope="col">Date</th>
<th scope="col">Matchup</th>
<th scope="col">Venue</th>
<th scope="col">Tickets</th>
</tr>
</thead>
<tbody>
{"".join(rows)}
</tbody>
</table>
</div>
"""


def _schedule_heading(subject: str, season: str | None) -> str:
    """ "Las Vegas Aces 2026 schedule"; the year only when the listed games
    say which one (site_data.season_label)."""
    return f"{subject} {season} schedule" if season else f"{subject} schedule"


# What a results page shows of a title and a description before cutting them
# off. The build fails (validate_seo) on a page that runs over, so a long name
# is shortened by the tiers below, never cut mid-word by a search engine.
TITLE_MAX = 60
DESCRIPTION_MAX = 155


def _fit(candidates: list[str], limit: int) -> str:
    """The first candidate (longest, most informative first) that fits in
    `limit` characters; the last one when none does, so a name too long for
    even the shortest form is caught by validate_seo, not silently cut."""
    return next((c for c in candidates if len(c) <= limit), candidates[-1])


# Leagues whose season is one calendar year and whose last games are played
# by the month given (the WNBA finals end in October). A team page with no
# listed game, built in that month or later, is about the next year's season
# (DECISIONS 0029). Other leagues' empty pages name no year.
NEXT_SEASON_FROM_MONTH: dict[str, int] = {"wnba": 10}


def _awaited_season(team: Mapping[str, Any]) -> str | None:
    """The season an empty team page is waiting for ("2027"), or None: only
    for a NEXT_SEASON_FROM_MONTH league, only when this build fetched and
    listed nothing, and never for a team whose main seller is not
    Ticketmaster (its home games may never be listed here, so the page must
    not promise that season will fill in)."""
    rollover = NEXT_SEASON_FROM_MONTH.get(team["league_slug"])
    fetched_at = team.get("fetched_at")
    if rollover is None or team["games"] or not team.get("fetched", True) or not fetched_at:
        return None
    if team_primary_seller(team["league_slug"], team["team_slug"]) is not None:
        return None
    when = datetime.fromisoformat(str(fetched_at)).astimezone(UTC)
    return str(when.year + 1 if when.month >= rollover else when.year)


def team_history_text(team: Mapping[str, Any]) -> str:
    """A moved or renamed team's note (config.Team.history_note), plain text,
    or "" for a team without one. While the page waits for a season
    (_awaited_season: a fetched build that lists no game), it adds that the
    season's schedule is not out yet, so the note never reads as if games
    were listed. Shown on the team page and on its former-slug notice page."""
    note = history_note_for(team["league_slug"], team["team_slug"])
    if not note:
        return ""
    awaited = _awaited_season(team)
    return f"{note} The {awaited} schedule is not out yet." if awaited else note


def _team_history_block(team: Mapping[str, Any]) -> str:
    text = team_history_text(team)
    return f'<p class="team-history">{e(text)}</p>\n' if text else ""


def _team_title(
    name: str,
    season: str | None,
    *,
    listed: bool,
    home_listed: bool,
    awaited_season: str | None = None,
    official_ticket_page: bool = False,
) -> str:
    """ "New York Sirens schedule 2026-27: next home game and tickets": the
    words a fan types, in the order Search Console shows them typed
    ("minnesota frost schedule 2026-27", "boston fleet 2026-27 schedule",
    "next valkyries home game"; 2026-10-21 to 10-29). Each claim is made only
    when the page backs it: "tickets" and the season when games are listed
    (every game links to its ticket seller; the site shows no prices), "next
    home game" and "home games" when a home game is listed (the page opens
    with it). A page with nothing listed never says "home games" or
    "tickets": it is "<team> schedule 2027" while it waits for that season
    (_awaited_season; "phoenix mercury schedule 2027" had 18 impressions to
    "phoenix mercury 2027 schedule"'s 7, 2026-10-09 to 11-06, so the year goes
    after "schedule", as on a page with games), and otherwise "<team>
    schedule" with the two things every such page still has: the calendar to
    subscribe to and, when one was verified, the team's official ticket page
    (DECISIONS 0037)."""
    if not listed:
        if awaited_season:
            return _fit(
                [
                    f"{name} schedule {awaited_season}: add it to your calendar",
                    f"{name} schedule {awaited_season}: add to your calendar",
                    f"{name} schedule {awaited_season}",
                ],
                TITLE_MAX,
            )
        return _fit(
            [
                *([f"{name} schedule: calendar and official ticket page"] if official_ticket_page else []),
                f"{name} schedule: add it to your calendar",
                f"{name} schedule",
            ],
            TITLE_MAX,
        )
    schedule = f"{name} schedule {season}" if season else f"{name} schedule"
    lead = (
        [f"{schedule}: next home game and tickets", f"{schedule}: home games and tickets"]
        if home_listed
        else [f"{schedule}: dates and tickets"]
    )
    return _fit([*lead, f"{schedule} and tickets", schedule, f"{name} schedule"], TITLE_MAX)


def _has_official_ticket_page(league_slug: str, team_slug: str) -> bool:
    """Whether the team page shows a "Get <team> tickets" link
    (_official_tickets_block): the same lookup, so a title never names a
    link the page does not have."""
    return official_tickets.link_for(official_tickets.team_page(league_slug, team_slug)) is not None


def _about_schedule(note: str) -> str:
    """The page's schedule-source note, after the games: why the league's
    own schedule is not used and where these listings come from."""
    return f"""<section class="about-schedule" aria-labelledby="about-schedule-heading">
<h2 id="about-schedule-heading">About this schedule</h2>
<p class="schedule-source-note">{e(note)}</p>
</section>
"""


def _breadcrumb(trail: list[tuple[str, str]], current: str) -> str:
    """The visible trail: links for the ancestors, then the current page as
    plain text."""
    links = [f'<a href="{e(href)}">{e(name)}</a>' for name, href in trail]
    links.append(f'<span aria-current="page">{e(current)}</span>')
    return f'<nav aria-label="breadcrumb">{" &rsaquo; ".join(links)}</nav>'


def _league_list_text(names: list[str]) -> str:
    """ "WNBA, NWSL, PWHL, AUSL, Big Ten or SEC"."""
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} or {names[-1]}"


def _all_games_feed_block(base_url: str) -> str:
    """The home page's link to the all-leagues feed (ics/all.ics): what the
    file is, and what an all-day, time-TBA entry in it means (the wording is
    ics.TIME_TBA_SUFFIX and ics.TIME_TBA_NOTE, the feed's own). The link is
    a plain calendar link, so the analytics click listener already counts it
    as calendar_subscribe; nothing else is added."""
    https = f"{base_url}/{COMBINED_FEED_PATH}"
    return f"""<section class="all-games-feed" aria-labelledby="all-games-heading">
<h2 id="all-games-heading">One calendar with every listed game</h2>
<p>This calendar holds every game listed in every league on this site, in one
place. <a href="{e(_webcal(https))}">Subscribe in your calendar app</a>, or
copy the address <a href="{e(https)}">{e(https)}</a> into a calendar app that
asks for one.</p>
<p>A game with a date and no announced start time is an all-day entry that
ends &ldquo;{e(TIME_TBA_SUFFIX.strip())}&rdquo;. Its note reads
&ldquo;{e(TIME_TBA_NOTE)}&rdquo;</p>
</section>
"""


def _teams_by_league_block(leagues: list[dict[str, Any]]) -> str:
    """The home page's links to every team's page, grouped by league, so a
    team page is one click from the home page. Empty when the summary names
    no teams (a caller that does not pass them)."""
    groups = []
    for lg in leagues:
        teams = lg.get("teams") or []
        if not teams:
            continue
        items = "\n".join(f'<li><a href="/{e(lg["slug"])}/{e(t["slug"])}/">{e(t["name"])}</a></li>' for t in teams)
        groups.append(
            f'<h3 id="teams-{e(lg["slug"])}">{e(lg["name"])} teams</h3>\n<ul class="team-roster" '
            f'aria-labelledby="teams-{e(lg["slug"])}">\n{items}\n</ul>'
        )
    if not groups:
        return ""
    return (
        '<section class="all-teams" aria-labelledby="all-teams-heading">\n'
        '<h2 id="all-teams-heading">Every team\'s schedule</h2>\n' + "\n".join(groups) + "\n</section>\n"
    )


def render_index(
    *,
    leagues: list[dict[str, Any]],
    not_included: list[dict[str, str]],
    base_url: str,
    ga4_id: str | None = None,
    paid_links: bool = False,
    feed_keys: frozenset[str] = frozenset(),
) -> str:
    league_rows = []
    for lg in leagues:
        count = lg["games_count"]
        live = bool(count)
        if count is None:
            # Not fetched this build -- never "0 upcoming games".
            count_label = "schedule not fetched"
        else:
            count_label = f"{count} upcoming game" if count == 1 else f"{count} upcoming games"
        row_class = "league-row league-row--live" if live else "league-row"
        league_rows.append(
            f'<li class="{row_class}"><a class="league-row-link" href="/{e(lg["slug"])}/">'
            f'<span class="league-row-name">{e(lg["name"])}</span>'
            f'<span class="league-row-count">{e(count_label)}</span>'
            "</a></li>"
        )
    league_links = "\n".join(league_rows)
    not_included_items = "\n".join(
        f"<li><strong>{e(item['name'])}:</strong> {e(item['reason'])}</li>" for item in not_included
    )
    league_names = _league_list_text([lg["name"] for lg in leagues])
    # The same list in each league's short name ("Big Ten", "SEC"), for when
    # the full names no longer fit the description.
    short_league_names = _league_list_text([league_names_for(lg["slug"], lg["name"])[1] for lg in leagues])
    body = f"""<h1>Women's sports schedules for your calendar</h1>
<p class="lede">Pick a league or a team and add its schedule to Google
Calendar, Apple Calendar or Outlook. Every listed game shows up on its own,
updated nightly, with a link to buy tickets from the team's seller. No
account, no ads.</p>
<p><a href="{SCHEDULE_PATH}">The week ahead in every league, day by day</a></p>
<h2 id="leagues">Leagues</h2>
<ul class="league-strip">
{league_links}
</ul>
{_all_games_feed_block(base_url)}{_teams_by_league_block(leagues)}<section class="not-included-panel" aria-labelledby="not-included-heading">
<h2 id="not-included-heading">Leagues examined and not included</h2>
<p>Per this site's own licensing research, these leagues' own schedules
were not used because their published terms forbid it or could not be
read; they are not tracked as leagues here at all (their games do not
appear even via Ticketmaster, since no team roster was configured for
them):</p>
<ul>
{not_included_items}
</ul>
</section>
"""
    return _base(
        feed=_feed_for(feed_keys, feeds.ALL_KEY, base_url),
        title=_fit(
            [
                f"{SITE_NAME}: women's sports schedules for your calendar",
                f"{SITE_NAME}: women's sports schedules",
            ],
            TITLE_MAX,
        ),
        description=_fit(
            [
                # "next home game" is the home page's top query (DECISIONS 0038).
                f"Find your {league_names} team's next listed home game and add its schedule to "
                "Google, Apple or Outlook calendar. Updated nightly.",
                f"Find your {short_league_names} team's next listed home game and add its schedule to "
                "Google, Apple or Outlook calendar. Updated nightly.",
                "Add your team's schedule to Google, Apple or Outlook calendar. Updated nightly. No account.",
            ],
            DESCRIPTION_MAX,
        ),
        canonical_url=f"{base_url}/",
        base_url=base_url,
        body=body,
        ga4_id=ga4_id,
        paid_links=paid_links,
        jsonld=structured_data.script_block([structured_data.website(name=SITE_NAME, base_url=base_url)]),
    )


def render_not_found(
    *, leagues: list[dict[str, Any]], base_url: str, ga4_id: str | None = None, paid_links: bool = False
) -> str:
    """dist/404.html, which GitHub Pages serves for any missing path --
    without it, a stale or mistyped link lands on GitHub's own "Page not
    found · GitHub Pages" page, with no way back to this site. noindex, and
    kept out of the sitemap."""
    league_links = "\n".join(f'<li><a href="/{e(lg["slug"])}/">{e(lg["name"])}</a></li>' for lg in leagues)
    body = f"""<h1>Page not found</h1>
<p class="lede">There is no page at this address. Team and league calendars
are listed below, or start from <a href="/">the home page</a>.</p>
<h2>Leagues</h2>
<ul class="team-roster">
{league_links}
</ul>
"""
    return _base(
        title=f"Page not found | {SITE_NAME}",
        description="There is no page at this address.",
        canonical_url=f"{base_url}/",
        base_url=base_url,
        body=body,
        noindex=True,
        ga4_id=ga4_id,
        paid_links=paid_links,
    )


def render_moved_team(
    *,
    team_name: str,
    league_name: str,
    league_slug: str,
    team_slug: str,
    base_url: str,
    ga4_id: str | None = None,
    paid_links: bool = False,
    history: str = "",
) -> str:
    """The page at a slug a team used to have (config.Team.former_slugs): a
    notice that points to the current page, and sends the browser there. A
    static host cannot redirect, so this is what a saved link to the old
    page lands on. noindex, and kept out of the sitemap, so the old path is
    never a second listing of the same team; the calendar feed at the old
    path still works and is not touched. `history` is the team page's note
    (team_history_text), plain text, so a fan who followed a link with the
    old name sees why it changed."""
    new_path = f"/{league_slug}/{team_slug}/"
    history_html = f"<p>{e(history)}</p>\n" if history else ""
    body = f"""<h1>{e(team_name)} has a new page address</h1>
<p class="lede moved-notice">The {e(team_name)} ({e(league_name)}) schedule is now at
<a href="{e(new_path)}">{e(base_url)}{e(new_path)}</a>.</p>
{history_html}<p>A calendar you already subscribed to keeps working at its old address.</p>
"""
    return _base(
        title=f"{team_name} schedule has moved | {SITE_NAME}",
        description=f"The {team_name} schedule now lives at {base_url}{new_path}.",
        canonical_url=f"{base_url}{new_path}",
        base_url=base_url,
        body=body,
        noindex=True,
        ga4_id=ga4_id,
        paid_links=paid_links,
        refresh_to=new_path,
    )


def render_privacy(*, base_url: str, ga4_id: str | None = None, paid_links: bool = False) -> str:
    """dist/privacy/index.html, linked from every page's footer. Rendered
    from the same GA4 ID as the pages' <head>, so it describes exactly what
    this build does: Google Analytics with its safeguards when an ID is
    set, "no analytics" when none is."""
    affiliate_note = AFFILIATE_NOTE_ACTIVE if _any_paid(paid_links) else AFFILIATE_NOTE_INACTIVE
    analytics_on = measurement_id(ga4_id) is not None
    if analytics_on:
        # The team-shop link exists only with the Fanatics link set
        # (team_shops.py), and its clicks are counted only then (analytics.py).
        counted_links = (
            "&ldquo;Buy tickets&rdquo;, official ticket page, &ldquo;Team shop&rdquo; and calendar-subscribe links"
            if shop_links_on()
            else "&ldquo;Buy tickets&rdquo;, official ticket page and calendar-subscribe links"
        )
        pages_section = f"""<h2>Web pages: Google Analytics</h2>
<p>This site's pages use Google Analytics 4, a Google service, to count page
views and clicks on {counted_links}, so
we can see which leagues and teams people use.</p>
<ul>
<li><strong>Not loaded if you ask not to be tracked.</strong> If your browser
sends Global Privacy Control or Do Not Track, the page never loads Google's
script: no request to Google, no cookie.</li>
<li><strong>Advertising features are off.</strong> Google signals and ad
personalization are disabled, and consent for ad storage, ad user data and
ad personalization is denied for every visitor.</li>
<li><strong>In the EEA, the UK and Switzerland</strong>, analytics storage is
denied as well, so Google Analytics sets no cookies on your device. Google
still receives a cookieless measurement request for each page view and link
click, with nothing stored on your device to recognize you next time.</li>
<li><strong>Everywhere else</strong>, Google Analytics sets first-party
cookies (named <code>_ga</code> and <code>_ga_</code> followed by an ID) to
tell a returning visitor from a new one.</li>
<li><strong>What Google receives:</strong> the page address and title, the
page you came from, the link you clicked (on this site), and your browser,
device type, language and screen size, from which Google also derives an
approximate location. Google says Google Analytics 4 does not log or store
IP addresses.</li>
<li><strong>Kept for {e(GA4_DATA_RETENTION)}.</strong> Google Analytics deletes
this site's event-level data after {e(GA4_DATA_RETENTION)}.</li>
<li><strong>Opt out on this device.</strong> Use &ldquo;Opt out of
analytics&rdquo; at the bottom of any page. It saves one setting in this
browser's local storage (not a cookie), and from the next page you open, this
site doesn't load Google Analytics in this browser at all. The page you are
on is also told to stop sending, through Google's own opt-out setting. The
same button then reads &ldquo;Opt back in&rdquo;, which removes the setting.
The choice applies to this browser on this device only, and clearing this
site's data in your browser clears it. It doesn't delete Google Analytics
cookies already set; your browser's settings can clear those.</li>
</ul>
<p>Google handles this data under its own terms: see
<a href="https://policies.google.com/technologies/partner-sites">how Google uses information from sites that use its services</a>.
To opt out, use &ldquo;Opt out of analytics&rdquo; at the bottom of any page,
turn on Global Privacy Control or Do Not Track in your browser, or install <a href="https://tools.google.com/dlpage/gaoptout">Google's Analytics opt-out browser add-on</a>.</p>
"""
        ticket_measured = " Google Analytics records only that the link was clicked, on this site's page."
        feed_clicks = """<p>On a web page, a click on a calendar-subscribe link is counted
by Google Analytics, as described above.</p>
"""
    else:
        pages_section = """<h2>Web pages: no analytics</h2>
<p>This site runs no analytics: no measurement service of any kind, no
scripts at all, and no cookies.</p>
"""
        ticket_measured = ""
        feed_clicks = ""
    if _buy_links_paid(paid_links):
        ticket_links = """<p>Every &ldquo;Buy tickets&rdquo; link goes to the home team's
own ticket seller's page for that team where we know it (for example AXS or
SeatGeek), otherwise to the address Ticketmaster publishes for that event. A
link marked &ldquo;Paid link&rdquo; first passes through the seller's
affiliate network, Impact, which records that this site sent you and then
forwards you to the seller. Every other link is used as-is. No link is routed
through this site or through Google."""
    else:
        ticket_links = """<p>Every &ldquo;Buy tickets&rdquo; link is a plain address: the home team's
own ticket seller's page for that team where we know it (for example AXS or
SeatGeek), otherwise the address Ticketmaster publishes for that event. It is
used as-is: never rewritten, and never routed through this site or through
Google."""
    paid_links_section = ""
    ads_exception = ""
    if _any_paid(paid_links):
        paid_links_section = """<h2>Paid links</h2>
<p>Some links are affiliate links, and each one has the label &ldquo;Paid
link&rdquo; right next to it. If you buy something after following one, the
seller pays this site a commission. A paid link passes through the affiliate
network Impact on its way to the seller. It carries one fixed ID that
identifies this site, never anything about you, and this site adds no script
and no cookie for it. Impact and the seller may set their own cookies once you
reach them, under their own privacy policies. A paid link never changes which
seller a game's &ldquo;Buy tickets&rdquo; link goes to.</p>
"""
        if analytics_on:
            paid_links_section += """<p>Google Analytics records a click on a paid link by the seller's
address it leads to, and notes that it was a paid link.</p>
"""
        ads_exception = " other than the paid links marked above"
    body = f"""<nav aria-label="breadcrumb"><a href="/">All leagues</a></nav>
<h1>Privacy</h1>
<p class="lede">What this site measures, what it never measures, and how to
opt out.</p>
{pages_section}<h2>Calendar feeds: what is and isn't measured</h2>
{feed_clicks}<p>The <code>.ics</code> calendar feeds carry game listings and nothing else:
no analytics, no image or pixel, and no redirecting links. A calendar app that
subscribes to a feed and re-fetches it is not measured by this site; the
host, GitHub Pages, receives those requests like any other (see Hosting). Ticket
links inside a feed are the plain Ticketmaster addresses for each game.</p>
<h2>Ticket links</h2>
{ticket_links}{ticket_measured} Following one takes you to that seller, which then
knows this site sent you. {affiliate_note} What happens there is covered by
the seller's own privacy policy.</p>
{paid_links_section}<h2>No accounts, no ads, no forms</h2>
<p>There is nothing to sign up for, no advertising{ads_exception}, and no form that collects
anything.</p>
<h2>Hosting</h2>
<p>Pages and calendar feeds are served by GitHub Pages. Like any web host,
GitHub receives each request's IP address and browser details; this site has
no access to those logs.</p>
<p>Updated {e(display_date(PRIVACY_UPDATED))}.</p>
"""
    return _base(
        title=f"Privacy | {SITE_NAME}",
        description="What Next Home Game measures, what it never measures, and how to opt out.",
        canonical_url=f"{base_url}{PRIVACY_PATH}",
        base_url=base_url,
        body=body,
        ga4_id=ga4_id,
        paid_links=paid_links,
    )


def render_accessibility(*, base_url: str, ga4_id: str | None = None, paid_links: bool = False) -> str:
    """dist/accessibility/index.html, linked from every page's footer: the
    published form of docs/a11y/STATEMENT.md (ACCESSIBILITY-STANDARD A11Y-16).
    It states a target and what is checked, never a conformance claim, and
    says plainly that no person has reviewed the site with assistive
    technology yet."""
    body = f"""<nav aria-label="breadcrumb"><a href="/">All leagues</a></nav>
<h1>Accessibility</h1>
<p class="lede"><strong>Accessibility status:</strong> {e(ACCESSIBILITY_STATUS)}</p>
<h2>What is checked on every change</h2>
<p>Every page this site publishes is checked automatically before a change is
accepted:</p>
<ul>
<li>pa11y, to the WCAG 2 AA standard, with two independent rule engines.</li>
<li>axe-core against WCAG 2.0, 2.1 and 2.2 A and AA rules, including color
contrast, target size and the page language.</li>
<li>A keyboard walk: the first Tab reaches &ldquo;Skip to main
content&rdquo;, every link can be reached, and each one shows a visible focus
outline that nothing covers.</li>
<li>Reflow: at 320 pixels wide nothing scrolls sideways.</li>
<li>Reduced motion: if you ask your device for less motion, nothing on the
site animates.</li>
</ul>
<h2>Known gaps</h2>
<ul>
<li>No person has yet checked the site with a screen reader (such as NVDA,
JAWS or VoiceOver) or with a keyboard alone. Automated checks catch many
problems but not all of them.</li>
<li>The calendar feeds are read by your own calendar app, so how
accessible they are depends on that app.</li>
<li>&ldquo;Buy tickets&rdquo; links go to Ticketmaster or to a team's own
ticket seller. Those sites are outside this statement.</li>
</ul>
<h2>Reporting a problem</h2>
<p>If something on this site gets in your way, tell us through
<a href="{e(ACCESSIBILITY_CONTACT_URL)}">the contact page at chelseakr.com</a>:
say which page and what happened. A problem that stops you finding a team,
subscribing to a calendar or following a ticket link is fixed first.</p>
<p>Updated {e(display_date(ACCESSIBILITY_UPDATED))}.</p>
"""
    return _base(
        title=f"Accessibility | {SITE_NAME}",
        description="How Next Home Game is checked for accessibility, its known gaps, and how to report a problem.",
        canonical_url=f"{base_url}{ACCESSIBILITY_PATH}",
        base_url=base_url,
        body=body,
        ga4_id=ga4_id,
        paid_links=paid_links,
    )


# The terms page's affiliate paragraph, in the two states the build can be in,
# following the same switch as the footer's AFFILIATE_NOTE_* (``_any_paid``).
TERMS_AFFILIATE_ACTIVE = (
    "Links marked &ldquo;Paid link&rdquo; are affiliate links: if you buy through one, "
    "this site earns a commission, and it costs you nothing extra. A paid link never "
    "changes which seller a game&rsquo;s &ldquo;Buy tickets&rdquo; link goes to. Every "
    "other link is plain, and this site is not paid for it."
)
TERMS_AFFILIATE_INACTIVE = (
    "Today no link on this site earns it money. If that changes, each paid link will "
    "be labeled as one where it appears, and this page will say so."
)


def render_terms(*, base_url: str, ga4_id: str | None = None, paid_links: bool = False) -> str:
    """dist/terms/index.html, linked from every page's footer: plain-language
    terms of use. Not reviewed by an attorney. Its affiliate paragraph follows
    the same switch as the footer, so it says "affiliate" exactly when a link
    can be one."""
    affiliate = TERMS_AFFILIATE_ACTIVE if _any_paid(paid_links) else TERMS_AFFILIATE_INACTIVE
    contact = "chelsea@chelseakr.com"
    mail = f'<a href="mailto:{e(contact)}">{e(contact)}</a>'
    body = f"""<nav aria-label="breadcrumb"><a href="/">All leagues</a></nav>
<h1>Terms of use</h1>
<p class="lede">These terms cover the {SITE_NAME} website and its calendar
feeds. By using them you accept these terms. They are short on purpose. If
anything here is unclear, email {mail}.</p>
<h2>Who runs this site</h2>
<p>{SITE_NAME} is run by one person, Chelsea Kelly-Reif, in California. You
can reach me at {mail}.</p>
<h2>What this site is, and is not</h2>
<p>{SITE_NAME} is a free calendar of home games for women&rsquo;s professional
and college teams. It is independent. It is not affiliated with or endorsed by
any league, team, school, Ticketmaster or any ticket seller. It does not sell
tickets and does not show ticket prices.</p>
<h2>The schedules can be wrong or late</h2>
<p>Game dates, times and venues come from the Ticketmaster Discovery API, not
from the leagues. Games are added, moved, postponed and canceled, sometimes
after they are listed, and the source can contain mistakes. This site reads
it on a schedule, so it can be behind, and the copying can add errors of its
own. A calendar event&rsquo;s end time is an estimate. Before you travel or
buy, check the game with the team or the ticket seller.</p>
<h2>Ticket links</h2>
<p>A &ldquo;Buy tickets&rdquo; link takes you to another company&rsquo;s site.
Anything you buy there is between you and that seller, under its own terms,
prices, fees and refund rules. I am not responsible for the seller, its site
or your purchase.</p>
<h2>Affiliate links</h2>
<p>{affiliate}</p>
<h2>No warranty</h2>
<p>The site and its feeds are provided &ldquo;as is&rdquo; and &ldquo;as
available,&rdquo; without any warranty, express or implied, including any
warranty of accuracy, completeness or fitness for a particular purpose. They
may be unavailable, slow or wrong at any time.</p>
<h2>Limit of liability</h2>
<p>To the fullest extent the law allows, I am not liable for any loss or
damage that comes from using or relying on this site or its feeds, including
a missed game, travel costs, ticket costs, or any indirect or consequential
loss. Where the law does not allow that, my total liability is limited to
US$50.</p>
<h2>Names and trademarks</h2>
<p>League, team and school names, Ticketmaster and the names of other ticket
sellers and stores are the names and trademarks of their owners. They appear
here only to say which game a listing is or where a link goes. Their owners do
not sponsor or endorse this site.</p>
<h2>Using the site</h2>
<p>You are welcome to read the site, link to it, share it and subscribe to its
calendar feeds. Please do not use it in a way that harms it or other people,
such as automated requests heavy enough to slow it down. To ask for a game to
be removed or to report a mistake, email {mail}.</p>
<h2>Changes to these terms</h2>
<p>I may update these terms. When I do, the date below changes. If you keep
using the site after that, the new version applies.</p>
<h2>Governing law</h2>
<p>These terms are governed by the laws of the State of California, USA. If
something goes wrong, please email me first, and I will try to fix it.</p>
<p>Updated {e(display_date(TERMS_UPDATED))}.</p>
"""
    return _base(
        title=f"Terms of use | {SITE_NAME}",
        description=(
            "Who runs Next Home Game, where its schedules come from, why they can be wrong "
            "or late, and how its ticket links work."
        ),
        canonical_url=f"{base_url}{TERMS_PATH}",
        base_url=base_url,
        body=body,
        ga4_id=ga4_id,
        paid_links=paid_links,
    )


# The official help pages /help/ follows, each read on HELP_UPDATED. Every
# step and every refresh figure on the page comes from one of these; where
# a page gives no figure, /help/ says the app does not publish one.
HELP_SOURCES: dict[str, str] = {
    "apple_icloud": "https://support.apple.com/en-us/102301",
    "apple_iphone_remove": "https://support.apple.com/en-us/102444",
    "apple_mac_refresh": "https://support.apple.com/guide/calendar/refresh-calendars-icl1024/mac",
    "apple_mac_delete": "https://support.apple.com/guide/calendar/delete-or-remove-calendars-icl1005/mac",
    "google_subscribe": "https://support.google.com/calendar/answer/37100",
    "google_unsubscribe": "https://support.google.com/calendar/answer/37188",
    "outlook_subscribe": (
        "https://support.microsoft.com/en-us/outlook/"
        "import-or-subscribe-to-a-calendar-in-outlook-com-or-outlook-on-the-web"
    ),
    "outlook_remove": "https://support.microsoft.com/en-us/outlook/add-a-calendar-in-outlook-com-or-outlook-on-the-web",
}
# The ticket sellers /help/ names as the reason a team can list few or no
# home games (DECISIONS 0013, 0034, 0036). tests/test_help_page.py checks
# each is a seller in sellers.PRIMARY_SELLERS, so the page cannot name one
# the seller table does not have.
HELP_NAMED_SELLERS = ("AXS", "SeatGeek", "Paciolan")
# The one team that sells through a Ticketmaster Account Manager store; the
# test checks the seller table still says so.
HELP_ACCOUNT_MANAGER_TEAM = ("ncaaw-sec", "missouri-tigers-womens-basketball")
HELP_ACCOUNT_MANAGER_NAME = "Missouri women's basketball"


def _help_source(key: str, text: str) -> str:
    return f'<a href="{e(HELP_SOURCES[key])}">{e(text)}</a>'


def render_help(*, base_url: str, ga4_id: str | None = None, paid_links: bool = False) -> str:
    """dist/help/index.html, linked from every page's header and footer
    (DECISIONS 0036): how to subscribe to a feed in Apple Calendar, Google
    Calendar and Outlook, how to unsubscribe, how often a feed updates, and
    why a game can be missing. Each app's steps and refresh behavior are
    what that app's own help page says (HELP_SOURCES); nothing is assumed.
    The page links no ticket seller, so it carries no paid link; the footer
    keeps the site's affiliate disclosure."""
    league = config.LEAGUES[0]
    team = league.teams[0]
    team_feed = f"{base_url}/ics/{league.slug}/{team.slug}.ics"
    league_feed = f"{base_url}/ics/{league.slug}.ics"
    all_feed = f"{base_url}/{COMBINED_FEED_PATH}"
    sellers = ", ".join(HELP_NAMED_SELLERS[:-1]) + f" or {HELP_NAMED_SELLERS[-1]}"
    contact = REMOVAL_CONTACT_EMAIL or "chelsea@chelseakr.com"
    mail = f'<a href="mailto:{e(contact)}">{e(contact)}</a>'
    body = f"""<nav aria-label="breadcrumb"><a href="/">All leagues</a></nav>
<h1>Calendar help</h1>
<p class="lede">Every team and league on this site has its own calendar feed.
Subscribe once, and its games show up in the calendar app you already use.
Here is how, app by app, and how to stop.</p>
<ul class="help-contents">
<li><a href="#help-address">Find the calendar address</a></li>
<li><a href="#help-apple">Apple Calendar (iPhone, iPad, Mac)</a></li>
<li><a href="#help-google">Google Calendar</a></li>
<li><a href="#help-outlook">Outlook</a></li>
<li><a href="#help-unsubscribe">Unsubscribe</a></li>
<li><a href="#help-refresh">How often your calendar updates</a></li>
<li><a href="#help-missing">Why a game might be missing</a></li>
<li><a href="#help-contact">Report a problem</a></li>
</ul>

<h2 id="help-address">Find the calendar address</h2>
<p>On a team or league page, the &ldquo;Add to&hellip;&rdquo; buttons near the
top do the steps below for you. If a button does not work, scroll to
&ldquo;Other calendar apps&rdquo; on the same page and copy the address shown
there. It ends in <code>.ics</code>. For example:</p>
<ul class="help-addresses">
<li>One team ({e(team.shown_name)}): <code>{e(team_feed)}</code></li>
<li>One league ({e(league.name)}): <code>{e(league_feed)}</code></li>
<li>Every league on the site: <code>{e(all_feed)}</code></li>
</ul>
<p>Subscribe to the address; do not download the file and import it. An
imported file is a one-time copy and never updates (Microsoft&rsquo;s
{_help_source("outlook_subscribe", "Outlook help")} says so plainly).</p>

<h2 id="help-apple">Apple Calendar</h2>
<h3>iPhone or iPad</h3>
<p>The quickest way is the &ldquo;Add to Apple Calendar&rdquo; button on a team
page. To do it by hand (iOS or iPadOS 26 or later):</p>
<ol>
<li>Open Calendar and tap the Calendars button.</li>
<li>Tap Add Calendar, then tap Add Subscription Calendar.</li>
<li>Paste the calendar address, then tap Find.</li>
<li>Give it a name and color. Next to Account, choose iCloud so it shows on
all your Apple devices.</li>
<li>Tap Done.</li>
</ol>
<p>On iOS 18 or earlier, tap Calendars at the bottom of the screen, then Add
Calendar &rsaquo; Add Subscription Calendar, paste the address and tap
Subscribe.</p>
<h3>Mac</h3>
<ol>
<li>In Calendar, choose File &rsaquo; New Calendar Subscription.</li>
<li>Paste the calendar address, then click Subscribe.</li>
<li>Give it a name and color. Next to Location, choose iCloud so it shows on
your other Apple devices.</li>
<li>Click OK.</li>
</ol>
<p class="help-source">Source: Apple,
{_help_source("apple_icloud", "Add calendar subscriptions in iCloud")}.</p>

<h2 id="help-google">Google Calendar</h2>
<p>Google adds a calendar by address only on a computer, in a web browser, not
in the Google Calendar phone app.</p>
<ol>
<li>Open Google Calendar on your computer.</li>
<li>On the left, next to &ldquo;Other calendars,&rdquo; click Add other
calendars (+), then From URL.</li>
<li>Paste the calendar address.</li>
<li>Click Add calendar. It appears on the left, under &ldquo;Other
calendars.&rdquo;</li>
</ol>
<p class="help-source">Source: Google,
{_help_source("google_subscribe", "Subscribe to someone else's calendar")}.</p>

<h2 id="help-outlook">Outlook</h2>
<h3>Outlook.com (a personal Microsoft account)</h3>
<ol>
<li>Sign in to Outlook.com and open Calendar.</li>
<li>Select Add calendar, then Subscribe from web.</li>
<li>Paste the calendar address, then select Import.</li>
</ol>
<h3>Outlook on the web (a work or school account)</h3>
<ol>
<li>Sign in to Outlook on the web and open Calendar.</li>
<li>Select Add calendar, then Subscribe from web.</li>
<li>Paste the calendar address, then select Import and Save.</li>
</ol>
<p>Choose Subscribe from web, not Upload from file: an uploaded file never
updates.</p>
<p class="help-source">Source: Microsoft,
{_help_source("outlook_subscribe", "Import or subscribe to a calendar in Outlook.com or Outlook on the web")}.</p>

<h2 id="help-unsubscribe">Unsubscribe</h2>
<p>There is no account here to cancel. Remove the calendar in your app and the
games are gone from it.</p>
<ul>
<li><strong>iPhone or iPad:</strong> in Calendar, tap the Calendars button,
tap the info button next to the calendar, tap Unsubscribe, then tap
Unsubscribe again to confirm
({_help_source("apple_iphone_remove", "Apple's steps")}).</li>
<li><strong>Mac:</strong> in Calendar, click the calendar&rsquo;s name in the
calendar list (View &rsaquo; Show Calendar List if you do not see it), then
choose Edit &rsaquo; Delete
({_help_source("apple_mac_delete", "Apple's steps")}).</li>
<li><strong>Google Calendar:</strong> on a computer, click Settings at the top
right, select the calendar in the left column, click Remove calendar, then
Unsubscribe, and confirm with Remove calendar
({_help_source("google_unsubscribe", "Google's steps")}).</li>
<li><strong>Outlook.com or Outlook on the web:</strong> in your list of
calendars, select More options next to the calendar, then Remove
({_help_source("outlook_remove", "Microsoft's steps")}).</li>
</ul>

<h2 id="help-refresh">How often your calendar updates</h2>
<p>This site rebuilds every feed once a night, shortly after midnight Pacific
time. Each feed asks calendar apps to check it again once a day. Your app
decides when it actually checks:</p>
<ul>
<li><strong>Apple Calendar on a Mac:</strong> you choose. Control-click the
calendar&rsquo;s name, choose Get Info, and pick a setting from the
Auto-refresh menu
({_help_source("apple_mac_refresh", "Apple's steps")}).</li>
<li><strong>Apple Calendar on iPhone or iPad:</strong> Apple does not publish
how often it checks a subscribed calendar, so it varies.</li>
<li><strong>Google Calendar:</strong> Google does not publish how often it
checks a calendar added by address, so it varies.</li>
<li><strong>Outlook.com:</strong> Microsoft says about every 3 hours, though an
update can take more than 24 hours.</li>
<li><strong>Outlook on the web (work or school):</strong> Microsoft says about
every 6 hours, though an update can take more than 24 hours.</li>
</ul>
<p>So a new game or a time change can take a day or more to reach your
calendar. Before you travel or buy tickets, check the game with the team or
the ticket seller.</p>

<h2 id="help-missing">Why a game might be missing</h2>
<ul>
<li><strong>This site reads one source.</strong> Every game comes from
Ticketmaster&rsquo;s public listings. No league&rsquo;s or team&rsquo;s own
schedule is used, so a game Ticketmaster does not list is not here.</li>
<li><strong>Some teams sell tickets somewhere else.</strong> Teams that sell
through {e(sellers)} may show few or no home games here. So may
{e(HELP_ACCOUNT_MANAGER_NAME)}, which sells through its own Ticketmaster Account Manager store;
those games are not in Ticketmaster&rsquo;s public listings. When one of
these teams has no games listed, its page names its seller and links to
it.</li>
<li><strong>Not listed yet.</strong> A game appears with the first nightly
rebuild after Ticketmaster lists it.</li>
<li><strong>No date yet.</strong> A game whose date Ticketmaster has not set
is shown on its team page but left out of the calendar feed until it has
one. A game with a date but no start time is in the feed as an all-day
event marked &ldquo;time TBA.&rdquo;</li>
<li><strong>Canceled or postponed.</strong> These stay in the feed, marked
with their status, so your calendar does not keep showing a game that is
off as if it were on.</li>
</ul>

<h2 id="help-contact">Report a problem</h2>
<p>If a game is missing or wrong, or these steps do not match what you see,
email {mail}. Name the team and the date, and the calendar app you use.</p>
<p>Updated {e(display_date(HELP_UPDATED))}.</p>
"""
    return _base(
        title=f"Calendar help: subscribe and unsubscribe | {SITE_NAME}",
        description=(
            "How to add a team's games to Apple Calendar, Google Calendar or Outlook, "
            "how to unsubscribe, how often feeds update, and why a game can be missing."
        ),
        canonical_url=f"{base_url}{HELP_PATH}",
        base_url=base_url,
        body=body,
        ga4_id=ga4_id,
        paid_links=paid_links,
    )


SCHEDULE_PATH = "/schedule/"


def _names_and(names: list[str]) -> str:
    """ "WNBA, NWSL and PWHL"."""
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _long_date(iso_date: str) -> str:
    """ "Thursday, October 1" from an ISO date."""
    d = date.fromisoformat(iso_date)
    return f"{d:%A}, {d:%B} {d.day}"


def _schedule_day(day: Mapping[str, Any]) -> str:
    """One day's games: a heading naming the date, then a table."""
    label = _long_date(day["date"])
    rows = []
    for g in day["games"]:
        matchup = _matchup_text(g)
        buy = (
            _buy_link(g, matchup, short=True) or '<span class="ticket-unavailable">no ticket link published yet</span>'
        )
        rows.append(
            "<tr>"
            f'<td><span class="game-date">{_when_html(g)}</span></td>'
            f'<td><a href="/{e(g["league_slug"])}/">{e(g["league_name"])}</a></td>'
            f"<td>{e(matchup)}</td>"
            f"<td>{e(_venue_text(g))}</td>"
            f"<td>{buy}</td>"
            "</tr>"
        )
    return f"""<section class="schedule-day" aria-labelledby="day-{e(day["date"])}">
<h2 id="day-{e(day["date"])}">{e(label)}</h2>
{_games_table_wrap_open(f"games-caption-{day['date']}")}
<table class="games-table">
<caption id="games-caption-{e(day["date"])}" class="sr-caption">Games on {e(label)}, from Ticketmaster</caption>
<thead>
<tr>
<th scope="col">Date and time</th>
<th scope="col">League</th>
<th scope="col">Matchup</th>
<th scope="col">Venue</th>
<th scope="col">Tickets</th>
</tr>
</thead>
<tbody>
{"".join(rows)}
</tbody>
</table>
</div>
</section>
"""


def render_schedule(
    *,
    schedule: Mapping[str, Any],
    leagues: list[dict[str, Any]],
    base_url: str,
    ga4_id: str | None = None,
    paid_links: bool = False,
) -> str:
    """dist/schedule/index.html: every tracked league's listed games, day by
    day, for the days in site_data.schedule_data. The days are named by
    date, never "today": the page is built once a night and read at any
    time, and it states when its listings were fetched."""
    if not schedule["fetched"]:
        listing = f'<p class="no-games-message">{e(NOT_FETCHED_MSG)}</p>\n'
        lede = "Every tracked league's games, day by day, for the week ahead."
    else:
        first, last = _long_date(schedule["first_day"]), _long_date(schedule["last_day"])
        lede = (
            f"Every game Ticketmaster lists for a tracked league from {first} through {last}, "
            "by the venue's local date. Times are the venue's local time."
        )
        if schedule["days"]:
            listing = "".join(_schedule_day(day) for day in schedule["days"])
        else:
            listing = (
                f'<p class="no-games-message">Ticketmaster lists no games for any tracked league '
                f"from {e(first)} through {e(last)}.</p>\n"
            )
        if schedule["possibly_incomplete"]:
            listing = _possibly_incomplete_note(_names_and(schedule["possibly_incomplete"])) + "\n" + listing
    league_links = "\n".join(
        f'<li><a href="/{e(lg["slug"])}/">{e(lg["name"])} schedule and calendar feed</a></li>' for lg in leagues
    )
    body = f"""{_breadcrumb([("All leagues", "/")], "Schedule")}
<h1>The week ahead in every league</h1>
<p class="lede">{e(lede)}</p>
{_freshness_note(schedule)}{listing}<section class="league-links" aria-labelledby="by-league-heading">
<h2 id="by-league-heading">One league at a time</h2>
<p>Each league's page lists its whole season and has its calendar feed to subscribe to.</p>
<ul>
{league_links}
</ul>
</section>
"""
    return _base(
        title=f"The week ahead in every league | {SITE_NAME}",
        description=f"Every listed {_names_and([lg['name'] for lg in leagues])} game for the week ahead, day by day.",
        canonical_url=f"{base_url}{SCHEDULE_PATH}",
        base_url=base_url,
        body=body,
        ga4_id=ga4_id,
        paid_links=paid_links,
    )


def render_league(
    *,
    league: dict[str, Any],
    base_url: str,
    ga4_id: str | None = None,
    paid_links: bool = False,
    feed_keys: frozenset[str] = frozenset(),
) -> str:
    slug = league["league_slug"]
    name = league["league_name"]
    season = league.get("season")
    fetched = league.get("fetched", True)
    ics_https = f"{base_url}/ics/{slug}.ics"
    page_url = f"{base_url}/{slug}/"
    # The team's real name ("Gotham FC", "UCLA Bruins Womens Basketball"),
    # not a title-cased slug ("Gotham Fc", "Ucla Bruins ...") -- this list is
    # the league page's only internal link to each team page.
    team_names = league.get("team_names") or {}

    def team_name(slug_: str) -> str:
        return team_names.get(slug_) or slug_.replace("-", " ").title()

    team_links = "\n".join(f'<li><a href="/{e(slug)}/{e(t)}/">{e(team_name(t))}</a></li>' for t in league["teams"])
    incomplete = league.get("possibly_incomplete_teams") or []
    incomplete_note = (
        _possibly_incomplete_note(", ".join(team_name(t) for t in incomplete)) + "\n" if incomplete else ""
    )
    # "Big Ten women's basketball 2026-27 schedule", not "NCAA Women's
    # Basketball (Big Ten) ...": the heading and title use the name a fan
    # searches; the breadcrumb and body keep the league's own name.
    heading = _schedule_heading(league_names_for(slug, name)[0], season)
    body = f"""{_breadcrumb([("All leagues", "/")], name)}
<h1>{e(heading)}</h1>
<p class="lede">Every {e(name)} game Ticketmaster lists, with its date, time
and venue. Add the whole league to your calendar, or pick a team below for
just its games.</p>
{_subscribe_block(ics_https_url=ics_https, subject=f"the {name} schedule", cal_name=calendar_name(name))}
<h2>{e(name)} team schedules</h2>
<ul class="team-roster">
{team_links}
</ul>
{_official_tickets_block(official_tickets.league_page(slug), subject=name, owner="the league's")}<h2>Upcoming games</h2>
{incomplete_note}{_freshness_note(league)}{_games_table(league["games"], buy_link_subject=name, fetched=fetched)}
<p class="league-week-link"><a href="{SCHEDULE_PATH}">The week ahead in every league, day by day</a></p>
{_other_apps_block(ics_https_url=ics_https)}{_about_schedule(league["schedule_source_note"])}"""
    og_image, og_image_alt = LEAGUE_OG_IMAGES.get(slug, (DEFAULT_OG_IMAGE, DEFAULT_OG_IMAGE_ALT))
    nodes = [
        structured_data.breadcrumbs([("All leagues", f"{base_url}/"), (name, page_url)]),
        *structured_data.sports_events(league["games"], sport=league.get("sport", ""), fetched=fetched),
    ]
    return _base(
        feed=_feed_for(feed_keys, league["league_slug"], base_url),
        title=_fit([f"{heading}: add to your calendar | {SITE_NAME}", f"{heading} | {SITE_NAME}", heading], TITLE_MAX),
        description=_league_description(heading, league),
        canonical_url=page_url,
        base_url=base_url,
        body=body,
        og_image=og_image,
        og_image_alt=og_image_alt,
        noindex=kept_out_of_search(league),
        ga4_id=ga4_id,
        paid_links=paid_links,
        jsonld=structured_data.script_block(nodes),
    )


def _league_description(heading: str, league: dict[str, Any]) -> str:
    """A league page's meta description. When the build checked Ticketmaster
    and it listed no game, it says so, as an empty team page's does: an
    empty league page with an official ticket link is indexed (DECISIONS
    0021), and a search result must not promise games that are not there."""
    if league.get("fetched", True) and not league["games"]:
        return _fit(
            [
                f"{heading}. No games are listed right now; add it to your calendar and "
                "games appear as they are listed, updated nightly.",
                f"{heading}. No games are listed right now; add it to your calendar and "
                "games appear as they are listed.",
                f"{heading}. No games are listed right now.",
            ],
            DESCRIPTION_MAX,
        )
    return _fit(
        [
            f"{heading}: add every game to Google Calendar, Apple Calendar or Outlook, or just "
            "your team's, with dates, times and venues, updated nightly.",
            f"{heading}: add every game, or just your team's, to your calendar, with dates, "
            "times, venues and ticket links. Updated nightly.",
            f"{heading}: add every game, or just your team's, to your calendar, with dates, "
            "times, venues and ticket links.",
            f"{heading}: add every game, or just your team's, to your calendar, with dates and ticket links.",
            f"{heading}: add every game to your calendar, updated nightly.",
        ],
        DESCRIPTION_MAX,
    )


def _opponent_label(league_slug: str, opponent: str) -> str:
    """The away team as a meta description names it: a Big Ten opponent by its
    school ("Rutgers"), or a school outside the registry by its Ticketmaster name
    without the "Womens Basketball" suffix, not the full keyword ("Rutgers
    Scarlet Knights Womens Basketball")."""
    return _WOMENS_BASKETBALL_SUFFIX.sub("", title_name_for(league_slug, opponent))


# The suffix in every spelling Ticketmaster lists ("Womens Basketball",
# "Women's Basketball", "Womans Basketball", "Women Basketball") and the registry's own
# ("women's basketball"): a description that kept "Mercyhurst Lakers Womans
# Basketball" ran too long for its fuller forms.
_WOMENS_BASKETBALL_SUFFIX = re.compile(r"\s+wom[ae]n(?:[\u2019']?s)? basketball$", re.IGNORECASE)


def _team_description(team: Mapping[str, Any]) -> str:
    """The meta description, at most DESCRIPTION_MAX characters: the next home
    game with its real date when one is listed, and the words a fan types
    (schedule, ticket links). With no home game listed it says nothing about
    one."""
    name = title_name_for(team["league_slug"], team["team_name"])
    league = league_names_for(team["league_slug"], team.get("league_name", ""))[1]
    season = team.get("season")
    # "<team> (<league>) schedule <season>": the league is in the queries
    # ("pwhl sirens schedule", "pwhl schedule ottawa"). A name that already
    # says it ("PWHL Detroit") does not say it twice (DECISIONS 0038).
    plain_lead = f"{name} schedule {season}" if season else ""
    lead = (plain_lead if league in name else f"{name} ({league}) schedule {season}") if league and season else ""
    home = next((g for g in team["games"] if g["event_id"] == team.get("next_home_event_id")), None)
    if home is not None and not home.get("date_tbd") and home.get("away_team"):
        when = f"{home['start_display']} vs {_opponent_label(team['league_slug'], home['away_team'])}"
        return _fit(
            [
                *(
                    [
                        f"{lead}. Next home game: {when}. Add every game to your calendar, with ticket links.",
                        f"{lead}. Next home game: {when}. With ticket links.",
                    ]
                    if lead
                    else []
                ),
                # A name too long for the league in parentheses still leads
                # with "<team> schedule <season>" (DECISIONS 0038).
                *([f"{plain_lead}. Next home game: {when}. With ticket links."] if plain_lead else []),
                f"Next {name} home game: {when}. Add every game to your calendar, with ticket links, updated nightly.",
                f"Next home game: {when}. Add every {name} game to your calendar, with ticket links, updated nightly.",
                f"Next home game: {when}. Add the {name} schedule to your calendar. Updated nightly.",
                f"Next {name} home game: {when}.",
                f"Next {name} home game: {home['start_display']}.",
            ],
            DESCRIPTION_MAX,
        )
    seller = team_primary_seller(team["league_slug"], team["team_slug"])
    owner = "The school's" if team["league_slug"].startswith("ncaaw-") else "The team's"
    awaited = _awaited_season(team)
    if not team["games"]:
        if awaited:
            # "<team> schedule 2027", the order the title uses (_team_title).
            # "next valkyries home game" ranks here too, so the snippet answers
            # it truthfully: none is listed (DECISIONS 0038).
            return _fit(
                [
                    f"{name} schedule {awaited}. Ticketmaster has not listed the {awaited} schedule yet, so no next "
                    "home game is listed; add it to your calendar and games appear.",
                    f"{name} schedule {awaited}. Ticketmaster has not listed the {awaited} schedule yet, so no next "
                    "home game is listed; add it to your calendar.",
                    f"{name} schedule {awaited}. Ticketmaster has not listed the {awaited} schedule yet; "
                    "add it to your calendar.",
                    f"{name} schedule {awaited}. Ticketmaster has not listed it yet.",
                ],
                DESCRIPTION_MAX,
            )
        if team.get("fetched", True) and seller is not None:
            # The body's wording (_sells_elsewhere_msg): no promise that home
            # games will reach the calendar on their own.
            return _fit(
                [
                    f"{name} schedule. No games are listed right now. {owner} main ticket seller is "
                    f"{seller.name}, {seller.contrast}, so home games may not show up here.",
                    f"{name} schedule. No games are listed right now. {owner} main ticket seller is "
                    f"{seller.name}, so home games may not show up here.",
                    f"{name} schedule. No games are listed right now. {owner} main ticket seller is {seller.name}.",
                    f"{name} schedule. No games are listed right now.",
                ],
                DESCRIPTION_MAX,
            )
        if team.get("fetched", True):
            return _fit(
                [
                    f"{name} schedule. No games are listed right now; add it to your calendar and "
                    "games appear as they are listed, updated nightly.",
                    f"{name} schedule. No games are listed right now; add it to your calendar and "
                    "games appear as they are listed.",
                    f"{name} schedule. No games are listed right now.",
                ],
                DESCRIPTION_MAX,
            )
        # Not fetched this build: nothing about whether games are listed.
        return _fit(
            [
                f"{name} schedule. Subscribe once in Google Calendar, Apple Calendar or Outlook; the calendar "
                "is rebuilt every night from the listings.",
                f"{name} schedule. Subscribe once in your calendar app; the calendar is rebuilt every night "
                "from the listings.",
                f"{name} schedule. Add it to your calendar, updated nightly.",
                f"{name} schedule.",
            ],
            DESCRIPTION_MAX,
        )
    if home is None and seller is not None and team.get("fetched", True):
        # Games are listed but no home game (the Minnesota Frost sell on
        # SeatGeek): never "every home and away game".
        schedule = f"{name} schedule {season}" if season else f"{name} schedule"
        return _fit(
            [
                *(
                    [
                        f"{lead}: listed games with dates, venues and ticket links. No home game is listed: "
                        f"{owner.lower()} main ticket seller is {seller.name}."
                    ]
                    if lead
                    else []
                ),
                f"{schedule}: listed games with dates, venues and ticket links. No home game is listed: "
                f"{owner.lower()} main ticket seller is {seller.name}.",
                f"{schedule}: listed games with dates and ticket links. No home game is listed: "
                f"{owner.lower()} main ticket seller is {seller.name}.",
                f"{schedule}: listed games and ticket links. No home game is listed: "
                f"{owner.lower()} main ticket seller is {seller.name}.",
                f"{name} schedule. No home game is listed: {owner.lower()} main ticket seller is {seller.name}.",
                f"{name} schedule.",
            ],
            DESCRIPTION_MAX,
        )
    if home is None:
        # Only away games are listed (or an unfetched build's kept games):
        # never "every home and away game" (DECISIONS 0037).
        schedule = f"{name} schedule {season}" if season else f"{name} schedule"
        return _fit(
            [
                *(
                    [
                        f"{lead}: listed games with dates, venues and ticket links. No home game is listed yet; "
                        "add it to your calendar."
                    ]
                    if lead
                    else []
                ),
                f"{schedule}: listed games with dates, venues and ticket links. No home game is listed yet; "
                "add it to your calendar.",
                f"{schedule}: listed games with dates and ticket links. No home game is listed yet; "
                "add it to your calendar.",
                f"{name} schedule and ticket links. Add it to your calendar.",
                f"{name} schedule.",
            ],
            DESCRIPTION_MAX,
        )
    return _fit(
        [
            *(
                [f"{lead}: every home and away game with dates, venues and ticket links. Add it to your calendar."]
                if lead
                else []
            ),
            f"{name} schedule: every home and away game with dates, venues and ticket links. "
            "Add it to Google, Apple or Outlook calendar, updated nightly.",
            f"{name} schedule: every home and away game with dates, venues and ticket links. "
            "Add it to your calendar, updated nightly.",
            f"{name} schedule with dates, venues and ticket links. Add it to your calendar, updated nightly.",
            f"{name} schedule and ticket links. Add it to your calendar.",
            f"{name} schedule.",
        ],
        DESCRIPTION_MAX,
    )


def _this_week_block(team: Mapping[str, Any]) -> str:
    """A team page's "this week" strip: this team's listed games in the
    window the /schedule/ page covers, and a link to that page. A build that
    fetched nothing says nothing about games, only links; a fetched build
    with no game in the window says exactly that, with the dates."""
    link = f'<a href="{SCHEDULE_PATH}">The week ahead in every league, day by day</a>'
    fetched_at = team.get("fetched_at")
    if not team.get("fetched", True) or not fetched_at:
        return f"""<section class="this-week" aria-labelledby="this-week-heading">
<h2 id="this-week-heading">This week</h2>
<p>{link}</p>
</section>
"""
    first, last = schedule_window(datetime.fromisoformat(fetched_at))
    in_window = [
        g
        for g in team["games"]
        if not g.get("date_tbd")
        and g.get("start_local_date")
        and first <= date.fromisoformat(g["start_local_date"]) <= last
    ]
    span = f"{_long_date(first.isoformat())} through {_long_date(last.isoformat())}"
    if in_window:
        rows = "\n".join(
            f'<li><span class="game-date">{_when_html(g)}</span> {e(_matchup_text(g))}{_home_away_tag(g)}</li>'
            for g in in_window
        )
        body = f"<p>{e(team['team_name'])} games listed from {e(span)}:</p>\n<ul>\n{rows}\n</ul>\n<p>{link}</p>"
    else:
        body = f"<p>No {e(team['team_name'])} game is listed from {e(span)}.</p>\n<p>{link}</p>"
    return f"""<section class="this-week" aria-labelledby="this-week-heading">
<h2 id="this-week-heading">This week</h2>
{body}
</section>
"""


def _full_date(iso_date: str) -> str:
    """ "Sunday, November 8, 2026" from an ISO date, for a sentence."""
    d = date.fromisoformat(iso_date)
    return f"{d:%A}, {d:%B} {d.day}, {d.year}"


def _checked_on(team: Mapping[str, Any]) -> str:
    """When this build read Ticketmaster, as "as of <date>" (the UTC date the
    freshness note also gives), or "right now" when no fetch time was
    recorded. Never a date that was not the check's."""
    fetched_at = team.get("fetched_at")
    if not fetched_at:
        return "right now"
    when = datetime.fromisoformat(str(fetched_at)).astimezone(UTC)
    return f'as of <time datetime="{e(when.date().isoformat())}">{e(_full_date(when.date().isoformat()))}</time>'


def _next_home_sentence(name: str, league_slug: str, game: Mapping[str, Any]) -> str:
    """ "The next USC women's basketball home game is against Utah State
    Aggies at Galen Center in Los Angeles, CA, on Sunday, November 8, 2026,
    at 5:00 PM PST." Each part is said only when Ticketmaster published it:
    no opponent, venue, date or time is ever filled in. The time is the
    venue's local time with its zone, as display_start wrote it."""
    against = f" against {e(_opponent_label(league_slug, game['away_team']))}" if game.get("away_team") else ""
    place = ", ".join(p for p in (game.get("venue_city"), game.get("venue_state")) if p)
    if game.get("venue_name"):
        where = f" at {e(game['venue_name'])}" + (f" in {e(place)}" if place else "")
    else:
        where = f" in {e(place)}" if place else ""
    iso_date = None if game.get("date_tbd") else game.get("start_local_date")
    if iso_date is None:
        return f"The next {name} home game Ticketmaster lists is{against}{where}; its date is not announced yet."
    day = display_date(date.fromisoformat(iso_date))
    shown = str(game.get("start_display") or "")
    clock = shown[len(day) + 2 :] if shown.startswith(f"{day}, ") else ""
    machine = game.get("start_local_datetime") or iso_date
    when = f'<time datetime="{e(machine)}">{e(_full_date(iso_date))}{f", at {e(clock)}" if clock else ""}</time>'
    tail = "" if clock else ", start time not announced yet"
    status = f" Ticketmaster lists it as {e(game['status'].lower())}." if game.get("status") else ""
    comma = "," if against or where else ""
    return f"The next {name} home game is{against}{where}{comma} on {when}{tail}.{status}"


def _team_lede(team: Mapping[str, Any]) -> str:
    """The team page's opening paragraph. Its first sentence answers the
    question the page is searched for, in the name a fan searches ("USC
    women's basketball", Team.title_name; the shown name where none is set):
    the next home game with its opponent, venue, date and local time, or, when
    none is listed, that none is, with the date Ticketmaster was checked
    (DECISIONS 0025). The rest says what the page lists, each claim only when
    the page backs it: the season when the listed games give one, "tickets"
    when a game links to a seller, "home games" when a game is known to be at
    home. It links the league's page (the hub), so the league is one click
    away from the body text and not only from the breadcrumb."""
    league_slug = team["league_slug"]
    name = e(title_name_for(league_slug, team["team_name"]))
    league_short = league_names_for(league_slug, team["league_name"])[1]
    league_link = f'<a href="/{e(league_slug)}/">{e(league_short)}</a>'
    if not team.get("fetched", True):
        # Not checked: says what the page is for and nothing about games.
        return (
            f'<p class="lede">Every {name} ({league_link}) game Ticketmaster\n'
            "lists, home and away, with its date, time and venue.</p>"
        )
    games = team["games"]
    checked = _checked_on(team)
    if not games:
        return (
            f'<p class="lede">Ticketmaster lists no upcoming {name} ({league_link}) game,\n'
            f"home or away, {checked}. Add the schedule to your calendar below, and each\n"
            "game appears in it once it is listed.</p>"
        )
    home_game = next((g for g in games if g["event_id"] == team.get("next_home_event_id")), None)
    first = (
        _next_home_sentence(name, league_slug, home_game)
        if home_game is not None
        else f"Ticketmaster lists no upcoming {name} home game {checked}."
    )
    season = team.get("season")
    for_season = f" for the {e(season)} season" if season else ""
    tickets = " and where to buy tickets" if any(g.get("buy") for g in games) else ""
    home = (
        f"\n{name} home games are marked &ldquo;Home&rdquo;."
        if any(g.get("tracked_team_is_home") is True for g in games)
        else ""
    )
    return (
        f'<p class="lede">{first}\nThis page has every {name} ({league_link}) game Ticketmaster\n'
        f"lists{for_season}, home and away, with its date, time, venue{tickets}.{home}</p>"
    )


def _sibling_teams_block(league_slug: str, team_slug: str, league_name: str) -> str:
    """Links to the other teams in the team's league, from the team registry
    (config.LEAGUES), so each team page leads to its neighbors. Empty for a
    league that is not in the registry or has no other team."""
    league = next((lg for lg in config.LEAGUES if lg.slug == league_slug), None)
    if league is None:
        return ""
    items = "\n".join(
        f'<li><a href="/{e(league_slug)}/{e(t.slug)}/">{e(t.shown_name)}</a></li>'
        for t in league.teams
        if t.slug != team_slug
    )
    if not items:
        return ""
    return f"""<section class="more-teams" aria-labelledby="more-teams-heading">
<h2 id="more-teams-heading">More {e(league_name)} team schedules</h2>
<ul class="team-roster">
{items}
</ul>
<p class="league-link"><a href="/{e(league_slug)}/">The full {e(league_name)} schedule, every team in one calendar</a></p>
</section>
"""


def _official_tickets_block(page: official_tickets.OfficialTicketPage | None, *, subject: str, owner: str) -> str:
    """The "Get <team> tickets" section: one link to the team's or league's
    own ticket page (official_tickets.py), shown whether or not any game is
    listed, so a page between seasons still says where tickets are sold.
    Empty when no official page was verified: never a guessed address. Plain
    unless an affiliate template is set for its host, and then labelled like
    every other paid link."""
    found = official_tickets.link_for(page)
    if page is None or found is None:
        return ""
    href, paid = found
    host = official_tickets.display_host(page.url)
    text = f"{e(subject)} {e(page.kind)} at {e(host)}, {e(owner)} official ticket page"
    link = _paid_link(href, text) if paid else f'<a href="{e(href)}">{text}</a>'
    return f"""<section class="{official_tickets.OFFICIAL_SECTION_CLASS}" aria-labelledby="official-tickets-heading">
<h2 id="official-tickets-heading">Get {e(subject)} tickets</h2>
<p>{link}.</p>
</section>
"""


def _team_shop_block(league_slug: str, team_slug: str, team_name: str) -> str:
    """The "Team shop" link to the team's Fanatics store (team_shops.py), on
    team pages only. Empty -- not an unpaid link -- unless the Fanatics
    affiliate link is configured and the team has a confirmed store page."""
    url = team_shop_url(league_slug, team_slug)
    if url is None:
        return ""
    link = _paid_link(url, f"Shop {e(team_name)} gear at Fanatics")
    return f"""<section class="team-shop" aria-labelledby="team-shop-heading">
<h2 id="team-shop-heading">Team shop</h2>
<p>{link}</p>
</section>
"""


# Team pages are built in one of two block orders. Off (the default, and the
# order the site has always had): the subscribe block, then the next home
# game. On: the next home game and its ticket link first, then the subscribe
# block, for a page that has a next home game; a page without one keeps the
# subscribe block first, since its "next game" section has no game or ticket
# link to lead with. A build-time constant, not a runtime or per-visitor
# choice, so a page is one order or the other (the roadmap's winter PWHL
# test is done by changing this and redeploying). Nothing else on the page,
# no link's rel or "Paid link" label, and no feed depends on it.
TEAM_PAGE_NEXT_GAME_FIRST = False


def _has_next_home_game(team: Mapping[str, Any]) -> bool:
    """True when the team page's next-game section shows a listed home game
    (the one _next_game_hero labels "Next home game" and links tickets for)."""
    if not team.get("fetched", True):
        return False
    return any(g["event_id"] == team.get("next_home_event_id") for g in team["games"])


def render_team(
    *,
    team: dict[str, Any],
    base_url: str,
    ga4_id: str | None = None,
    paid_links: bool = False,
    feed_keys: frozenset[str] = frozenset(),
) -> str:
    league_slug = team["league_slug"]
    team_slug = team["team_slug"]
    team_name = team["team_name"]
    league_name = team["league_name"]
    ics_https = f"{base_url}/ics/{league_slug}/{team_slug}.ics"
    page_url = f"{base_url}/{league_slug}/{team_slug}/"
    fetched = team.get("fetched", True)
    incomplete_note = _possibly_incomplete_note(team_name) + "\n" if team.get("possibly_incomplete") else ""
    # The <h1> uses the name a fan searches ("Nebraska women's basketball", not
    # the Ticketmaster keyword "Nebraska Cornhuskers Womens Basketball"); the
    # rest of the page, the feed and the calendar name keep the full name.
    heading = _schedule_heading(title_name_for(league_slug, team_name), team.get("season"))
    home_listed = bool(fetched and team.get("next_home_event_id"))
    h1 = f"{heading} and home games" if home_listed else heading
    search_name = title_name_for(league_slug, team_name)
    subscribe = _subscribe_block(
        ics_https_url=ics_https, subject=f"the {search_name} schedule", cal_name=calendar_name(team_name)
    )
    owner = "the school's" if league_slug.startswith("ncaaw-") else "the team's"
    tickets = _official_tickets_block(
        official_tickets.team_page(league_slug, team_slug), subject=search_name, owner=owner
    )
    hero = _next_game_hero(team)
    lead_blocks = (
        f"{hero}\n{subscribe}" if TEAM_PAGE_NEXT_GAME_FIRST and _has_next_home_game(team) else f"{subscribe}\n{hero}"
    )
    body = f"""{_breadcrumb([("All leagues", "/"), (league_name, f"/{league_slug}/")], team_name)}
<h1>{e(h1)}</h1>
{_team_lede(team)}
{_team_history_block(team)}{lead_blocks}
{tickets}<h2>Upcoming games</h2>
{incomplete_note}{_freshness_note(team)}{_games_table(team["games"], buy_link_subject=team_name, fetched=fetched, home_away=True)}
{_this_week_block(team)}{_other_apps_block(ics_https_url=ics_https)}{_team_shop_block(league_slug, team_slug, team_name)}{_sibling_teams_block(league_slug, team_slug, league_name)}{_about_schedule(team["schedule_source_note"])}"""
    og_image, og_image_alt = LEAGUE_OG_IMAGES.get(league_slug, (DEFAULT_OG_IMAGE, DEFAULT_OG_IMAGE_ALT))
    nodes = [
        structured_data.breadcrumbs(
            [("All leagues", f"{base_url}/"), (league_name, f"{base_url}/{league_slug}/"), (team_name, page_url)]
        ),
        structured_data.sports_team(
            name=team_name,
            page_url=page_url,
            sport=team.get("sport", ""),
            organization=team.get("organization_name", ""),
        ),
        *structured_data.sports_events(team["games"], sport=team.get("sport", ""), fetched=fetched),
    ]
    return _base(
        feed=_feed_for(feed_keys, team["league_slug"], base_url),
        title=_team_title(
            title_name_for(league_slug, team_name),
            team.get("season"),
            listed=bool(team["games"]),
            home_listed=home_listed,
            awaited_season=_awaited_season(team),
            official_ticket_page=_has_official_ticket_page(league_slug, team_slug),
        ),
        description=_team_description(team),
        canonical_url=page_url,
        base_url=base_url,
        body=body,
        og_image=og_image,
        og_image_alt=og_image_alt,
        noindex=kept_out_of_search(team),
        ga4_id=ga4_id,
        paid_links=paid_links,
        jsonld=structured_data.script_block(nodes),
    )


PACIFIC = ZoneInfo("America/Los_Angeles")
# AP style: March through July are never abbreviated, September is "Sept."
AP_MONTHS = ("Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec.")


def _pacific_stamp(when: datetime) -> str:
    """ "Thursday, Nov. 5, 2026, 12:25 AM PT": a build time in US order and
    Pacific time, where the nightly build and its owner are. Built by hand,
    not with %b/%p, so the output never depends on the machine's locale."""
    local = when.astimezone(PACIFIC)
    hour = local.hour % 12 or 12
    meridiem = "AM" if local.hour < 12 else "PM"
    return f"{local:%A}, {AP_MONTHS[local.month - 1]} {local.day}, {local.year}, {hour}:{local:%M} {meridiem} PT"


def _freshness_note(payload: Mapping[str, object]) -> str:
    """When these listings were read from Ticketmaster, stated on the page
    (DATA-GOVERNANCE-STANDARD DG-04): if the nightly build stops, readers can
    see the date instead of taking an old list as current. Empty when the
    build fetched nothing -- that case already says so -- or when no fetch
    time was recorded."""
    fetched_at = payload.get("fetched_at")
    if not payload.get("fetched", True) or not fetched_at:
        return ""
    when = datetime.fromisoformat(str(fetched_at)).astimezone(UTC)
    shown = _pacific_stamp(when)
    return (
        f'<p class="schedule-source-note data-freshness">Listings as of <time datetime="{e(when.isoformat(timespec="seconds"))}">'
        f"{e(shown)}</time>, from Ticketmaster. They are refreshed every night.</p>\n"
    )


# ---------------------------------------------------------------------------
# STYLE_CSS
#
# Palette -- "Floodlight" (DECISIONS 0035): a night game under the lights.
# Two brand constants, the same in light and dark mode, shared with
# pipeline/assets/favicon.svg and scripts/render_social_assets.py:
#   chrome #16131d  scoreboard black -- header, footer, hero ticket, table
#                    heads, subscribe buttons (18.34:1 with white)
#   hi     #d4f24a  floodlight lime, ONE meaning only: "this is a real next
#                    game" -- the hero date chip and its ticket button, and
#                    a non-zero league game count. Focus rings and button
#                    hovers borrow it; links never do (links are ink or
#                    white, underlined, in both modes). Never text on paper
#                    (1.27:1 on white). Chrome on lime: 14.50:1.
# Paper (light mode), all on #ffffff / the #f3f1f6 surface:
#   ink     #16131d  18.34:1 / 16.35:1
#   muted   #57526a   7.45:1 /  6.64:1
#   visited #7b2d6b   8.64:1 /  7.71:1  (berry, so visited never reads as ink)
#   border  #d6d2de  dividers only, never text
# On chrome (#16131d): white text and links 18.34:1, muted #cfcadb 11.46:1,
#   dim #a29cb4 6.94:1, visited pink #f2a7d8 9.86:1, lime focus 14.50:1.
# Dark mode canvas #0f0d14 / surface #1a1722 -- a warm black, not the blue
# night the portfolio's water sites use: ink #f1eff5 16.92:1, muted #b3adc2
#   8.89:1 / 8.13:1, links take the ink, visited #f2a7d8 10.38:1 / 9.49:1,
#   lime focus 15.26:1, button outline #a29cb4 on the surface 6.68:1.
# The motif is the ticket: the hero is a ticket with a perforated tear line
# and two notches, the subscribe box a ticket-stock card, and a two-tone
# "lane stripe" (lime then chrome) runs under each page's H1 and across
# the top of the header. All of it is decoration in CSS; nothing is an
# image of a league's or team's mark.
# ---------------------------------------------------------------------------

STYLE_CSS = """\
@font-face {
  font-family: "Big Shoulders Display";
  font-style: normal;
  font-weight: 500 800;
  font-display: optional;
  src: url("/fonts/big-shoulders-display-latin.woff2") format("woff2");
}
@font-face {
  font-family: "Big Shoulders Text";
  font-style: normal;
  font-weight: 500 800;
  font-display: optional;
  src: url("/fonts/big-shoulders-text-latin.woff2") format("woff2");
}
@font-face {
  font-family: "Public Sans";
  font-style: normal;
  font-weight: 400 700;
  font-display: swap;
  src: url("/fonts/public-sans-latin.woff2") format("woff2");
}

:root {
  color-scheme: light dark;

  /* brand -- constant in both modes */
  --chrome: #16131d;
  --hi: #d4f24a;

  /* content-area tokens (paper in light mode, a warm black in dark) */
  --bg: #ffffff;
  --surface: #f3f1f6;
  --ink: #16131d;
  --muted: #57526a;
  --border: #d6d2de;
  --link: #16131d;
  --link-visited: #7b2d6b;
  --focus: #16131d;
  /* subscribe-button outline: the button's own chrome on paper; in dark
     mode the on-chrome dim, so four chrome buttons on the dark surface stay
     distinct (#a29cb4 on #1a1722: 6.68:1) */
  --cta-border: #16131d;
  /* the subscribe card's edge: ink on paper, the dark border in dark mode */
  --card-edge: #16131d;

  /* chrome tokens -- header, footer, hero ticket: always scoreboard black */
  --on-chrome-fg: #ffffff;
  --on-chrome-muted: #cfcadb;
  --on-chrome-dim: #a29cb4;
  --on-chrome-link: #ffffff;
  --on-chrome-link-visited: #f2a7d8;
  --on-chrome-focus: #d4f24a;

  --display-font: "Big Shoulders Display", "Arial Narrow", sans-serif;
  --label-font: "Big Shoulders Text", "Arial Narrow", sans-serif;
  --body-font: "Public Sans", -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --measure: 34rem;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f0d14;
    --surface: #1a1722;
    --ink: #f1eff5;
    --muted: #b3adc2;
    --border: #2e2a3a;
    --link: #f1eff5;
    --link-visited: #f2a7d8;
    --focus: #d4f24a;
    --cta-border: #a29cb4;
    --card-edge: #2e2a3a;
  }
}

* { box-sizing: border-box; }

html { -webkit-text-size-adjust: 100%; }

body {
  background: var(--bg);
  color: var(--ink);
  font-family: var(--body-font);
  font-size: 1rem;
  line-height: 1.6;
  margin: 0;
  padding: 0;
}

main { max-width: 64rem; margin: 0 auto; padding: 0 1.25rem 3rem; }
/* Header/footer bands paint full-bleed (they're the brand chrome), but
   their content aligns to the same 64rem column as main -- so the
   wordmark and "Sources and terms" text line up with the H1 below them
   instead of floating flush against the true viewport edge on a wide
   screen. */
.site-footer > * { max-width: 64rem; margin-left: auto; margin-right: auto; }

h1, h2 {
  font-family: var(--display-font);
  font-weight: 800;
  line-height: 1.05;
  letter-spacing: -0.01em;
  margin: 0 0 0.5rem;
}
h1 { font-size: clamp(2rem, 5vw + 1rem, 3rem); margin-top: 1.75rem; }
/* The lane stripe: lime then chrome, decoration only. In dark mode the
   chrome half takes the ink color so it shows on the dark canvas. */
main > h1::after {
  content: ""; display: block; width: 4.5rem; height: 0.375rem; margin-top: 0.6rem;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--hi) 0 55%, var(--ink) 55% 100%);
}
h2 {
  font-size: clamp(1.15rem, 2vw + 0.8rem, 1.5rem);
  margin-top: 2.5rem;
  padding-top: 1.25rem;
  border-top: 1px solid var(--border);
}
main > h1:first-child, main > h2:first-of-type { border-top: 0; }

p { max-width: var(--measure); }
.lede { font-size: 1.0625rem; color: var(--muted); }

a { color: var(--link); text-underline-offset: 0.15em; }
a:visited { color: var(--link-visited); }
a:focus-visible, button:focus-visible, .games-table-wrap:focus-visible {
  outline: 3px solid var(--focus);
  outline-offset: 2px;
  border-radius: 2px;
}
@media (prefers-reduced-motion: no-preference) {
  a, .league-row-link, .next-game-cta, .subscribe-cta { transition: background-color 120ms ease, color 120ms ease, border-color 120ms ease; }
}

.skip-link {
  position: absolute; left: -999px; top: 0;
  background: var(--hi); color: var(--chrome); font-weight: 700;
  padding: 0.6rem 1rem; z-index: 10; text-decoration: none;
}
.skip-link:focus { left: 0.75rem; top: 0.75rem; border-radius: 0.25rem; }

/* ---- chrome: header + footer, always scoreboard black ---- */
.site-header {
  background: var(--chrome);
  border-top: 4px solid var(--hi);
  padding: 0.75rem 1.25rem;
}
.site-header-inner {
  display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
  gap: 0.25rem 1.25rem; max-width: 64rem; margin: 0 auto;
}
.brand {
  display: flex; align-items: center; gap: 0.6rem; min-height: 2.75rem;
  color: var(--on-chrome-fg); text-decoration: none;
  font-family: var(--display-font); font-weight: 800; font-size: 1.4rem;
  letter-spacing: 0.02em; text-transform: uppercase;
}
.brand:visited { color: var(--on-chrome-fg); }
.brand-mark { display: block; border-radius: 7px; }
.site-nav ul { list-style: none; display: flex; gap: 0.25rem 1.25rem; margin: 0; padding: 0; }
.site-nav a {
  display: inline-flex; align-items: center; min-height: 2.75rem;
  color: var(--on-chrome-fg); text-decoration: none;
  font-family: var(--label-font); font-weight: 700; font-size: 1rem; letter-spacing: 0.04em;
  text-transform: uppercase; border-bottom: 3px solid transparent;
}
.site-nav a:visited { color: var(--on-chrome-fg); }
.site-nav a:hover { border-bottom-color: var(--hi); }
.site-header a:focus-visible { outline-color: var(--on-chrome-focus); }

.site-footer { background: var(--chrome); color: var(--on-chrome-muted); margin-top: 3rem; border-top: 4px solid var(--hi); }
.site-footer > * { padding: 1.5rem 1.25rem 2rem; }
.site-footer h2 {
  color: var(--on-chrome-fg); border-top: 0; margin-top: 0; padding-top: 0;
  font-size: 1.05rem;
}
.site-footer p { max-width: 42rem; font-size: 0.9375rem; }
.site-footer a { color: var(--on-chrome-link); }
.site-footer a:visited { color: var(--on-chrome-link-visited); }
.site-footer a:focus-visible { outline-color: var(--on-chrome-focus); }
.site-footer .privacy-note { color: var(--on-chrome-dim); }
.analytics-toggle {
  background: none; border: 0; padding: 0.125rem 0; min-height: 1.5rem;
  color: var(--on-chrome-link); font: inherit; text-decoration: underline;
  text-underline-offset: 0.15em; cursor: pointer;
}
.site-footer button:focus-visible { outline-color: var(--on-chrome-focus); }

/* ---- breadcrumb + source note ---- */
nav[aria-label="breadcrumb"] {
  font-family: var(--label-font); font-weight: 600; letter-spacing: 0.01em;
  font-size: 0.9rem; margin-top: 1.5rem;
}
.schedule-source-note { color: var(--muted); font-size: 0.9375rem; }

/* ---- index: league scoreboard strip ---- */
.league-strip { list-style: none; margin: 0 0 2rem; padding: 0; border-top: 1px solid var(--border); }
.league-row { border-bottom: 1px solid var(--border); }
.league-row-link {
  display: flex; align-items: baseline; justify-content: space-between; gap: 1rem;
  padding: 0.9rem 0.25rem; text-decoration: none; color: var(--ink);
}
.league-row-link:visited { color: var(--ink); }
.league-row-link:hover { background: var(--surface); box-shadow: inset 4px 0 0 var(--ink); }
.league-row-name {
  font-family: var(--display-font); font-weight: 800; font-size: 1.6rem;
  letter-spacing: 0.02em; text-transform: uppercase;
}
.league-row-count { font-family: var(--body-font); font-size: 0.9375rem; color: var(--muted); white-space: nowrap; }
.league-row--live .league-row-count {
  /* chrome-on-lime, the same pairing (14.50:1) as everywhere else lime
     appears -- both colors are brand constants, unchanged between light
     and dark mode, so this needs no dark-mode override. */
  color: var(--chrome); font-weight: 700;
  background: var(--hi); padding: 0.2rem 0.6rem; border-radius: 0.3rem;
  font-variant-numeric: tabular-nums;
}

.not-included-panel {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 0.75rem; padding: 1.25rem 1.25rem 1.5rem; margin: 1.5rem 0;
}
.not-included-panel h2 { font-size: 1.05rem; border-top: 0; padding-top: 0; margin-top: 0; }
.not-included-panel p { font-size: 0.9375rem; color: var(--muted); }
.not-included-panel ul { padding-left: 1.1rem; font-size: 0.9375rem; }
.not-included-panel li { margin-bottom: 0.6rem; }

/* ---- team roster (league page) ---- */
.team-roster {
  list-style: none; margin: 0; padding: 0;
  columns: 1; column-gap: 1.5rem;
  border-top: 1px solid var(--border);
}
.team-roster li { border-bottom: 1px solid var(--border); break-inside: avoid; }
.team-roster a {
  display: block; padding: 0.65rem 0.25rem; text-decoration: none;
  font-family: var(--label-font); font-weight: 600; font-size: 1.05rem;
  color: var(--ink);
}
.team-roster a:visited { color: var(--ink); }
.team-roster a:hover { color: var(--link); text-decoration: underline; }
@media (min-width: 30rem) { .team-roster { columns: 2; } }

/* ---- team page: this week, and the other teams in the league; home page team lists ---- */
.this-week ul { list-style: none; margin: 0 0 0.75rem; padding: 0; }
.this-week li { padding: 0.4rem 0; border-bottom: 1px solid var(--border); }
.more-teams, .all-teams { margin-top: 2rem; }
.all-teams h3 { margin: 1.5rem 0 0.5rem; }

/* ---- subscribe box: the .ics mechanic, styled as the actual product ---- */
.subscribe {
  position: relative;
  background: var(--surface); border: 2px solid var(--card-edge);
  border-radius: 0.85rem; padding: 1.5rem 1.25rem 1.25rem; margin: 1.5rem 0;
}
/* Two binder tabs: the box is a calendar page as well as a ticket. */
.subscribe::before, .subscribe::after {
  content: ""; position: absolute; top: -9px; width: 22px; height: 16px;
  background: var(--hi); border: 2px solid var(--chrome); border-radius: 4px;
}
.subscribe::before { left: 1.75rem; }
.subscribe::after { right: 1.75rem; }
.subscribe h2 { font-size: 1.15rem; border-top: 0; padding-top: 0; margin-top: 0; }
/* The feed URL is one long unbroken token (".../ics/<league>/<team>.ics");
   without a break opportunity it pushed team pages to 350-430 CSS px wide at
   a 320 px viewport, failing WCAG 1.4.10 Reflow. */
.subscribe p a, .other-apps p a, .moved-notice a { overflow-wrap: anywhere; }
.subscribe-instructions { padding-left: 1.1rem; font-size: 0.9375rem; }
.subscribe-instructions li { margin-bottom: 0.5rem; }
.subscribe-cta {
  display: inline-flex; align-items: center; min-height: 2.75rem;
  background: var(--chrome); color: var(--on-chrome-fg);
  font-family: var(--label-font); font-weight: 700; letter-spacing: 0.01em;
  text-decoration: none; padding: 0.6rem 1.1rem; border-radius: 0.5rem;
  margin-bottom: 0.15rem;
}
.subscribe-cta:visited { color: var(--on-chrome-fg); }
/* chrome on lime, 14.50:1 */
.subscribe-cta:hover { background: var(--hi); color: var(--chrome); }
.subscribe-buttons {
  list-style: none; margin: 0.75rem 0 1rem; padding: 0;
  display: flex; flex-wrap: wrap; gap: 0.5rem;
}
.subscribe-buttons .subscribe-cta { margin-bottom: 0; border: 1px solid var(--cta-border); }
.subscribe-feed { font-size: 0.9375rem; }

/* ---- team page hero: the actual next home game ---- */
.next-game {
  position: relative;
  background: var(--chrome); color: var(--on-chrome-fg);
  border: 1px solid var(--card-edge);
  border-radius: 0.85rem; padding: 1.5rem 1.25rem;
  margin: 1.5rem 0; display: flex; flex-wrap: wrap; gap: 1.25rem;
}
/* The ticket's two notches, cut where the label's tear line runs (1.5rem
   padding + the label's 1.14rem line + 0.75rem, less the notch radius). */
.next-game::before, .next-game::after {
  content: ""; position: absolute; top: 2.79rem; width: 1.2rem; height: 1.2rem;
  border-radius: 50%; background: var(--bg);
}
.next-game::before { left: -0.6rem; }
.next-game::after { right: -0.6rem; }
.next-game-date {
  flex: 0 0 auto; width: 6rem; height: 6rem;
  background: var(--hi); color: var(--chrome); border-radius: 0.6rem;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  font-family: var(--display-font);
}
.next-game-date--tbd { background: var(--on-chrome-dim); }
.next-game-month { font-size: 1rem; font-weight: 700; letter-spacing: 0.04em; }
.next-game-day { font-size: 2.75rem; font-weight: 800; line-height: 1; }
.next-game-details { flex: 1 1 14rem; min-width: 0; }
.next-game-matchup {
  font-family: var(--display-font); font-weight: 800; font-size: clamp(1.4rem, 3vw + 1rem, 1.9rem);
  line-height: 1.05; margin: 0 0 0.3rem; max-width: none;
}
.next-game-when, .next-game-venue { margin: 0 0 0.2rem; color: var(--on-chrome-muted); font-size: 0.9375rem; max-width: none; }
.next-game-cta {
  display: inline-block; background: var(--hi); color: var(--chrome);
  font-family: var(--label-font); font-weight: 700; letter-spacing: 0.01em;
  text-decoration: none; padding: 0.65rem 1.15rem; border-radius: 0.5rem;
  margin-top: 0.75rem;
}
.next-game-cta:visited { color: var(--chrome); }
/* a lighter lime on hover, chrome text still: #16131d on #e6fa8c */
.next-game-cta:hover { background: #e6fa8c; }
.next-game-cta--unavailable {
  background: none; color: var(--on-chrome-dim); font-style: italic; padding: 0; font-size: 0.9375rem;
}
/* The label row ends in the ticket's tear line, a dashed perforation that
   meets the two notches. */
.next-game h2.next-game-label {
  flex: 1 0 100%; margin: 0; padding: 0 0 0.75rem; border-top: 0;
  border-bottom: 2px dashed var(--on-chrome-dim);
  font-family: var(--label-font); font-weight: 700; font-size: 0.95rem; line-height: 1.2;
  letter-spacing: 0.06em; text-transform: uppercase; color: var(--on-chrome-muted);
}
.next-game--empty .next-game-label { margin-bottom: 0.5rem; }
.next-game-note { flex: 1 0 100%; margin: 0; color: var(--on-chrome-muted); font-size: 0.9375rem; max-width: none; }
.next-game .game-status { color: var(--on-chrome-fg); }
.next-game--empty { display: block; }
.next-game-empty-msg { color: var(--on-chrome-muted); max-width: 36rem; margin: 0; }
.next-game--empty .next-game-empty-msg { margin-top: 0.75rem; }
/* A plain link inside the black hero (the "check the team's seller" link in
   the empty message) takes the on-chrome link colors. Before 0035 it kept
   the page's ink link color, the same color as the hero, so it could not
   be seen (about 1:1). White 18.34:1, visited pink 9.86:1. */
.next-game a:not(.next-game-cta) { color: var(--on-chrome-link); }
.next-game a:not(.next-game-cta):visited { color: var(--on-chrome-link-visited); }
.next-game a:focus-visible { outline-color: var(--on-chrome-focus); }

/* ---- games table ---- */
.no-games-message { color: var(--muted); }
/* position: relative makes the wrapper the containing block of the ticket
   links' visually hidden spans (.sr-only, position: absolute), so they stay
   inside its scroll box; without it they sit at their place in the 42rem
   table and widen the whole page at 320px (the a11y reflow check). */
.games-table-wrap {
  position: relative;
  overflow-x: auto; -webkit-overflow-scrolling: touch;
  margin: 1rem 0; border: 1px solid var(--border); border-radius: 0.6rem;
}
table.games-table { border-collapse: collapse; width: 100%; min-width: 42rem; font-size: 0.9375rem; }
table.games-table th, table.games-table td {
  padding: 0.6rem 0.85rem; text-align: left; vertical-align: top;
  border-bottom: 1px solid var(--border);
}
table.games-table thead th {
  background: var(--chrome); color: var(--on-chrome-fg);
  font-family: var(--label-font); font-weight: 700; letter-spacing: 0.01em;
  border-bottom: 0;
}
table.games-table tbody tr:nth-child(even) { background: var(--surface); }
table.games-table tbody tr:last-child td { border-bottom: 0; }
.game-date { font-family: var(--label-font); font-weight: 700; font-variant-numeric: tabular-nums; }
.ticket-unavailable { color: var(--muted); font-style: italic; }
.game-status { font-weight: 700; }
.home-away {
  display: inline-block; margin-left: 0.4rem; padding: 0 0.45rem;
  border: 1px solid var(--border); border-radius: 999px;
  font-family: var(--label-font); font-weight: 700; font-size: 0.8125rem;
  color: var(--muted); white-space: nowrap;
}
.home-away--home { color: var(--ink); border-color: var(--ink); }

/* ---- help page ---- */
/* A feed address is one long unbroken token: let it wrap at 320px. */
.help-addresses code { overflow-wrap: anywhere; }
.help-contents { padding-left: 1.1rem; }
.help-contents li, main > ol li { margin-bottom: 0.35rem; }
.help-source { color: var(--muted); font-size: 0.9375rem; }

.sr-caption, .sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
"""

# The "Paid link" label (PAID_LINK_LABEL). Appended to style.css only when
# some link can be an affiliate link (style_css), so with no affiliate link
# configured, style.css is byte-for-byte what it was before (DECISIONS 0018).
# --muted on --bg is 7.45:1 and on --surface (alternate table rows) 6.64:1 in
# light mode, and 8.89:1 and 8.13:1 in dark mode. The hero is chrome, so
# there the label takes the on-chrome muted color the hero's own date and
# venue lines use (#cfcadb on #16131d: 11.46:1).
PAID_LINK_CSS = """
.paid-link {
  display: inline-block; margin-left: 0.35rem; padding: 0 0.45rem;
  border: 1px solid currentColor; border-radius: 0.25rem;
  font-family: var(--label-font); font-weight: 700; font-size: 0.8125rem;
  color: var(--muted); white-space: nowrap;
}
.next-game .paid-link { color: var(--on-chrome-muted); margin-top: 0.75rem; }
"""


def style_css(*, paid_links: bool = False) -> str:
    """dist/style.css: STYLE_CSS, plus the paid-link label's rules when some
    link can be an affiliate link (_any_paid)."""
    return STYLE_CSS + PAID_LINK_CSS if _any_paid(paid_links) else STYLE_CSS
