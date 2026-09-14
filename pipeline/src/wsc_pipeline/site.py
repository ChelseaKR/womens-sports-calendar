"""Static HTML generator. No JavaScript, no cookies, no analytics, no
third-party script tags anywhere (DECISIONS 0002) -- every page emitted
here contains zero <script> elements, checked by
tests/test_site_no_script.py and again by the "no external script tags"
build-time check in build.py.

WCAG 2.2 AA per STANDARDS/ACCESSIBILITY-STANDARD.md: semantic landmarks,
table headers with scope, link text that names its destination, sufficient
color contrast (checked values noted inline), no color-only distinctions.
"""

from __future__ import annotations

from html import escape as e

CSS_PATH = "/style.css"


def _base(
    *,
    title: str,
    description: str,
    canonical_url: str,
    body: str,
    og_type: str = "website",
) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<link rel="canonical" href="{e(canonical_url)}">
<link rel="stylesheet" href="{CSS_PATH}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:type" content="{e(og_type)}">
<meta property="og:url" content="{e(canonical_url)}">
</head>
<body>
<a class="skip-link" href="#main">Skip to main content</a>
<header class="site-header">
<p class="brand"><a href="/">womens-sports-calendar</a></p>
</header>
<main id="main">
{body}
</main>
{_footer()}
</body>
</html>
"""


def _footer() -> str:
    return """<footer class="site-footer">
<h2>Sources and terms</h2>
<p>Game data, venues, dates, and prices are read from the
<a href="https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/">Ticketmaster Discovery API</a>,
under its
<a href="https://developer.ticketmaster.com/support/terms-of-use/">Terms of Use</a>.
No league's own schedule is used on this site &mdash; each league page says
why. Purchase links are plain Ticketmaster affiliate URLs; buying through
one tells Ticketmaster this site sent you, and Ticketmaster (via its Impact
affiliate programme) may pay this site a commission on the sale. Prices
shown are the range Ticketmaster publishes for an event; a game with no
Ticketmaster listing shows no price, never a guess.</p>
<p class="privacy-note">Nothing leaves your browser when you read this
site. There is no analytics, no tracking cookie, and no script from anyone
but us on this page. The only thing that reaches another company is a
click on a &ldquo;Buy tickets&rdquo; link, which goes to Ticketmaster's own
site and tells them we sent you.</p>
</footer>
"""


def _subscribe_block(*, ics_https_url: str, ics_webcal_url: str, label: str) -> str:
    return f"""<section class="subscribe" aria-labelledby="subscribe-heading">
<h2 id="subscribe-heading">Subscribe to {e(label)}</h2>
<p><a href="{e(ics_webcal_url)}">Subscribe in your calendar app</a>
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


def _price_cell(price: dict | None) -> str:
    if price is None:
        return '<span class="price-unavailable">not available</span>'
    return f'<span class="price-value">{e(price["currency"])} {price["min"]:.2f}&ndash;{price["max"]:.2f}</span>'


def _games_table(games: list[dict], *, buy_link_subject: str) -> str:
    if not games:
        return "<p>No upcoming games found from Ticketmaster right now.</p>"
    rows = []
    for g in games:
        matchup = f"{g['home_team'] or 'TBD'} vs {g['away_team'] or 'TBD'}"
        venue = ", ".join(p for p in (g["venue_name"], g["venue_city"], g["venue_state"]) if p) or "Venue not available"
        date_note = "" if g["in_calendar_feed"] else " (date TBD &mdash; not yet in the calendar feed)"
        if g["ticket_url"]:
            buy = f'<a href="{e(g["ticket_url"])}">Buy tickets for {e(matchup)} on {e(g["start_display"])} from Ticketmaster</a>'
        else:
            buy = '<span class="price-unavailable">no Ticketmaster listing</span>'
        rows.append(
            "<tr>"
            f"<td>{e(g['start_display'])}{date_note}</td>"
            f"<td>{e(matchup)}</td>"
            f"<td>{e(venue)}</td>"
            f"<td>{_price_cell(g['price'])}</td>"
            f"<td>{buy}</td>"
            "</tr>"
        )
    return f"""<table class="games-table">
<caption class="sr-caption">Upcoming {e(buy_link_subject)} games, from Ticketmaster</caption>
<thead>
<tr>
<th scope="col">Date</th>
<th scope="col">Matchup</th>
<th scope="col">Venue</th>
<th scope="col">Price range</th>
<th scope="col">Tickets</th>
</tr>
</thead>
<tbody>
{"".join(rows)}
</tbody>
</table>
"""


def render_index(
    *,
    leagues: list[dict],
    not_included: list[dict[str, str]],
    base_url: str,
) -> str:
    league_links = "\n".join(
        f'<li><a href="/{e(lg["slug"])}/">{e(lg["name"])}</a> &mdash; {lg["games_count"]} upcoming game(s)</li>'
        for lg in leagues
    )
    not_included_items = "\n".join(
        f"<li><strong>{e(item['name'])}:</strong> {e(item['reason'])}</li>" for item in not_included
    )
    body = f"""<h1>Women's pro sports calendar and ticket-price finder</h1>
<p>Subscribe once to a league or team calendar and see the Ticketmaster
price range before you click. No account, no ads, no tracking.</p>
<h2>Leagues</h2>
<ul class="league-list">
{league_links}
</ul>
<h2>Leagues examined and not included</h2>
<p>Per this site's own licensing research, these leagues' own schedules
were not used because their published terms forbid it or could not be
read; they are not tracked as leagues here at all (their games do not
appear even via Ticketmaster, since no team roster was configured for
them):</p>
<ul>
{not_included_items}
</ul>
"""
    return _base(
        title="womens-sports-calendar",
        description="Subscribable calendars and ticket-price ranges for women's pro sports leagues, from the Ticketmaster Discovery API.",
        canonical_url=f"{base_url}/",
        body=body,
    )


def render_league(
    *,
    league: dict,
    base_url: str,
) -> str:
    slug = league["league_slug"]
    name = league["league_name"]
    ics_https = f"{base_url}/ics/{slug}.ics"
    ics_webcal = ics_https.replace("https://", "webcal://").replace("http://", "webcal://")
    team_links = "\n".join(
        f'<li><a href="/{e(slug)}/{e(t)}/">{e(t.replace("-", " ").title())}</a></li>' for t in league["teams"]
    )
    body = f"""<nav aria-label="breadcrumb"><a href="/">All leagues</a></nav>
<h1>{e(name)}</h1>
<p class="schedule-source-note">{e(league["schedule_source_note"])}</p>
{_subscribe_block(ics_https_url=ics_https, ics_webcal_url=ics_webcal, label=f"all of {name}")}
<h2>Upcoming games</h2>
{_games_table(league["games"], buy_link_subject=name)}
<h2>Teams</h2>
<ul class="team-list">
{team_links}
</ul>
"""
    return _base(
        title=f"{name} calendar and tickets",
        description=f"Subscribe to a {name} calendar and see Ticketmaster ticket price ranges for upcoming games.",
        canonical_url=f"{base_url}/{slug}/",
        body=body,
    )


def render_team(
    *,
    team: dict,
    base_url: str,
) -> str:
    league_slug = team["league_slug"]
    team_slug = team["team_slug"]
    ics_https = f"{base_url}/ics/{league_slug}/{team_slug}.ics"
    ics_webcal = ics_https.replace("https://", "webcal://").replace("http://", "webcal://")
    body = f"""<nav aria-label="breadcrumb"><a href="/">All leagues</a> &rsaquo; <a href="/{e(league_slug)}/">{e(team['league_name'])}</a></nav>
<h1>{e(team['team_name'])}</h1>
<p class="schedule-source-note">{e(team["schedule_source_note"])}</p>
{_subscribe_block(ics_https_url=ics_https, ics_webcal_url=ics_webcal, label=team["team_name"])}
<h2>Upcoming games</h2>
{_games_table(team["games"], buy_link_subject=team["team_name"])}
"""
    return _base(
        title=f"{team['team_name']} calendar and tickets",
        description=f"Subscribe to the {team['team_name']} calendar and see Ticketmaster ticket price ranges for upcoming games.",
        canonical_url=f"{base_url}/{league_slug}/{team_slug}/",
        body=body,
    )


STYLE_CSS = """\
:root {
  color-scheme: light dark;
  --bg: #ffffff;
  --fg: #111318;
  --muted: #45494f;
  --link: #0b4f9c;
  --link-visited: #5b2d8f;
  --border: #c7ccd1;
  --accent-bg: #eef3fb;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #10131a;
    --fg: #f1f3f6;
    --muted: #c3c8d0;
    --link: #8fc0ff;
    --link-visited: #d3b3ff;
    --border: #454b55;
    --accent-bg: #1c2433;
  }
}
* { box-sizing: border-box; }
body {
  background: var(--bg);
  color: var(--fg);
  font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  line-height: 1.5;
  margin: 0;
  padding: 0 1rem;
}
main, .site-header, .site-footer { max-width: 60rem; margin: 0 auto; }
a { color: var(--link); }
a:visited { color: var(--link-visited); }
a:focus-visible, button:focus-visible { outline: 3px solid var(--link); outline-offset: 2px; }
.skip-link {
  position: absolute; left: -999px; top: 0;
  background: var(--accent-bg); color: var(--fg); padding: 0.5rem 1rem; z-index: 10;
}
.skip-link:focus { left: 0.5rem; top: 0.5rem; }
.site-header { padding: 1rem 0; border-bottom: 1px solid var(--border); }
.brand a { font-weight: 700; text-decoration: none; }
table.games-table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
table.games-table th, table.games-table td {
  border: 1px solid var(--border); padding: 0.5rem 0.75rem; text-align: left; vertical-align: top;
}
table.games-table th { background: var(--accent-bg); }
.price-unavailable { color: var(--muted); font-style: italic; }
.price-value { font-weight: 600; }
.subscribe { background: var(--accent-bg); border: 1px solid var(--border); border-radius: 0.5rem; padding: 1rem 1.25rem; margin: 1.25rem 0; }
.subscribe-instructions li { margin-bottom: 0.4rem; }
.schedule-source-note { color: var(--muted); font-size: 0.95rem; }
.site-footer { border-top: 1px solid var(--border); margin-top: 2rem; padding: 1rem 0 2rem; color: var(--muted); font-size: 0.9rem; }
.site-footer a { color: var(--link); }
.sr-caption { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
"""
