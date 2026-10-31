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

Visual design: the real brand established in pipeline/assets/favicon.svg
and scripts/render_social_assets.py (navy #0b1f3a / gold #f4c94c calendar
card, gold = "this is the highlighted next-game cell") is extended here,
not replaced -- see the palette comment on STYLE_CSS below.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, date, datetime
from html import escape as e
from typing import Any
from urllib.parse import quote, urlencode

from . import config, feeds, official_tickets, structured_data
from .analytics import GA4_DATA_RETENTION, ga4_head_snippet, measurement_id
from .config import league_names_for, title_name_for
from .ics import COMBINED_FEED_PATH, TIME_TBA_NOTE, TIME_TBA_SUFFIX, calendar_name
from .normalize import display_date
from .sellers import AFFILIATE_LINK_TEMPLATES, affiliate_links_active, is_affiliate_link
from .site_data import kept_out_of_search, schedule_window
from .team_shops import shop_links_on, team_shop_url

CSS_PATH = "/style.css"
PRIVACY_PATH = "/privacy/"
ACCESSIBILITY_PATH = "/accessibility/"
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
# The "Updated" date printed on /privacy/ and /accessibility/, and their
# sitemap <lastmod>: one value each, so the two cannot disagree. Change it
# whenever that page's text changes.
PRIVACY_UPDATED = date(2026, 10, 31)
ACCESSIBILITY_UPDATED = date(2026, 9, 17)
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
{canonical_link}{feed_link}<meta name="theme-color" content="#0b1f3a">
<link rel="preload" href="/fonts/public-sans-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="/fonts/big-shoulders-display-latin.woff2" as="font" type="font/woff2" crossorigin>
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
<a class="brand" href="/"><img class="brand-mark" src="/favicon.svg" alt="" width="28" height="28">{e(SITE_NAME)}</a>
</header>
<main id="main">
{body}
</main>
{_footer(analytics_on=bool(analytics_head), paid_links=paid_links)}
</body>
</html>
"""


# The footer's privacy note, in the two states the build can be in. Each is
# literal about what happens; /privacy/ has the detail.
PRIVACY_NOTE_ANALYTICS = """This site's pages use Google Analytics to count
visits and clicks on ticket and calendar links, with Google's advertising
features switched off. It is not loaded at all if your browser sends Global
Privacy Control or Do Not Track, or once you opt out here, and the calendar
feeds are never tracked. A
&ldquo;Buy tickets&rdquo; link goes to the ticket seller's own site and tells
them we sent you."""
PRIVACY_NOTE_NO_ANALYTICS = """This site runs no analytics, no scripts, and
sets no cookies, and the calendar feeds are never tracked. A &ldquo;Buy
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
<p class="privacy-note"><a href="{ACCESSIBILITY_PATH}">Accessibility statement</a>.</p>{_removal_contact()}
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
</section>
"""


def _buy_link(game: Mapping[str, Any], matchup: str, *, css_class: str = "") -> str | None:
    """The one "Buy tickets" link for a game, from site_data's `buy`
    (sellers.buy_link), with link text naming where it goes. None when
    there is nowhere to buy; callers say so in words. No price is ever
    shown (DECISIONS 0013)."""
    buy = game.get("buy")
    if not buy:
        return None
    text = f"Buy tickets for {matchup} on {game['start_display']} from {buy['seller']}"
    if buy.get("home_team"):
        text += f", the official seller for {buy['home_team']} home games"
    # An affiliate link is marked as one for search engines (Google asks that
    # paid and affiliate links say so) and for the reader, with the visible
    # "Paid link" label right after it (the footer note is not enough on its
    # own). Derived here from the seller and the URL (a Ticketmaster URL
    # can arrive already wrapped in Impact tracking), never stored in
    # data/*.json. The link text still names the seller, not the tracking
    # host it goes through. A plain link gets no rel attribute and no label
    # at all.
    if is_affiliate_link(buy["seller"], buy["url"]):
        return _paid_link(buy["url"], e(text), css_class=css_class)
    class_attr = f' class="{css_class}"' if css_class else ""
    return f'<a{class_attr} href="{e(buy["url"])}">{e(text)}</a>'


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
        note = f'<p class="next-game-note">No {e(team_name)} home game is listed by Ticketmaster right now.</p>\n'
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
        buy = _buy_link(g, matchup) or '<span class="ticket-unavailable">no ticket link published yet</span>'
        tag = _home_away_tag(g) if home_away else ""
        rows.append(
            "<tr>"
            f'<td><span class="game-date">{_when_html(g)}</span>{date_note}</td>'
            f"<td>{e(matchup)}{tag}{_game_labels_html(g)}</td>"
            f"<td>{e(_venue_text(g))}</td>"
            f"<td>{buy}</td>"
            "</tr>"
        )
    return f"""<div class="games-table-wrap">
<table class="games-table">
<caption class="sr-caption">Upcoming {e(buy_link_subject)} games, from Ticketmaster</caption>
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


def _team_title(name: str, season: str | None, *, listed: bool, home_listed: bool) -> str:
    """ "New York Sirens schedule 2026-27: next home game and tickets": the
    words a fan types, in the order Search Console shows them typed
    ("minnesota frost schedule 2026-27", "boston fleet 2026-27 schedule",
    "next valkyries home game"; 2026-10-21 to 10-29). Each claim is made only
    when the page backs it: "tickets" and the season when games are listed
    (every game links to its ticket seller; the site shows no prices), "next
    home game" and "home games" when a home game is listed (the page opens
    with it). A page with nothing listed is just "<team> schedule"."""
    if not listed:
        return _fit([f"{name} schedule"], TITLE_MAX)
    schedule = f"{name} schedule {season}" if season else f"{name} schedule"
    lead = (
        [f"{schedule}: next home game and tickets", f"{schedule}: home games and tickets"]
        if home_listed
        else [f"{schedule}: dates and tickets"]
    )
    return _fit([*lead, f"{schedule} and tickets", schedule, f"{name} schedule"], TITLE_MAX)


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
    """ "WNBA, NWSL, PWHL, AUSL or NCAA Women's Basketball (Big Ten)"."""
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
    body = f"""<h1>Women's sports schedules for your calendar</h1>
<p class="lede">Pick a league or a team and add its schedule to Google
Calendar, Apple Calendar or Outlook. Every listed game shows up on its own,
updated nightly, with a link to buy tickets from the team's seller. No
account, no ads.</p>
<p><a href="{SCHEDULE_PATH}">The week ahead in every league, day by day</a></p>
{_all_games_feed_block(base_url)}<h2>Leagues</h2>
<ul class="league-strip">
{league_links}
</ul>
{_teams_by_league_block(leagues)}<section class="not-included-panel" aria-labelledby="not-included-heading">
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
                f"Add your {league_names} team's schedule to Google, Apple or Outlook calendar. "
                "Updated nightly. No account.",
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
) -> str:
    """The page at a slug a team used to have (config.Team.former_slugs): a
    notice that points to the current page, and sends the browser there. A
    static host cannot redirect, so this is what a saved link to the old
    page lands on. noindex, and kept out of the sitemap, so the old path is
    never a second listing of the same team; the calendar feed at the old
    path still works and is not touched."""
    new_path = f"/{league_slug}/{team_slug}/"
    body = f"""<h1>{e(team_name)} has a new page address</h1>
<p class="lede">The {e(team_name)} ({e(league_name)}) schedule is now at
<a href="{e(new_path)}">{e(base_url)}{e(new_path)}</a>.</p>
<p>A calendar you already subscribed to keeps working at its old address.</p>
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
click, with nothing stored on your device to recognise you next time.</li>
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
    else:
        pages_section = """<h2>Web pages: no analytics</h2>
<p>This site runs no analytics: no measurement service of any kind, no
scripts at all, and no cookies.</p>
"""
        ticket_measured = ""
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
{pages_section}<h2>Calendar feeds: never tracked</h2>
<p>The <code>.ics</code> calendar feeds carry game listings and nothing else:
no tracking pixel, no analytics, no redirecting links. A calendar app that
subscribes to a feed and re-fetches it is not measured by this site. Ticket
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
<li>axe-core against WCAG 2.0, 2.1 and 2.2 A and AA rules, including colour
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
        buy = _buy_link(g, matchup) or '<span class="ticket-unavailable">no ticket link published yet</span>'
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
<div class="games-table-wrap">
<table class="games-table">
<caption class="sr-caption">Games on {e(label)}, from Ticketmaster</caption>
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
            f"{heading}: add every game to your calendar, updated nightly.",
        ],
        DESCRIPTION_MAX,
    )


def _opponent_label(league_slug: str, opponent: str) -> str:
    """The away team as a meta description names it: a Big Ten opponent by its
    school ("Rutgers"), or a school outside the registry by its Ticketmaster name
    without the "Womens Basketball" suffix, not the full keyword ("Rutgers
    Scarlet Knights Womens Basketball")."""
    name = title_name_for(league_slug, opponent)
    for suffix in (" women's basketball", " Womens Basketball"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _team_description(team: Mapping[str, Any]) -> str:
    """The meta description, at most DESCRIPTION_MAX characters: the next home
    game with its real date when one is listed, and the words a fan types
    (schedule, ticket links). With no home game listed it says nothing about
    one."""
    name = title_name_for(team["league_slug"], team["team_name"])
    league = league_names_for(team["league_slug"], team.get("league_name", ""))[1]
    season = team.get("season")
    # "<team> (<league>) schedule <season>": the league is in the queries
    # ("pwhl sirens schedule", "pwhl schedule ottawa").
    lead = f"{name} ({league}) schedule {season}" if league and season else ""
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
                f"Next {name} home game: {when}. Add every game to your calendar, with ticket links, updated nightly.",
                f"Next home game: {when}. Add every {name} game to your calendar, with ticket links, updated nightly.",
                f"Next home game: {when}. Add the {name} schedule to your calendar. Updated nightly.",
                f"Next {name} home game: {when}.",
                f"Next {name} home game: {home['start_display']}.",
            ],
            DESCRIPTION_MAX,
        )
    if not team["games"]:
        if team.get("fetched", True):
            return _fit(
                [
                    f"{name} schedule. No games are listed right now; add it to your calendar and "
                    "games appear as they are listed, updated nightly.",
                    f"{name} schedule. No games are listed right now.",
                ],
                DESCRIPTION_MAX,
            )
        return _fit(
            [f"{name} schedule. Add it to your calendar, updated nightly.", f"{name} schedule."], DESCRIPTION_MAX
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


def _team_lede(team: Mapping[str, Any]) -> str:
    """The team page's opening paragraph, in the words a fan searches with
    ("schedule", "home games", "tickets"), each one said only when the page
    backs it: the season when the listed games give one, "tickets" when a
    game links to a seller, "home games" when a game is known to be at home.
    It links the league's page (the hub), so the league is one click away
    from the body text and not only from the breadcrumb."""
    name = e(team["team_name"])
    league_link = f'<a href="/{e(team["league_slug"])}/">{e(team["league_name"])}</a>'
    if not team.get("fetched", True):
        return (
            f'<p class="lede">Every {name} ({league_link}) game Ticketmaster\n'
            "lists, home and away, with its date, time and venue.</p>"
        )
    games = team["games"]
    if not games:
        return (
            f'<p class="lede">Ticketmaster lists no {name} ({league_link}) game\n'
            "right now. Add the schedule to your calendar below, and each game appears\n"
            "in it once it is listed.</p>"
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
        f'<p class="lede">Every {name} ({league_link}) game Ticketmaster\n'
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
    owner = "the school's" if league_slug == "ncaaw-big-ten" else "the team's"
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
{lead_blocks}
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
    shown = f"{when:%A} {when.day} {when:%B %Y}, {when:%H:%M} UTC"
    return (
        f'<p class="schedule-source-note data-freshness">Listings as of <time datetime="{e(when.isoformat(timespec="seconds"))}">'
        f"{e(shown)}</time>, from Ticketmaster. They are refreshed every night.</p>\n"
    )


# ---------------------------------------------------------------------------
# STYLE_CSS
#
# Palette -- extends the exact hex values already established in
# pipeline/assets/favicon.svg and scripts/render_social_assets.py, not a
# new one:
#   navy   #0b1f3a  brand primary -- header/footer/hero chrome, headings
#                    and links on paper (16.52:1 on white)
#   gold   #f4c94c  reserved for ONE meaning only: "this is a real next
#                    game" -- the hero date-chip and its buy-tickets CTA,
#                    and a non-zero league game count. Never decoration.
#                    (10.47:1 as navy-on-gold text, the same ratio
#                    render_social_assets.py already checked for the
#                    highlighted calendar cell.)
#   white  #ffffff  paper / on-navy text (16.52:1 / 18.58:1)
#   light  #c9d6ea  on-navy secondary text -- the exact "subtitle text on
#                    navy" value from render_social_assets.py (11.24:1)
#   dim    #8fa8cf  on-navy small text -- the exact "footer/domain text on
#                    navy" value from render_social_assets.py (6.82:1),
#                    now used for this site's real footer/domain text
#   border #c7ccd1  the exact "decorative calendar grid lines" value,
#                    reused as section/table dividers
# New tokens added here (all contrast-checked against their real
# backgrounds -- see the PR description for the full ratio table):
#   paper-tint #eef3fb  subscribe box / table zebra / notice panel bg
#   ink-muted  #51607a  secondary text on paper (6.36:1 on white)
#   visited    #7a4a00  visited-link on paper (7.48:1) -- a dark amber,
#                        same hue family as gold, never gold itself (gold
#                        text on white is 1.58:1, which is why gold never
#                        appears directly on a paper background)
#   dark-mode swaps the paper for a near-navy canvas (#0a1420) -- in dark
#   mode this site's "light" and "dark" colors are the same two colors the
#   brand's own OG image already is: a navy world with gold, white and
#   light-blue on it.
# ---------------------------------------------------------------------------

STYLE_CSS = """\
@font-face {
  font-family: "Big Shoulders Display";
  font-style: normal;
  font-weight: 500 800;
  font-display: swap;
  src: url("/fonts/big-shoulders-display-latin.woff2") format("woff2");
}
@font-face {
  font-family: "Big Shoulders Text";
  font-style: normal;
  font-weight: 500 800;
  font-display: swap;
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
  --navy: #0b1f3a;
  --gold: #f4c94c;

  /* content-area tokens (paper in light mode, a navy canvas in dark) */
  --bg: #ffffff;
  --surface: #eef3fb;
  --ink: #0b1f3a;
  --muted: #51607a;
  --border: #c7ccd1;
  --link: #0b1f3a;
  --link-visited: #7a4a00;
  --focus: #0b1f3a;
  /* subscribe-button outline: the button's own navy on paper; in dark mode
     the on-navy dim blue, so four navy buttons on the navy-tinted box stay
     distinct (#8fa8cf on #101c30: 7.04:1) */
  --cta-border: #0b1f3a;

  /* chrome tokens -- header, footer, hero, subscribe box: always navy */
  --on-navy-fg: #ffffff;
  --on-navy-muted: #c9d6ea;
  --on-navy-dim: #8fa8cf;
  --on-navy-link: #8fc0ff;
  --on-navy-link-visited: #e8c37a;
  --on-navy-focus: #f4c94c;

  --display-font: "Big Shoulders Display", "Arial Narrow", sans-serif;
  --label-font: "Big Shoulders Text", "Arial Narrow", sans-serif;
  --body-font: "Public Sans", -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --measure: 34rem;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0a1420;
    --surface: #101c30;
    --ink: #eef2f8;
    --muted: #aab6c9;
    --border: #24344f;
    --link: #8fc0ff;
    --link-visited: #e8c37a;
    --focus: #f4c94c;
    --cta-border: #8fa8cf;
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
h1 { font-size: clamp(2rem, 5vw + 1rem, 3rem); margin-top: 1.5rem; }
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
a:focus-visible, button:focus-visible {
  outline: 3px solid var(--focus);
  outline-offset: 2px;
  border-radius: 2px;
}
@media (prefers-reduced-motion: no-preference) {
  a, .league-row-link, .next-game-cta, .subscribe-cta { transition: background-color 120ms ease, color 120ms ease, border-color 120ms ease; }
}

.skip-link {
  position: absolute; left: -999px; top: 0;
  background: var(--gold); color: var(--navy); font-weight: 700;
  padding: 0.6rem 1rem; z-index: 10; text-decoration: none;
}
.skip-link:focus { left: 0.75rem; top: 0.75rem; border-radius: 0.25rem; }

/* ---- chrome: header + footer, always navy, the brand's own colors ---- */
.site-header {
  background: var(--navy);
  padding: 0.9rem 1.25rem;
}
.brand {
  display: flex; align-items: center; gap: 0.5rem;
  max-width: 64rem; margin: 0 auto; box-sizing: border-box;
  color: var(--on-navy-fg); text-decoration: none;
  font-family: var(--label-font); font-weight: 700; font-size: 1.15rem;
  letter-spacing: 0.01em;
}
.brand:visited { color: var(--on-navy-fg); }
.brand-mark { display: block; border-radius: 6px; }
.site-header a:focus-visible { outline-color: var(--on-navy-focus); }

.site-footer { background: var(--navy); color: var(--on-navy-muted); margin-top: 3rem; }
.site-footer > * { padding: 1.5rem 1.25rem 2rem; }
.site-footer h2 {
  color: var(--on-navy-fg); border-top: 0; margin-top: 0; padding-top: 0;
  font-size: 1.05rem;
}
.site-footer p { max-width: 42rem; font-size: 0.9375rem; }
.site-footer a { color: var(--on-navy-link); }
.site-footer a:visited { color: var(--on-navy-link-visited); }
.site-footer a:focus-visible { outline-color: var(--on-navy-focus); }
.site-footer .privacy-note { color: var(--on-navy-dim); }
.analytics-toggle {
  background: none; border: 0; padding: 0.125rem 0; min-height: 1.5rem;
  color: var(--on-navy-link); font: inherit; text-decoration: underline;
  text-underline-offset: 0.15em; cursor: pointer;
}
.site-footer button:focus-visible { outline-color: var(--on-navy-focus); }

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
.league-row-link:hover { background: var(--surface); }
.league-row-name { font-family: var(--display-font); font-weight: 700; font-size: 1.375rem; }
.league-row-count { font-family: var(--body-font); font-size: 0.9375rem; color: var(--muted); white-space: nowrap; }
.league-row--live .league-row-count {
  /* navy-on-gold, same pairing (and the same 10.47:1 ratio) as everywhere
     else gold appears -- both colors are brand constants, unchanged
     between light and dark mode, so this needs no dark-mode override. */
  color: var(--navy); font-weight: 600;
  background: var(--gold); padding: 0.2rem 0.55rem; border-radius: 999px;
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
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 0.85rem; padding: 1.5rem 1.25rem 1.25rem; margin: 1.5rem 0;
}
.subscribe::before, .subscribe::after {
  content: ""; position: absolute; top: -8px; width: 22px; height: 16px;
  background: var(--navy); border-radius: 4px;
}
.subscribe::before { left: 1.75rem; }
.subscribe::after { right: 1.75rem; }
.subscribe h2 { font-size: 1.15rem; border-top: 0; padding-top: 0; margin-top: 0; }
/* The feed URL is one long unbroken token (".../ics/<league>/<team>.ics");
   without a break opportunity it pushed team pages to 350-430 CSS px wide at
   a 320 px viewport, failing WCAG 1.4.10 Reflow. */
.subscribe p a, .other-apps p a { overflow-wrap: anywhere; }
.subscribe-instructions { padding-left: 1.1rem; font-size: 0.9375rem; }
.subscribe-instructions li { margin-bottom: 0.5rem; }
.subscribe-cta {
  display: inline-block; background: var(--navy); color: var(--on-navy-fg);
  font-family: var(--label-font); font-weight: 700; letter-spacing: 0.01em;
  text-decoration: none; padding: 0.6rem 1.1rem; border-radius: 0.5rem;
  margin-bottom: 0.15rem;
}
.subscribe-cta:visited { color: var(--on-navy-fg); }
.subscribe-cta:hover { background: #132a4d; }
.subscribe-buttons {
  list-style: none; margin: 0.75rem 0 1rem; padding: 0;
  display: flex; flex-wrap: wrap; gap: 0.5rem;
}
.subscribe-buttons .subscribe-cta { margin-bottom: 0; border: 1px solid var(--cta-border); }
.subscribe-feed { font-size: 0.9375rem; }

/* ---- team page hero: the actual next home game ---- */
.next-game {
  background: var(--navy); color: var(--on-navy-fg);
  border-radius: 0.85rem; padding: 1.5rem 1.25rem;
  margin: 1.5rem 0; display: flex; flex-wrap: wrap; gap: 1.25rem;
}
.next-game-date {
  flex: 0 0 auto; width: 6rem; height: 6rem;
  background: var(--gold); color: var(--navy); border-radius: 0.6rem;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  font-family: var(--display-font);
}
.next-game-date--tbd { background: var(--on-navy-dim); }
.next-game-month { font-size: 1rem; font-weight: 700; letter-spacing: 0.04em; }
.next-game-day { font-size: 2.75rem; font-weight: 800; line-height: 1; }
.next-game-details { flex: 1 1 14rem; min-width: 0; }
.next-game-matchup {
  font-family: var(--display-font); font-weight: 800; font-size: clamp(1.4rem, 3vw + 1rem, 1.9rem);
  line-height: 1.05; margin: 0 0 0.3rem; max-width: none;
}
.next-game-when, .next-game-venue { margin: 0 0 0.2rem; color: var(--on-navy-muted); font-size: 0.9375rem; max-width: none; }
.next-game-cta {
  display: inline-block; background: var(--gold); color: var(--navy);
  font-family: var(--label-font); font-weight: 700; letter-spacing: 0.01em;
  text-decoration: none; padding: 0.65rem 1.15rem; border-radius: 0.5rem;
  margin-top: 0.75rem;
}
.next-game-cta:visited { color: var(--navy); }
.next-game-cta:hover { background: #ffd876; }
.next-game-cta--unavailable {
  background: none; color: var(--on-navy-dim); font-style: italic; padding: 0; font-size: 0.9375rem;
}
.next-game h2.next-game-label {
  flex: 1 0 100%; margin: 0; padding: 0; border-top: 0;
  font-family: var(--label-font); font-weight: 700; font-size: 0.95rem;
  letter-spacing: 0.06em; text-transform: uppercase; color: var(--on-navy-muted);
}
.next-game--empty .next-game-label { margin-bottom: 0.5rem; }
.next-game-note { flex: 1 0 100%; margin: 0; color: var(--on-navy-muted); font-size: 0.9375rem; max-width: none; }
.next-game .game-status { color: var(--on-navy-fg); }
.next-game--empty { display: block; }
.next-game-empty-msg { color: var(--on-navy-muted); max-width: 36rem; margin: 0; }
.next-game a:focus-visible { outline-color: var(--on-navy-focus); }

/* ---- games table ---- */
.no-games-message { color: var(--muted); }
.games-table-wrap {
  overflow-x: auto; -webkit-overflow-scrolling: touch;
  margin: 1rem 0; border: 1px solid var(--border); border-radius: 0.6rem;
}
table.games-table { border-collapse: collapse; width: 100%; min-width: 42rem; font-size: 0.9375rem; }
table.games-table th, table.games-table td {
  padding: 0.6rem 0.85rem; text-align: left; vertical-align: top;
  border-bottom: 1px solid var(--border);
}
table.games-table thead th {
  background: var(--navy); color: var(--on-navy-fg);
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

.sr-caption { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
"""

# The "Paid link" label (PAID_LINK_LABEL). Appended to style.css only when
# some link can be an affiliate link (style_css), so with no affiliate link
# configured, style.css is byte-for-byte what it was before (DECISIONS 0018).
# --muted on --bg is 6.36:1 and on --surface (alternate table rows) 5.7:1 in
# light mode, and 9.03:1 and 8.32:1 in dark mode. The hero is navy chrome,
# so there the label takes the on-navy muted color the hero's own date and
# venue lines use (#c9d6ea on #0b1f3a: 11.24:1).
PAID_LINK_CSS = """
.paid-link {
  display: inline-block; margin-left: 0.35rem; padding: 0 0.45rem;
  border: 1px solid currentColor; border-radius: 0.25rem;
  font-family: var(--label-font); font-weight: 700; font-size: 0.8125rem;
  color: var(--muted); white-space: nowrap;
}
.next-game .paid-link { color: var(--on-navy-muted); margin-top: 0.75rem; }
"""


def style_css(*, paid_links: bool = False) -> str:
    """dist/style.css: STYLE_CSS, plus the paid-link label's rules when some
    link can be an affiliate link (_any_paid)."""
    return STYLE_CSS + PAID_LINK_CSS if _any_paid(paid_links) else STYLE_CSS
