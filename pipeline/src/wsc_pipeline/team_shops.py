"""The "Team shop" link on a team page: the team's store at Fanatics, sent
through the owner's Impact tracking link (DECISIONS 0018).

The link exists only to carry that affiliate id, so it is shown only when
sellers.FANATICS_IMPACT_LINK is set. With no id there is no shop link at
all, rather than an unpaid one: the site is a calendar, a merchandise link
is not something a reader came for, and a plain link that later turns into
a paid one would change its meaning without changing how it looks. With no
id, every page is byte-for-byte what it was before this module existed.

Only league and team pages Fanatics itself lists are used. Every URL below
is the team's page as listed in fanatics.com's own sitemap
(https://www.fanatics.com/bot_www_fanatics_com_sitemap_index.xml, files 0
to 3), read 2026-10-12 under a robots.txt that allows it ("User-agent: *
Allow: /"). No Fanatics page was fetched. A team with no entry gets no
link; a near match is never used.

Not covered, on purpose:

- PWHL and AUSL: the sitemap has no team pages for either league.
- WNBA Portland Fire and Toronto Tempo, and NWSL Bay FC, Boston Legacy,
  Denver Summit and Gotham FC: no team page in the sitemap.
- NCAA women's basketball: Fanatics sells each school's whole-athletics
  store, not a women's basketball store, so a "team shop" link would not
  be this team's.

Chicago Stars FC's Fanatics address still uses the club's former name,
"chicago-red-stars"; it is the club's own team page there.
"""

from __future__ import annotations

from urllib.parse import quote, urlparse

from . import sellers

FANATICS_HOST = "www.fanatics.com"
CHECKED_ON = "2026-10-12"

# (league slug, team slug) -> the team's page at Fanatics.
FANATICS_TEAM_SHOPS: dict[tuple[str, str], str] = {
    ("nwsl", "angel-city"): "https://www.fanatics.com/nwsl/angel-city-fc/o-32797932+t-2333770538+z-92-1228894380",
    ("nwsl", "chicago-stars"): "https://www.fanatics.com/nwsl/chicago-red-stars/o-10462409+t-87507637+z-952-3802278468",
    ("nwsl", "houston-dash"): "https://www.fanatics.com/nwsl/houston-dash/o-98801387+t-09352678+z-80-752680636",
    (
        "nwsl",
        "kansas-city-current",
    ): "https://www.fanatics.com/nwsl/kansas-city-current/o-32804654+t-5699121099+z-94-2877763152",
    (
        "nwsl",
        "north-carolina-courage",
    ): "https://www.fanatics.com/nwsl/north-carolina-courage/o-76021310+t-10056583+z-83-2515100446",
    ("nwsl", "orlando-pride"): "https://www.fanatics.com/nwsl/orlando-pride/o-10241387+t-54244788+z-914-462614558",
    (
        "nwsl",
        "portland-thorns",
    ): "https://www.fanatics.com/nwsl/portland-thorns-fc/o-21791387+t-43471536+z-938-940142781",
    (
        "nwsl",
        "racing-louisville",
    ): "https://www.fanatics.com/nwsl/racing-louisville-fc/o-10790243+t-4522902064+z-91-2150694333",
    (
        "nwsl",
        "san-diego-wave",
    ): "https://www.fanatics.com/nwsl/san-diego-wave-fc/o-10685776+t-1212124144+z-98-3537981838",
    (
        "nwsl",
        "seattle-reign",
    ): "https://www.fanatics.com/nwsl/seattle-reign-fc/o-32575787+t-6777909707+z-99-3614018416",
    ("nwsl", "utah-royals"): "https://www.fanatics.com/nwsl/utah-royals/o-32910221+t-7211297600+z-98-470208292",
    (
        "nwsl",
        "washington-spirit",
    ): "https://www.fanatics.com/nwsl/washington-spirit/o-21792421+t-5677015343+z-93-3021596904",
    ("wnba", "atlanta-dream"): "https://www.fanatics.com/wnba/atlanta-dream/o-1460+t-69434525+z-92374-3568125624",
    ("wnba", "chicago-sky"): "https://www.fanatics.com/wnba/chicago-sky/o-2559+t-69106760+z-91608-4263507522",
    ("wnba", "connecticut-sun"): "https://www.fanatics.com/wnba/connecticut-sun/o-4715+t-92547816+z-93624-729867934",
    ("wnba", "dallas-wings"): "https://www.fanatics.com/wnba/dallas-wings/o-1471+t-25092395+z-92906-162900988",
    (
        "wnba",
        "golden-state-valkyries",
    ): "https://www.fanatics.com/wnba/golden-state-valkyries/o-8126+t-46745985+z-8050-4214175585",
    ("wnba", "indiana-fever"): "https://www.fanatics.com/wnba/indiana-fever/o-5837+t-69436785+z-8826-1776406336",
    ("wnba", "las-vegas-aces"): "https://www.fanatics.com/wnba/las-vegas-aces/o-1482+t-87453972+z-90332-2920441961",
    (
        "wnba",
        "los-angeles-sparks",
    ): "https://www.fanatics.com/wnba/los-angeles-sparks/o-2537+t-03324564+z-8040-3865932782",
    ("wnba", "minnesota-lynx"): "https://www.fanatics.com/wnba/minnesota-lynx/o-3693+t-14981254+z-773-2726048771",
    (
        "wnba",
        "new-york-liberty",
    ): "https://www.fanatics.com/wnba/new-york-liberty/o-1448+t-92983577+z-96745-4259593538",
    ("wnba", "phoenix-mercury"): "https://www.fanatics.com/wnba/phoenix-mercury/o-7048+t-25659123+z-8840-3801808752",
    ("wnba", "seattle-storm"): "https://www.fanatics.com/wnba/seattle-storm/o-3604+t-03094693+z-92283-1157218896",
    (
        "wnba",
        "washington-mystics",
    ): "https://www.fanatics.com/wnba/washington-mystics/o-3604+t-92091317+z-94317-630925064",
}


def check_team_shops() -> None:
    """Every entry is an https URL on Fanatics' own host, under the entry's
    own league, with no query string. Run at import, so a bad edit fails
    every build and test rather than reaching a page."""
    for (league_slug, team_slug), url in FANATICS_TEAM_SHOPS.items():
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != FANATICS_HOST or parsed.query or parsed.fragment:
            raise ValueError(f"team shop for {league_slug}/{team_slug} is not a plain Fanatics URL: {url}")
        if not parsed.path.startswith(f"/{league_slug}/"):
            raise ValueError(f"team shop for {league_slug}/{team_slug} is not under /{league_slug}/: {url}")


check_team_shops()


def team_shop_url(league_slug: str, team_slug: str) -> str | None:
    """The affiliate link to this team's Fanatics store, or None: always None
    while sellers.FANATICS_IMPACT_LINK is empty, and None for a team with no
    entry above."""
    template = sellers.FANATICS_TEMPLATE
    url = FANATICS_TEAM_SHOPS.get((league_slug, team_slug))
    if not template or url is None:
        return None
    return template.format(url=quote(url, safe=""))
