"""/llms.txt, in the format llmstxt.org specifies (read 2026-10-22): an H1
with the site's name, a blockquote summary, plain-text sections, then H2
sections that are lists of [name](url): note links.

Plain facts only, from the same configuration the pages are built from. The
feeds listed are the ones this build wrote (feeds.py), never a guess.
"""

from __future__ import annotations

from collections.abc import Iterable

from . import config, feeds, ics

SPEC_URL = "https://llmstxt.org/"


def render(*, base_url: str, feed_keys: Iterable[str] = ()) -> str:
    keys = set(feed_keys)
    leagues = list(config.LEAGUES)
    names = ", ".join(lg.name for lg in leagues)
    lines = [
        "# Next Home Game",
        "",
        "> Next Home Game publishes women's sports game schedules as subscribable calendar "
        f"(.ics) files and web pages, for {names}. Game data comes from the Ticketmaster "
        "Discovery API only. It is an independent site, not affiliated with any league, "
        "team or Ticketmaster.",
        "",
        "How the data works: the site is rebuilt once a night (08:13 UTC) from Ticketmaster's "
        "listings, so a page shows games as listed at the last build, with the fetch time on "
        "the page. A game with no published date or time is shown as date TBD or time TBA and is "
        "never given a guessed time. Home and away are stated only when Ticketmaster's event "
        "name says which side is at home. Schedules can change after a build; confirm a game "
        "with the team before you go. The site shows no ticket prices.",
        "",
        "How to cite: name the page and its address, say the listings come from Ticketmaster, "
        f'and give the "Listings as of" time printed on the page. Example: "Next Home Game, '
        f'{base_url}/wnba/, game listings from Ticketmaster, as of the time printed on the page."',
        "",
        "Feeds carry no purchase links. Pages may carry ticket links, some of which can be "
        "paid (affiliate) links; those are labeled as paid links on the page where they appear.",
        "",
        f"This file follows the llms.txt format described at {SPEC_URL}.",
        "",
        "## Leagues",
        "",
    ]
    for lg in leagues:
        lines.append(
            f"- [{lg.name}]({base_url}/{lg.slug}/): upcoming games for {len(lg.teams)} teams, one page per team"
        )
    lines += [
        "",
        "## Calendars (iCalendar)",
        "",
        f"- [All leagues]({base_url}/{ics.COMBINED_FEED_PATH}): every listed game in one calendar",
    ]
    for lg in leagues:
        lines.append(
            f"- [{lg.name}]({base_url}/ics/{lg.slug}.ics): one league's games; each team also has /ics/{lg.slug}/<team>.ics"
        )
    lines += ["", "## Feeds (Atom) and data", ""]
    if feeds.ALL_KEY in keys:
        lines.append(
            f"- [Home games, all leagues]({base_url}/{feeds.feed_path(feeds.ALL_KEY)}): Atom 1.0; an entry's date is the game's start time"
        )
    for lg in leagues:
        if lg.slug in keys:
            lines.append(f"- [{lg.name} home games]({base_url}/{feeds.feed_path(lg.slug)}): Atom 1.0")
    lines += [
        f"- [Site summary]({base_url}/data/site.json): JSON, per-league counts and the fetch time",
        f"- [Sitemap]({base_url}/sitemap.xml): every page, with lastmod only where the schedule's change is known",
        "",
        "## Policies",
        "",
        f"- [Privacy]({base_url}/privacy/): what the site collects and the affiliate-link disclosure",
        f"- [Accessibility]({base_url}/accessibility/)",
        "",
    ]
    return "\n".join(lines)
