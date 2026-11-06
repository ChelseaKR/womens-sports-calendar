"""Count home games Wikipedia lists against what Ticketmaster lists (DECISIONS 0034).

Run only by .github/workflows/measure-gap.yml (workflow_dispatch). It answers
two questions before anyone decides whether a second source is worth using:
how many home games is each team missing because its tickets are sold
elsewhere, and, for the games both sources list, do they agree on the date
and the venue? The bar for "agree" is 95% of shared games.

The Ticketmaster side uses the site's own search and attribution code,
unchanged (build._search_team, build.attribute_games,
site_data.tracked_team_is_home), as measure_leagues.py does.

The Wikipedia side reads a fixed list of English Wikipedia article pages
(WIKI_SOURCES), one request per title, with an honest User-Agent that names
a contact (Wikimedia's User-Agent policy), at most one request every
WIKI_MIN_INTERVAL seconds. It reads ordinary article pages under /wiki/,
which en.wikipedia.org's robots.txt allows for "friendly, low-speed bots".
It never reads /w/ or /api/: on 2026-11-05 robots.txt disallowed both for
every user agent, including /api/rest_v1/ (only its ?doc page is allowed).

It writes counts only. No date, opponent, venue, time or event name from
either source leaves this module, and nothing is published: the counts go to
the job summary and a `gap-measurement` artifact. A page that failed, does
not exist or has no schedule table the parser recognizes is shown as not
measured, never as 0 games (absence is not a value).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from .build import _search_team, attribute_games
from .config import League, Team, league_by_slug
from .normalize import Game
from .site_data import tracked_team_is_home
from .ticketmaster import DiscoveryClient, TicketmasterFetchError

WIKI_BASE = "https://en.wikipedia.org/wiki/"
# Wikimedia's User-Agent policy asks automated clients to say who they are
# and how to reach the operator.
WIKI_USER_AGENT = "NextHomeGame-gap-measure/0.1 (https://nexthomegame.com/; chelsea@chelseakr.com) python-httpx"
WIKI_MIN_INTERVAL = 3.0
# Far more than the titles below need; a typo that loops can never hammer
# the site.
WIKI_MAX_REQUESTS = 40
# Shared with the nightly build (5,000 a day); this run needs about 30.
TM_MAX_REQUESTS = 300

AGREEMENT_BAR = 0.95
# A Wikipedia game and a Ticketmaster game against the same opponent this
# many days apart or less are taken to be the same game, so a date
# disagreement can be seen at all.
PAIR_WINDOW_DAYS = 7

MEASURED = "measured"
FAILED = "failed"
NO_PAGE = "not measured: no Wikipedia page"
NO_TABLE = "not measured: no schedule table recognized"
OVER_CAP = "skipped: request cap reached"
NOT_RUN = "not measured: Ticketmaster not read in this run"


@dataclass(frozen=True)
class WikiSource:
    """Where one tracked team's home games are on Wikipedia.

    kind "pwhl-season": the league season page, whose schedule tables have
    Visitor and Home columns naming teams by city (`wiki_name`) and dates
    with no year. kind "cbb-team": a college team-season page, whose one
    schedule table names the opponent, with "at" in front for a road game
    and "vs." for a neutral site."""

    league_slug: str
    team_slug: str
    title: str
    kind: str
    wiki_name: str = ""
    # The team's seller is not Ticketmaster (or is a team store Discovery
    # leaves out): the gap teams of 2026-11-05. The others are controls,
    # for the agreement check.
    gap_team: bool = False


def _pwhl(team_slug: str, wiki_name: str, *, gap: bool = False) -> WikiSource:
    return WikiSource("pwhl", team_slug, "2026–27 PWHL season", "pwhl-season", wiki_name, gap)


def _cbb(league_slug: str, team_slug: str, title: str, *, gap: bool = False) -> WikiSource:
    return WikiSource(league_slug, team_slug, title, "cbb-team", gap_team=gap)


B1G = "ncaaw-big-ten"
SEC = "ncaaw-sec"

# The eight vendor-gap teams of nhg-ticketing-gap-2026-11-05 plus controls
# Ticketmaster lists. Titles were chosen 2026-11-05; one that does not exist
# is reported as not measured. WNBA teams are re-measured once the 2027
# schedule is out (owner decision 2026-11-05); NWSL and AUSL are in their
# offseason.
WIKI_SOURCES: tuple[WikiSource, ...] = (
    _pwhl("minnesota-frost", "Minnesota", gap=True),
    _pwhl("vancouver-goldeneyes", "Vancouver", gap=True),
    _pwhl("pwhl-las-vegas", "Las Vegas", gap=True),
    _pwhl("boston-fleet", "Boston"),
    _pwhl("pwhl-detroit", "Detroit"),
    _pwhl("pwhl-hamilton", "Hamilton"),
    _pwhl("montreal-victoire", "Montreal"),
    _pwhl("new-york-sirens", "New York"),
    _pwhl("ottawa-charge", "Ottawa"),
    _pwhl("pwhl-san-jose", "San Jose"),
    _pwhl("seattle-torrent", "Seattle"),
    _pwhl("toronto-sceptres", "Toronto"),
    _cbb(
        B1G,
        "minnesota-golden-gophers-womens-basketball",
        "2026–27 Minnesota Golden Gophers women's basketball team",
        gap=True,
    ),
    _cbb(B1G, "purdue-boilermakers-womens-basketball", "2026–27 Purdue Boilermakers women's basketball team", gap=True),
    _cbb(
        B1G,
        "michigan-state-spartans-womens-basketball",
        "2026–27 Michigan State Spartans women's basketball team",
        gap=True,
    ),
    _cbb(B1G, "indiana-hoosiers-womens-basketball", "2026–27 Indiana Hoosiers women's basketball team", gap=True),
    _cbb(SEC, "arkansas-razorbacks-womens-basketball", "2026–27 Arkansas Razorbacks women's basketball team", gap=True),
    _cbb(SEC, "missouri-tigers-womens-basketball", "2026–27 Missouri Tigers women's basketball team", gap=True),
    _cbb(B1G, "ohio-state-buckeyes-womens-basketball", "2026–27 Ohio State Buckeyes women's basketball team"),
    _cbb(B1G, "penn-state-nittany-lions-womens-basketball", "2026–27 Penn State Lady Lions basketball team"),
    _cbb(B1G, "oregon-ducks-womens-basketball", "2026–27 Oregon Ducks women's basketball team"),
    _cbb(B1G, "iowa-hawkeyes-womens-basketball", "2026–27 Iowa Hawkeyes women's basketball team"),
    _cbb(SEC, "south-carolina-gamecocks-womens-basketball", "2026–27 South Carolina Gamecocks women's basketball team"),
    _cbb(SEC, "tennessee-lady-volunteers-womens-basketball", "2026–27 Tennessee Lady Volunteers basketball team"),
    _cbb(SEC, "kentucky-wildcats-womens-basketball", "2026–27 Kentucky Wildcats women's basketball team"),
)


# ---------------------------------------------------------------- parsing


@dataclass(frozen=True)
class WikiGame:
    """One home game as a Wikipedia page lists it. Never written out."""

    day: date
    opponent: str
    site: str  # "" when the page names no venue for it


@dataclass
class _Table:
    section: str
    rows: list[list[str]] = field(default_factory=list)


class _WikitableParser(HTMLParser):
    """Every table with class "wikitable", as rows of cell text, with the
    h2 section it sits under. <style> and <sup> text is dropped (inline
    styles and footnote markers), and <br> becomes a space."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[_Table] = []
        self._section = ""
        self._in_h2 = False
        self._h2_text: list[str] = []
        self._depth = 0  # nesting of wikitables
        self._skip = 0
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("style", "sup", "script"):
            self._skip += 1
        elif tag == "h2":
            self._in_h2, self._h2_text = True, []
        elif tag == "table":
            classes = (dict(attrs).get("class") or "").split()
            if self._depth or "wikitable" in classes:
                self._depth += 1
                if self._depth == 1:
                    self.tables.append(_Table(section=self._section))
        elif self._depth == 1 and tag == "tr":
            self._row = []
        elif self._depth == 1 and tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("style", "sup", "script"):
            self._skip = max(0, self._skip - 1)
        elif tag == "h2" and self._in_h2:
            self._in_h2 = False
            self._section = _clean("".join(self._h2_text))
        elif tag == "table" and self._depth:
            self._depth -= 1
        elif self._depth == 1 and tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(_clean("".join(self._cell)))
            self._cell = None
        elif self._depth == 1 and tag == "tr" and self._row is not None:
            if self._row:
                self.tables[-1].rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._in_h2:
            self._h2_text.append(data)
        if self._cell is not None:
            self._cell.append(data)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def wikitables(html: str) -> list[_Table]:
    parser = _WikitableParser()
    parser.feed(html)
    parser.close()
    return parser.tables


_MONTHS = {
    m: i
    for i, m in enumerate(
        (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ),
        start=1,
    )
}
_DATE_WITH_YEAR = re.compile(r"\b([A-Z][a-z]+) (\d{1,2}), (\d{4})\b")
_DATE_NO_YEAR = re.compile(r"^([A-Z][a-z]+) (\d{1,2})\b")
_SEASON_START = re.compile(r"^(\d{4})[–-]\d{2}\b")


def _date(month: str, day: str, year: int) -> date | None:
    m = _MONTHS.get(month.lower())
    if m is None:
        return None
    try:
        return date(year, m, int(day))
    except ValueError:
        return None


def parse_pwhl_season(html: str, title: str, wiki_name: str) -> list[WikiGame] | None:
    """`wiki_name`'s regular-season home games on the PWHL season page, or
    None when no schedule table is recognized. Dates carry no year: a
    month from July on is the season's first year ("2026–27" -> 2026),
    an earlier one the next. Preseason tables are left out (only tables
    under the "Regular season" heading count). These tables name no venue,
    so `site` is empty."""
    start = _SEASON_START.match(title)
    if start is None:
        return None
    first_year = int(start.group(1))
    found_table = False
    games: list[WikiGame] = []
    for table in wikitables(html):
        if table.section.lower() != "regular season" or not table.rows:
            continue
        header = [c.lower() for c in table.rows[0]]
        if "date" not in header or "visitor" not in header or "home" not in header:
            continue
        found_table = True
        i_date, i_vis, i_home = header.index("date"), header.index("visitor"), header.index("home")
        for row in table.rows[1:]:
            if len(row) <= max(i_date, i_vis, i_home) or row[i_home] != wiki_name:
                continue
            m = _DATE_NO_YEAR.match(row[i_date])
            if m is None:
                continue
            month = _MONTHS.get(m.group(1).lower())
            if month is None:
                continue
            day = _date(m.group(1), m.group(2), first_year if month >= 7 else first_year + 1)
            if day is not None:
                games.append(WikiGame(day=day, opponent=row[i_vis], site=""))
    return games if found_table else None


_ROAD = re.compile(r"^(at|@)\s", re.IGNORECASE)
_NEUTRAL = re.compile(r"^vs\.?\s", re.IGNORECASE)
_RANK = re.compile(r"^(No\. ?\d+|#\d+)\s+")


def parse_cbb_team(html: str) -> list[WikiGame] | None:
    """Home games in a college team-season page's schedule table, or None
    when no table has Date, Opponent and Site columns. A home game is a row
    whose opponent has neither "at" (road) nor "vs." (neutral site) in
    front, the convention of Wikipedia's college basketball schedule
    template."""
    found_table = False
    games: list[WikiGame] = []
    for table in wikitables(html):
        if not table.rows:
            continue
        header = [c.lower() for c in table.rows[0]]
        i_date = next((i for i, c in enumerate(header) if c.startswith("date")), None)
        i_opp = next((i for i, c in enumerate(header) if c.startswith("opponent")), None)
        i_site = next((i for i, c in enumerate(header) if c.startswith("site")), None)
        if i_date is None or i_opp is None or i_site is None:
            continue
        found_table = True
        for row in table.rows[1:]:
            if len(row) != len(header):
                continue  # section bands ("Regular season") and footnotes
            m = _DATE_WITH_YEAR.search(row[i_date])
            if m is None:
                continue
            day = _date(m.group(1), m.group(2), int(m.group(3)))
            opponent = _RANK.sub("", row[i_opp])
            if day is None or _ROAD.match(opponent) or _NEUTRAL.match(opponent):
                continue
            games.append(WikiGame(day=day, opponent=opponent, site=row[i_site]))
    return games if found_table else None


def parse(source: WikiSource, html: str) -> list[WikiGame] | None:
    if source.kind == "pwhl-season":
        return parse_pwhl_season(html, source.title, source.wiki_name)
    return parse_cbb_team(html)


# --------------------------------------------------------------- matching

_STOP = {
    "the",
    "womens",
    "women",
    "s",
    "basketball",
    "pwhl",
    "la",
    "de",
    "university",
    "of",
    "lady",
}


def _tokens(text: str) -> set[str]:
    """Lowercase words with accents, parentheses and filler removed:
    "St. Thomas (MN)" -> {"st", "thomas"}, "La Victoire De Montréal" ->
    {"victoire", "montreal"}."""
    text = unicodedata.normalize("NFKD", re.sub(r"\([^)]*\)", " ", text))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return {w for w in re.findall(r"[a-z0-9]+", text) if w not in _STOP}


def _same_opponent(wiki_opponent: str, tm_opponent: str) -> bool:
    a, b = _tokens(wiki_opponent), _tokens(tm_opponent)
    return bool(a) and bool(b) and (a <= b or b <= a)


def _same_venue(wiki_site: str, game: Game) -> bool:
    """True when Ticketmaster's venue city, or every word of its venue name,
    appears in Wikipedia's site cell ("The Barn Minneapolis, MN")."""
    site = _tokens(wiki_site)
    city = _tokens(game.venue_city or "")
    venue = _tokens(game.venue_name or "")
    return bool(site) and ((bool(city) and city <= site) or (bool(venue) and venue <= site))


@dataclass
class Agreement:
    shared: int = 0
    date_agree: int = 0
    venue_compared: int = 0
    venue_agree: int = 0
    agree: int = 0


def compare(wiki: list[WikiGame], tm_home: list[Game]) -> Agreement:
    """Pair each Wikipedia home game with the closest Ticketmaster home game
    against the same opponent, at most PAIR_WINDOW_DAYS apart, each game
    used once. A pair agrees when the dates are equal and, if Wikipedia
    names a venue, the venues match too."""
    out = Agreement()
    unused = [(g.start_local_date, g) for g in tm_home if g.start_local_date is not None]
    for w in sorted(wiki, key=lambda g: g.day):
        best: tuple[date, Game] | None = None
        best_gap = PAIR_WINDOW_DAYS + 1
        for day, g in unused:
            gap = abs((day - w.day).days)
            if gap < best_gap and _same_opponent(w.opponent, g.away_team or ""):
                best, best_gap = (day, g), gap
        if best is None:
            continue
        unused.remove(best)
        best_game = best[1]
        out.shared += 1
        same_date = best_gap == 0
        out.date_agree += same_date
        venue_ok = True
        if w.site:
            out.venue_compared += 1
            venue_ok = _same_venue(w.site, best_game)
            out.venue_agree += venue_ok
        out.agree += same_date and venue_ok
    return out


# ----------------------------------------------------------------- fetching


class WikipediaClient:
    """Sequential, rate-limited reader of English Wikipedia article pages.
    Each title is fetched at most once per run."""

    def __init__(self, *, client: httpx.Client | None = None, min_interval: float = WIKI_MIN_INTERVAL) -> None:
        self._client = client or httpx.Client(
            timeout=30.0, headers={"User-Agent": WIKI_USER_AGENT}, follow_redirects=True
        )
        self._min_interval = min_interval
        self._last: float | None = None
        self._cache: dict[str, tuple[str, str | None]] = {}
        self.requests_made = 0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> WikipediaClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @staticmethod
    def url_for(title: str) -> str:
        return WIKI_BASE + quote(title.replace(" ", "_"), safe="")

    def page(self, title: str) -> tuple[str, str | None]:
        """(status, html): MEASURED with the page, NO_PAGE, FAILED or
        OVER_CAP with None."""
        if title in self._cache:
            return self._cache[title]
        if self.requests_made >= WIKI_MAX_REQUESTS:
            return OVER_CAP, None
        if self._last is not None:
            wait = self._min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
        self._last = time.monotonic()
        self.requests_made += 1
        url = self.url_for(title)
        if not url.startswith(WIKI_BASE):  # pragma: no cover - guarded by construction
            raise ValueError(url)
        try:
            response = self._client.get(url)
        except httpx.HTTPError as exc:
            print(f"wikipedia {title!r}: {type(exc).__name__}", file=sys.stderr)
            result: tuple[str, str | None] = (FAILED, None)
        else:
            if response.status_code == 404:
                result = (NO_PAGE, None)
            elif response.status_code != 200:
                print(f"wikipedia {title!r}: HTTP {response.status_code}", file=sys.stderr)
                result = (FAILED, None)
            else:
                result = (MEASURED, response.text)
        self._cache[title] = result
        return result


# ------------------------------------------------------------------ measuring


@dataclass
class TeamGap:
    league: str
    team: str
    gap_team: bool
    wikipedia_status: str = ""
    ticketmaster_status: str = ""
    wikipedia_home: int | None = None
    ticketmaster_home: int | None = None
    # Wikipedia home minus Ticketmaster home, upcoming games only.
    missing: int | None = None
    shared: int | None = None
    date_agree: int | None = None
    venue_compared: int | None = None
    venue_agree: int | None = None
    agree: int | None = None


def _upcoming(day: date | None, today: date) -> bool:
    return day is not None and day >= today


def _team(source: WikiSource) -> tuple[League, Team]:
    league = league_by_slug(source.league_slug)
    return league, next(t for t in league.teams if t.slug == source.team_slug)


def _ticketmaster_home(
    client: DiscoveryClient | None, sources: tuple[WikiSource, ...], today: date
) -> dict[tuple[str, str], tuple[str, list[Game] | None]]:
    """{(league, team): (status, upcoming home games or None)} using the
    site's own search and attribution, as the nightly build would list
    them."""
    out: dict[tuple[str, str], tuple[str, list[Game] | None]] = {}
    if client is None:
        return {(s.league_slug, s.team_slug): (NOT_RUN, None) for s in sources}
    raw_by_team: dict[tuple[str, str], list[dict[str, Any]]] = {}
    leagues: dict[str, League] = {}
    teams: dict[tuple[str, str], Team] = {}
    for s in sources:
        league, team = _team(s)
        leagues[league.slug] = league
        key = (s.league_slug, s.team_slug)
        teams[key] = team
        if client.budget.requests_made >= TM_MAX_REQUESTS:
            out[key] = (OVER_CAP, None)
            continue
        try:
            raw, _truncated = _search_team(client, league, team)
        except TicketmasterFetchError as exc:
            print(f"{s.league_slug}/{s.team_slug}: {exc}", file=sys.stderr)
            out[key] = (FAILED, None)
            continue
        raw_by_team[key] = raw
    # Only the searched teams are in each league here, so an event is
    # attributed only to teams this run measures.
    searched = {
        slug: League(
            slug=lg.slug,
            name=lg.name,
            country_codes=lg.country_codes,
            teams=tuple(t for t in lg.teams if (lg.slug, t.slug) in raw_by_team),
        )
        for slug, lg in leagues.items()
    }
    games, _mismatched = attribute_games(tuple(searched.values()), raw_by_team)
    for key in raw_by_team:
        team = teams[key]
        home = [
            g
            for g in games
            if (g.league_slug, g.tracked_team_slug) == key
            and tracked_team_is_home(team, g) is True
            and _upcoming(g.start_local_date, today)
            and g.status_code != "cancelled"
        ]
        out[key] = (MEASURED, home)
    return out


def measure(
    wiki: WikipediaClient,
    tm: DiscoveryClient | None,
    today: date,
    *,
    generated_at: datetime,
    sources: tuple[WikiSource, ...] = WIKI_SOURCES,
) -> dict[str, Any]:
    tm_home = _ticketmaster_home(tm, sources, today)
    teams: list[TeamGap] = []
    for s in sources:
        team = _team(s)[1]
        row = TeamGap(league=s.league_slug, team=team.shown_name, gap_team=s.gap_team)
        status, html = wiki.page(s.title)
        wiki_games = parse(s, html) if html is not None else None
        if status == MEASURED and wiki_games is None:
            status = NO_TABLE
        row.wikipedia_status = status
        if wiki_games is not None:
            wiki_games = [g for g in wiki_games if _upcoming(g.day, today)]
            row.wikipedia_home = len(wiki_games)
        row.ticketmaster_status, tm_games = tm_home[(s.league_slug, s.team_slug)]
        if tm_games is not None:
            row.ticketmaster_home = len(tm_games)
        if wiki_games is not None and tm_games is not None:
            row.missing = len(wiki_games) - len(tm_games)
            agreement = compare(wiki_games, tm_games)
            row.shared = agreement.shared
            row.date_agree = agreement.date_agree
            row.venue_compared = agreement.venue_compared
            row.venue_agree = agreement.venue_agree
            row.agree = agreement.agree
        teams.append(row)
    compared = [t for t in teams if t.shared is not None]
    shared = sum(t.shared or 0 for t in compared)
    agree = sum(t.agree or 0 for t in compared)
    missing_gap = [t.missing for t in teams if t.gap_team and t.missing is not None]
    return {
        "generated_at": generated_at.isoformat(),
        "counted_from": today.isoformat(),
        "wikipedia_requests": wiki.requests_made,
        "ticketmaster_requests": tm.budget.requests_made if tm is not None else None,
        "agreement_bar": AGREEMENT_BAR,
        "shared_games": shared if compared else None,
        "agreeing_games": agree if compared else None,
        "agreement": (agree / shared) if shared else None,
        "meets_bar": (agree / shared >= AGREEMENT_BAR) if shared else None,
        "gap_teams_measured": len(missing_gap),
        "gap_teams_total": sum(1 for t in teams if t.gap_team),
        "gap_missing_total": sum(missing_gap) if missing_gap else None,
        "teams": [asdict(t) for t in teams],
    }


def _cell(value: object) -> str:
    """A count, or a dash when it was not measured (never 0 for unknown)."""
    if value is None:
        return "–"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def render_markdown(report: dict[str, Any]) -> str:
    agreement = report["agreement"]
    lines = [
        "# Home-game gap: Wikipedia against Ticketmaster",
        "",
        f"Generated {report['generated_at']}. Upcoming means on or after {report['counted_from']}.",
        f"{report['wikipedia_requests']} Wikipedia page requests,"
        f" {_cell(report['ticketmaster_requests'])} Ticketmaster Discovery API requests.",
        "",
        "Counts only; nothing here is published. Wikipedia home: upcoming home games the team's Wikipedia"
        " page lists. Ticketmaster home: upcoming games the site would list as this team's home games. Missing:"
        " the first minus the second. Shared: games both list (same opponent, at most"
        f" {PAIR_WINDOW_DAYS} days apart). Agree: shared games with the same date and, where Wikipedia names"
        " one, the same venue. A dash means not measured, not zero.",
        "",
        f"- Agreement on shared games: {_cell(report['agreeing_games'])} of {_cell(report['shared_games'])}"
        + (f" ({agreement:.1%}); bar {report['agreement_bar']:.0%}: " if agreement is not None else "; bar: ")
        + ("met" if report["meets_bar"] else "not met" if report["meets_bar"] is False else "not measured"),
        f"- Vendor-gap teams measured: {report['gap_teams_measured']} of {report['gap_teams_total']};"
        f" home games missing from Ticketmaster across them: {_cell(report['gap_missing_total'])}",
        "",
        "| Team | League | Gap team | Wikipedia home | Ticketmaster home | Missing | Shared | Same date |"
        " Venue compared | Same venue | Agree | Wikipedia | Ticketmaster |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for t in report["teams"]:
        lines.append(
            f"| {t['team']} | {t['league']} | {_cell(t['gap_team'])} | {_cell(t['wikipedia_home'])} |"
            f" {_cell(t['ticketmaster_home'])} | {_cell(t['missing'])} | {_cell(t['shared'])} |"
            f" {_cell(t['date_agree'])} | {_cell(t['venue_compared'])} | {_cell(t['venue_agree'])} |"
            f" {_cell(t['agree'])} | {t['wikipedia_status']} | {t['ticketmaster_status']} |"
        )
    lines.append("")
    lines.append(
        "Sources: English Wikipedia article pages (CC BY-SA 4.0), read for counting only; Ticketmaster Discovery API."
    )
    return "\n".join(lines)


def main(
    argv: list[str] | None = None,
    *,
    wiki: WikipediaClient | None = None,
    tm: DiscoveryClient | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--out", type=Path, required=True, help="directory for gap.json and gap.md")
    parser.add_argument(
        "--wikipedia-only",
        action="store_true",
        help="read Wikipedia only (no API key needed); Ticketmaster columns show as not measured",
    )
    args = parser.parse_args(argv)
    if tm is None and not args.wikipedia_only:
        api_key = os.environ.get("TICKETMASTER_API_KEY", "")
        if not api_key:
            print("TICKETMASTER_API_KEY is not set; nothing was measured.", file=sys.stderr)
            return 2
        tm = DiscoveryClient(api_key)
    now = datetime.now(UTC).replace(microsecond=0)
    with wiki or WikipediaClient() as wiki_client:
        if tm is not None:
            with tm:
                report = measure(wiki_client, tm, now.date(), generated_at=now)
        else:
            report = measure(wiki_client, None, now.date(), generated_at=now)
    markdown = render_markdown(report)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "gap.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (args.out / "gap.md").write_text(markdown + "\n", encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(markdown + "\n")
    print(markdown)
    failed = any(FAILED in (t["wikipedia_status"], t["ticketmaster_status"]) for t in report["teams"])
    # Every count is written either way; a failed fetch still fails the run.
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
