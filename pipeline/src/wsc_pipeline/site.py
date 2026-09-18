"""Static HTML generator. The only script on any page is the guarded Google
Analytics 4 loader from analytics.py (DECISIONS 0012, superseding 0002), and
only when analytics.GA4_MEASUREMENT_ID is set: with no ID, every page emitted
here contains zero <script> elements; with one, exactly one inline <script>
that honours Global Privacy Control and Do Not Track -- both checked by
tests/test_site_html.py and tests/test_analytics.py. Nothing else here is
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

from datetime import date
from html import escape as e

from .analytics import GA4_DATA_RETENTION, ga4_head_snippet, measurement_id
from .sellers import affiliate_links_active

CSS_PATH = "/style.css"
PRIVACY_PATH = "/privacy/"
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
) -> str:
    image_url = f"{base_url}/{og_image}"
    analytics_head = ga4_head_snippet(ga4_id, base_url=base_url)
    robots_meta = '<meta name="robots" content="noindex">\n' if noindex else ""
    # A noindexed page (the 404) carries no canonical: pointing it at another
    # URL would declare it a duplicate of a page it is not.
    canonical_link = "" if noindex else f'<link rel="canonical" href="{e(canonical_url)}">\n'
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name='impact-site-verification' content='672c11dd-230b-463d-b029-e09ce84f1050'>
<title>{e(title)}</title>
{robots_meta}<meta name="description" content="{e(description)}">
{canonical_link}<meta name="theme-color" content="#0b1f3a">
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
{analytics_head}</head>
<body>
<a class="skip-link" href="#main">Skip to main content</a>
<header class="site-header">
<a class="brand" href="/"><img class="brand-mark" src="/favicon.svg" alt="" width="28" height="28">{e(SITE_NAME)}</a>
</header>
<main id="main">
{body}
</main>
{_footer(analytics_on=bool(analytics_head))}
</body>
</html>
"""


# The footer's privacy note, in the two states the build can be in. Each is
# literal about what happens; /privacy/ has the detail.
PRIVACY_NOTE_ANALYTICS = """This site's pages use Google Analytics to count
visits and clicks on ticket and calendar links, with Google's advertising
features switched off. It is not loaded at all if your browser sends Global
Privacy Control or Do Not Track, and the calendar feeds are never tracked. A
&ldquo;Buy tickets&rdquo; link goes to the ticket seller's own site and tells
them we sent you."""
PRIVACY_NOTE_NO_ANALYTICS = """This site runs no analytics, no scripts, and
sets no cookies, and the calendar feeds are never tracked. A &ldquo;Buy
tickets&rdquo; link goes to the ticket seller's own site and tells them we
sent you."""

# Rendered from sellers.AFFILIATE_LINK_TEMPLATES, so the disclosure is true
# by construction: it says "affiliate" exactly when a link is one.
AFFILIATE_NOTE_ACTIVE = (
    "Some of these are affiliate links: if you buy through one, the seller may pay this site a commission."
)
AFFILIATE_NOTE_INACTIVE = "They are plain links, and this site is not paid for them."


def _footer(*, analytics_on: bool) -> str:
    note = PRIVACY_NOTE_ANALYTICS if analytics_on else PRIVACY_NOTE_NO_ANALYTICS
    affiliate_note = AFFILIATE_NOTE_ACTIVE if affiliate_links_active() else AFFILIATE_NOTE_INACTIVE
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
<a href="{PRIVACY_PATH}">Privacy: what this site measures and what it never does</a>.</p>
</footer>
"""


def _subscribe_block(*, ics_https_url: str, ics_webcal_url: str, label: str) -> str:
    return f"""<section class="subscribe" aria-labelledby="subscribe-heading">
<h2 id="subscribe-heading">Subscribe to {e(label)}</h2>
<p><a class="subscribe-cta" href="{e(ics_webcal_url)}">Subscribe in your calendar app</a>
(most calendar apps open <code>webcal://</code> links automatically) &mdash;
or use the direct feed URL:
<a href="{e(ics_https_url)}">{e(ics_https_url)}</a></p>
<ul class="subscribe-instructions">
<li><strong>iPhone/iPad:</strong> Settings &rsaquo; Calendar &rsaquo; Accounts &rsaquo; Add Account &rsaquo; Other &rsaquo; Add Subscribed Calendar, then paste the feed URL above.</li>
<li><strong>Google Calendar:</strong> on the left, next to &ldquo;Other calendars,&rdquo; select the + icon &rsaquo; From URL, then paste the feed URL above.</li>
<li><strong>Outlook:</strong> Add calendar &rsaquo; Subscribe from web, then paste the feed URL above.</li>
</ul>
</section>
"""


def _buy_link(game: dict, matchup: str, *, css_class: str = "") -> str | None:
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
    class_attr = f' class="{css_class}"' if css_class else ""
    return f'<a{class_attr} href="{e(buy["url"])}">{e(text)}</a>'


def _matchup_text(game: dict) -> str:
    """"Home vs Away" when both were parsed; otherwise Ticketmaster's own
    event name. Never "TBD vs TBD": the live site showed that for events
    whose names carry no "vs" (e.g. "Washington Spirit Premium
    Experiences", tournament listings), stating two unknown teams when the
    real listing name was right there."""
    if game["home_team"] and game["away_team"]:
        return f"{game['home_team']} vs {game['away_team']}"
    return game.get("event_name") or "Event name not published by Ticketmaster"


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


def _next_game_hero(games: list[dict], *, team_name: str, fetched: bool = True) -> str:
    """The dominant visual moment on a team page: the actual next home
    game (games[0] -- site_data.py already sorts soonest-first), or, when
    Ticketmaster has nothing listed right now, a plain, honest empty
    state. Never a fabricated date standing in for a real one, and never
    "none listed" when this build did not look (fetched=False)."""
    if not fetched:
        return f"""<section class="next-game next-game--empty" aria-labelledby="next-game-heading">
<h2 id="next-game-heading" class="sr-caption">Next home game</h2>
<p class="next-game-empty-msg">{e(NOT_FETCHED_MSG)}</p>
</section>
"""
    if not games:
        return f"""<section class="next-game next-game--empty" aria-labelledby="next-game-heading">
<h2 id="next-game-heading" class="sr-caption">Next home game</h2>
<p class="next-game-empty-msg">No {e(team_name)} games are listed by
Ticketmaster right now. Subscribe above and the next one will show up in
your calendar automatically &mdash; nothing to check back for.</p>
</section>
"""
    g = games[0]
    month_day = _month_day(g["start_local_date"])
    matchup = _matchup_text(g)
    venue = ", ".join(p for p in (g["venue_name"], g["venue_city"], g["venue_state"]) if p) or "Venue not available"
    when = e(g["start_display"]) + (
        "" if g["in_calendar_feed"] else " (date TBD &mdash; not yet in the calendar feed)"
    )
    if month_day:
        month, day = month_day
        date_chip = f'<div class="next-game-date" aria-hidden="true"><span class="next-game-month">{e(month)}</span><span class="next-game-day">{e(day)}</span></div>'
    else:
        date_chip = '<div class="next-game-date next-game-date--tbd" aria-hidden="true"><span class="next-game-month">Date</span><span class="next-game-day">TBD</span></div>'
    cta = _buy_link(g, matchup, css_class="next-game-cta") or (
        '<p class="next-game-cta next-game-cta--unavailable">No ticket link published for this game yet</p>'
    )
    return f"""<section class="next-game" aria-labelledby="next-game-heading">
<h2 id="next-game-heading" class="sr-caption">Next home game</h2>
{date_chip}
<div class="next-game-details">
<p class="next-game-matchup">{e(matchup)}</p>
<p class="next-game-when">{when}</p>
<p class="next-game-venue">{e(venue)}</p>
{cta}
</div>
</section>
"""


def _games_table(games: list[dict], *, buy_link_subject: str, fetched: bool = True) -> str:
    if not fetched:
        return f'<p class="no-games-message">{e(NOT_FETCHED_MSG)}</p>'
    if not games:
        return '<p class="no-games-message">No upcoming games found from Ticketmaster right now.</p>'
    rows = []
    for g in games:
        matchup = _matchup_text(g)
        venue = ", ".join(p for p in (g["venue_name"], g["venue_city"], g["venue_state"]) if p) or "Venue not available"
        date_note = "" if g["in_calendar_feed"] else " (date TBD &mdash; not yet in the calendar feed)"
        buy = _buy_link(g, matchup) or '<span class="ticket-unavailable">no ticket link published yet</span>'
        rows.append(
            "<tr>"
            f'<td><span class="game-date">{e(g["start_display"])}</span>{date_note}</td>'
            f"<td>{e(matchup)}</td>"
            f"<td>{e(venue)}</td>"
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


def render_index(
    *,
    leagues: list[dict],
    not_included: list[dict[str, str]],
    base_url: str,
    ga4_id: str | None = None,
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
    body = f"""<h1>Women's pro sports calendars you subscribe to once</h1>
<p class="lede">Pick a league or a team and add its calendar to your
phone or computer. Every upcoming game shows up on its own, updated
nightly, with a link to buy tickets from the team's seller. No account,
no ads.</p>
<h2>Leagues</h2>
<ul class="league-strip">
{league_links}
</ul>
<section class="not-included-panel" aria-labelledby="not-included-heading">
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
        title=f"{SITE_NAME}: women's pro sports calendars and tickets",
        description="Subscribe once to a calendar for your women's pro sports league or team: every upcoming game, updated nightly, with a link to buy tickets.",
        canonical_url=f"{base_url}/",
        base_url=base_url,
        body=body,
        ga4_id=ga4_id,
    )


def render_not_found(*, leagues: list[dict], base_url: str, ga4_id: str | None = None) -> str:
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
    )


def render_privacy(*, base_url: str, ga4_id: str | None = None) -> str:
    """dist/privacy/index.html, linked from every page's footer. Rendered
    from the same GA4 ID as the pages' <head>, so it describes exactly what
    this build does: Google Analytics with its safeguards when an ID is
    set, "no analytics" when none is."""
    affiliate_note = AFFILIATE_NOTE_ACTIVE if affiliate_links_active() else AFFILIATE_NOTE_INACTIVE
    if measurement_id(ga4_id) is not None:
        pages_section = f"""<h2>Web pages: Google Analytics</h2>
<p>This site's pages use Google Analytics 4, a Google service, to count page
views and clicks on &ldquo;Buy tickets&rdquo; and calendar-subscribe links, so
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
</ul>
<p>Google handles this data under its own terms: see
<a href="https://policies.google.com/technologies/partner-sites">how Google uses information from sites that use its services</a>.
To opt out in any browser, turn on Global Privacy Control or Do Not Track, or
install <a href="https://tools.google.com/dlpage/gaoptout">Google's Analytics opt-out browser add-on</a>.</p>
"""
        ticket_measured = " Google Analytics records only that the link was clicked, on this site's page."
    else:
        pages_section = """<h2>Web pages: no analytics</h2>
<p>This site runs no analytics: no measurement service of any kind, no
scripts at all, and no cookies.</p>
"""
        ticket_measured = ""
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
<p>Every &ldquo;Buy tickets&rdquo; link is a plain address: the home team's
own ticket seller's page for that team where we know it (for example AXS or
SeatGeek), otherwise the address Ticketmaster publishes for that event. It is
used as-is: never rewritten, and never routed through this site or through
Google.{ticket_measured} Following one takes you to that seller, which then
knows this site sent you. {affiliate_note} What happens there is covered by
the seller's own privacy policy.</p>
<h2>No accounts, no ads, no forms</h2>
<p>There is nothing to sign up for, no advertising, and no form that collects
anything.</p>
<h2>Hosting</h2>
<p>Pages and calendar feeds are served by GitHub Pages. Like any web host,
GitHub receives each request's IP address and browser details; this site has
no access to those logs.</p>
<p>Updated 2026-09-17.</p>
"""
    return _base(
        title=f"Privacy | {SITE_NAME}",
        description="What Next Home Game measures, what it never measures, and how to opt out.",
        canonical_url=f"{base_url}{PRIVACY_PATH}",
        base_url=base_url,
        body=body,
        ga4_id=ga4_id,
    )


def render_league(
    *,
    league: dict,
    base_url: str,
    ga4_id: str | None = None,
) -> str:
    slug = league["league_slug"]
    name = league["league_name"]
    ics_https = f"{base_url}/ics/{slug}.ics"
    ics_webcal = ics_https.replace("https://", "webcal://").replace("http://", "webcal://")
    # The team's real name ("Gotham FC", "UCLA Bruins Womens Basketball"),
    # not a title-cased slug ("Gotham Fc", "Ucla Bruins ...") -- this list is
    # the league page's only internal link to each team page.
    team_names = league.get("team_names") or {}

    def team_name(slug_: str) -> str:
        return team_names.get(slug_) or slug_.replace("-", " ").title()

    team_links = "\n".join(
        f'<li><a href="/{e(slug)}/{e(t)}/">{e(team_name(t))}</a></li>' for t in league["teams"]
    )
    incomplete = league.get("possibly_incomplete_teams") or []
    incomplete_note = (
        _possibly_incomplete_note(", ".join(team_name(t) for t in incomplete)) + "\n" if incomplete else ""
    )
    body = f"""<nav aria-label="breadcrumb"><a href="/">All leagues</a></nav>
<h1>{e(name)}</h1>
<p class="schedule-source-note">{e(league["schedule_source_note"])}</p>
{incomplete_note}{_subscribe_block(ics_https_url=ics_https, ics_webcal_url=ics_webcal, label=f"all of {name}")}
<h2>Upcoming games</h2>
{_games_table(league["games"], buy_link_subject=name, fetched=league.get("fetched", True))}
<h2>Teams</h2>
<ul class="team-roster">
{team_links}
</ul>
"""
    og_image, og_image_alt = LEAGUE_OG_IMAGES.get(slug, (DEFAULT_OG_IMAGE, DEFAULT_OG_IMAGE_ALT))
    return _base(
        title=f"{name} calendar and tickets | {SITE_NAME}",
        description=f"Subscribe once to a {name} calendar: every upcoming game, updated nightly, with a link to buy tickets.",
        canonical_url=f"{base_url}/{slug}/",
        base_url=base_url,
        body=body,
        og_image=og_image,
        og_image_alt=og_image_alt,
        ga4_id=ga4_id,
    )


def render_team(
    *,
    team: dict,
    base_url: str,
    ga4_id: str | None = None,
) -> str:
    league_slug = team["league_slug"]
    team_slug = team["team_slug"]
    ics_https = f"{base_url}/ics/{league_slug}/{team_slug}.ics"
    ics_webcal = ics_https.replace("https://", "webcal://").replace("http://", "webcal://")
    fetched = team.get("fetched", True)
    incomplete_note = _possibly_incomplete_note(team["team_name"]) + "\n" if team.get("possibly_incomplete") else ""
    body = f"""<nav aria-label="breadcrumb"><a href="/">All leagues</a> &rsaquo; <a href="/{e(league_slug)}/">{e(team['league_name'])}</a></nav>
<h1>{e(team['team_name'])}</h1>
<p class="schedule-source-note">{e(team["schedule_source_note"])}</p>
{incomplete_note}{_subscribe_block(ics_https_url=ics_https, ics_webcal_url=ics_webcal, label=team["team_name"])}
{_next_game_hero(team["games"], team_name=team["team_name"], fetched=fetched)}
<h2>Upcoming games</h2>
{_games_table(team["games"], buy_link_subject=team["team_name"], fetched=fetched)}
"""
    og_image, og_image_alt = LEAGUE_OG_IMAGES.get(league_slug, (DEFAULT_OG_IMAGE, DEFAULT_OG_IMAGE_ALT))
    return _base(
        title=f"{team['team_name']} calendar and tickets | {SITE_NAME}",
        description=(
            f"Subscribe once to the {team['team_name']} ({team['league_name']}) calendar: every "
            "upcoming game, updated nightly, with a link to buy tickets."
        ),
        canonical_url=f"{base_url}/{league_slug}/{team_slug}/",
        base_url=base_url,
        body=body,
        og_image=og_image,
        og_image_alt=og_image_alt,
        ga4_id=ga4_id,
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

.sr-caption { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
"""
