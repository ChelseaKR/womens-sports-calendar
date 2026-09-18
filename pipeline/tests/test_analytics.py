"""Google Analytics 4 (DECISIONS 0012): on the HTML pages only, guarded by
Global Privacy Control / Do Not Track, ads features off, and never in the
.ics feeds.

Three layers:

1. Build-level: a build with no ID emits no GA on any page; a build with an
   ID puts the same guarded loader in the <head> of every page (index,
   privacy, 404, every league, every team); the .ics feeds and data JSON
   are byte-identical either way.
2. Behaviour: the emitted snippet is executed in Node against stubbed
   window/navigator/document objects, so "GPC or DNT loads nothing" is
   observed, not inferred from string matching.
3. Negative controls: each checker is run against a deliberately broken
   input, and every control first asserts its sabotage actually landed (a
   no-op sabotage would read as a pass).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from wsc_pipeline import analytics, site
from wsc_pipeline import build as build_module
from wsc_pipeline.analytics import ANALYTICS_DENIED_REGIONS, ga4_head_snippet
from wsc_pipeline.config import LEAGUES
from wsc_pipeline.normalize import normalize_event

from .conftest import STANDARD_PRICE, make_raw_event

TEST_ID = "G-TEST123456"
BASE_URL = "https://nexthomegame.com"
HOST = "nexthomegame.com"
GPC_GUARD = "if (n.globalPrivacyControl === true) return;"
DNT_GUARD = 'if (dnt === "1" || dnt === "yes") return;'
GA_MARKERS = ("<script", "googletagmanager", "gtag", "dataLayer", "google-analytics", TEST_ID)
EEA_UK_CH = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV",
    "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE", "IS", "LI", "NO", "GB", "CH",
}  # fmt: skip


def _expected_pages() -> set[str]:
    pages = {"index.html", "404.html", "privacy/index.html", "accessibility/index.html"}
    for lg in LEAGUES:
        pages.add(f"{lg.slug}/index.html")
        for team in lg.teams:
            pages.add(f"{lg.slug}/{team.slug}/index.html")
    return pages


def _html_pages(out_dir: Path) -> dict[str, str]:
    return {str(p.relative_to(out_dir)): p.read_text(encoding="utf-8") for p in sorted(out_dir.rglob("*.html"))}


def _fetched_games():
    """One priced WNBA game with a real Ticketmaster URL, so the ticket link,
    the .ics DESCRIPTION/URL, and the data JSON all have content to compare."""
    league, team = LEAGUES[0], LEAGUES[0].teams[0]
    raw = make_raw_event(
        event_id="EVT-GA",
        name=f"{team.name} vs Visiting Team",
        price_ranges=STANDARD_PRICE,
        url="https://www.ticketmaster.com/event/EVT-GA",
    )
    game = normalize_event(raw, league_slug=league.slug, tracked_team_slug=team.slug, tracked_team_name=team.name)
    assert game is not None
    empty = {lg.slug: set() for lg in LEAGUES}
    return [game], empty, {lg.slug: set() for lg in LEAGUES}, 1, 100


def _assert_guarded_ga(html: str, ga4_id: str) -> None:
    """The page carries exactly one <script>, in <head>, and it is exactly
    the guarded loader: the hostname, GPC and DNT guards all return before
    dataLayer, the gtag.js request, or the click listener exist."""
    scripts = re.findall(r"<script\b.*?</script>", html, flags=re.IGNORECASE | re.DOTALL)
    assert len(scripts) == 1, f"expected exactly one <script>, found {len(scripts)}"
    assert len(re.findall(r"<script\b", html, flags=re.IGNORECASE)) == 1
    script = scripts[0]
    assert script + "\n</head>" in html, "the GA loader must close out <head>"
    first_effect = min(
        script.index("w.dataLayer"), script.index("createElement"), script.index('d.addEventListener("click"')
    )
    for guard in (f'if (w.location.hostname !== "{HOST}") return;', GPC_GUARD, DNT_GUARD):
        assert guard in script, f"missing guard: {guard}"
        assert script.index(guard) < first_effect, f"guard runs too late: {guard}"
    assert "var dnt = n.doNotTrack || w.doNotTrack || n.msDoNotTrack;" in script
    assert "allow_google_signals: false" in script
    assert "allow_ad_personalization_signals: false" in script
    assert f'gtag("config", "{ga4_id}",' in script
    # Loaded only by the guarded code, never as a static <script src>.
    assert not re.search(r"<script[^>]*\bsrc=", html, flags=re.IGNORECASE)
    # And byte-for-byte the loader analytics.py emits (whose behaviour the
    # Node tests below execute) -- checked last, so the negative controls
    # exercise the specific checks above rather than only this one.
    assert script == ga4_head_snippet(ga4_id, base_url=BASE_URL).rstrip("\n")


# ---------------------------------------------------------------------------
# 1. Build-level
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("unset", [None, "", "   "])
def test_a_build_with_no_id_emits_no_ga_on_any_page(tmp_path: Path, unset):
    out_dir = tmp_path / "dist"
    build_module.build(out_dir=out_dir, base_url=BASE_URL, api_key=None, affiliate_id=None, ga4_id=unset)
    pages = _html_pages(out_dir)
    assert set(pages) == _expected_pages()
    for path, html in pages.items():
        for marker in GA_MARKERS:
            assert marker not in html, f"{path} contains {marker!r} with no GA4 ID set"
        assert "This site runs no analytics" in html, path
        assert "Google Analytics" not in html, path
    assert "Web pages: no analytics" in pages["privacy/index.html"]


def test_a_build_with_an_id_emits_the_guarded_tag_on_every_page(tmp_path: Path):
    out_dir = tmp_path / "dist"
    build_module.build(out_dir=out_dir, base_url=BASE_URL, api_key=None, affiliate_id=None, ga4_id=TEST_ID)
    pages = _html_pages(out_dir)
    assert set(pages) == _expected_pages()
    assert len(pages) > 70  # every page, not a handful
    for path, html in pages.items():
        try:
            _assert_guarded_ga(html, TEST_ID)
        except AssertionError as exc:
            raise AssertionError(f"{path}: {exc}") from exc
        assert "use Google Analytics" in html and "Global\nPrivacy Control or Do Not Track" in html, path
        assert "This site runs no analytics" not in html, path
    privacy = pages["privacy/index.html"]
    assert "Web pages: Google Analytics" in privacy
    assert f"Kept for {analytics.GA4_DATA_RETENTION}" in privacy
    assert "Calendar feeds: never tracked" in privacy


def test_ga_never_reaches_the_ics_feeds_or_data_and_they_are_unchanged(tmp_path: Path, monkeypatch):
    """The .ics feeds (and the data JSON they are validated against) are
    byte-identical whether or not an ID is set, and carry no GA marker."""
    monkeypatch.setattr(build_module, "fetch_all_games", lambda api_key: _fetched_games())
    without, with_id = tmp_path / "without", tmp_path / "with"
    build_module.build(out_dir=without, base_url=BASE_URL, api_key="fake-key", affiliate_id=None, ga4_id=None)
    build_module.build(out_dir=with_id, base_url=BASE_URL, api_key="fake-key", affiliate_id=None, ga4_id=TEST_ID)

    def payload_files(root: Path) -> dict[str, bytes]:
        return {
            str(p.relative_to(root)): p.read_bytes()
            for sub in ("ics", "data")
            for p in sorted((root / sub).rglob("*"))
            if p.is_file()
        }

    def comparable(name: str, data: bytes):
        # site.json stamps its own build time (site_data.site_summary); every
        # other byte, and every byte of every .ics feed, must match.
        if name == "data/site.json":
            parsed = json.loads(data)
            assert parsed.pop("generated_at")
            return parsed
        return data

    a, b = payload_files(without), payload_files(with_id)
    ics_files = [k for k in a if k.endswith(".ics")]
    assert len(ics_files) == sum(1 + len(lg.teams) for lg in LEAGUES)
    assert a.keys() == b.keys()
    for name in a:
        assert comparable(name, a[name]) == comparable(name, b[name]), f"{name} differs when a GA4 ID is set"
    # The fixture game really is in a feed, so "unchanged" compared content.
    league_feed = b[f"ics/{LEAGUES[0].slug}.ics"].decode()
    assert "tm-EVT-GA@" in league_feed
    assert "https://www.ticketmaster.com/event/EVT-GA" in league_feed
    for name, data in b.items():
        text = data.decode()
        for marker in (*GA_MARKERS, "utm_", "_ga", "analytics"):
            assert marker not in text, f"{name} contains {marker!r}"


def test_ticket_links_stay_plain_urls_when_ga_is_on(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(build_module, "fetch_all_games", lambda api_key: _fetched_games())
    out_dir = tmp_path / "dist"
    build_module.build(out_dir=out_dir, base_url=BASE_URL, api_key="fake-key", affiliate_id=None, ga4_id=TEST_ID)
    league, team = LEAGUES[0], LEAGUES[0].teams[0]
    for page in (out_dir / league.slug / "index.html", out_dir / league.slug / team.slug / "index.html"):
        html = page.read_text()
        buy_hrefs = re.findall(r'<a [^>]*href="([^"]+)"[^>]*>Buy tickets', html)
        assert buy_hrefs, page
        assert set(buy_hrefs) == {"https://www.ticketmaster.com/event/EVT-GA"}, page
        assert "googleadservices" not in html and "google.com/url" not in html


def test_main_uses_the_committed_measurement_id(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TICKETMASTER_API_KEY", raising=False)
    monkeypatch.setattr(analytics, "GA4_MEASUREMENT_ID", "G-MAIN12345")
    out_dir = tmp_path / "dist"
    assert build_module.main(["--out", str(out_dir), "--base-url", BASE_URL]) == 0
    _assert_guarded_ga((out_dir / "index.html").read_text(), "G-MAIN12345")


def test_main_with_the_id_unset_emits_nothing_and_says_so(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.delenv("TICKETMASTER_API_KEY", raising=False)
    monkeypatch.setattr(analytics, "GA4_MEASUREMENT_ID", "")
    out_dir = tmp_path / "dist"
    assert build_module.main(["--out", str(out_dir), "--base-url", BASE_URL]) == 0
    for path, html in _html_pages(out_dir).items():
        assert "<script" not in html, path
    assert "GA4_MEASUREMENT_ID is empty" in capsys.readouterr().err


def test_the_committed_measurement_id_is_well_formed():
    assert analytics.measurement_id(analytics.GA4_MEASUREMENT_ID) in (None, analytics.GA4_MEASUREMENT_ID)


@pytest.mark.parametrize("bad", ["UA-12345-1", "g-abc12345", 'G-1234"</script>', "G-12", "GTM-ABC123"])
def test_a_malformed_id_fails_the_build_before_anything_is_written(tmp_path: Path, bad):
    out_dir = tmp_path / "dist"
    with pytest.raises(ValueError, match="not a GA4 measurement ID"):
        build_module.build(out_dir=out_dir, base_url=BASE_URL, api_key=None, affiliate_id=None, ga4_id=bad)
    assert not out_dir.exists()


def test_privacy_page_is_in_the_sitemap_and_linked_from_every_footer(tmp_path: Path):
    out_dir = tmp_path / "dist"
    build_module.build(out_dir=out_dir, base_url=BASE_URL, api_key=None, affiliate_id=None, ga4_id=TEST_ID)
    assert f"<loc>{BASE_URL}{site.PRIVACY_PATH}</loc>" in (out_dir / "sitemap.xml").read_text()
    for path, html in _html_pages(out_dir).items():
        assert '<a href="/privacy/">Privacy: what this site measures' in html, path


# ---------------------------------------------------------------------------
# 2. Behaviour: run the emitted snippet in Node
# ---------------------------------------------------------------------------

_HARNESS = r"""
const vm = require("vm");
const fs = require("fs");
const [snippetPath, scenariosPath] = process.argv.slice(2);
const code = fs.readFileSync(snippetPath, "utf8").replace(/^\s*<script>/, "").replace(/<\/script>\s*$/, "");
const scenarios = JSON.parse(fs.readFileSync(scenariosPath, "utf8"));
const out = scenarios.map((sc) => {
  const appended = [];
  const listeners = {};
  const ctx = {
    navigator: Object.assign({}, sc.navigator),
    location: { hostname: sc.hostname },
    document: {
      head: { appendChild: (el) => appended.push(el) },
      createElement: (tag) => ({ tag }),
      addEventListener: (type, fn) => { listeners[type] = fn; },
    },
    Date,
  };
  Object.assign(ctx, sc.window || {});
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  const clicks = (sc.clicks || []).map((link) => {
    const before = ctx.dataLayer ? ctx.dataLayer.length : 0;
    let prevented = false;
    const anchor = Object.assign({}, link, { closest: (sel) => (sel === "main" ? (link.inMain ? {} : null) : null) });
    const ev = { target: { closest: (sel) => (sel === "a[href]" ? anchor : null) }, preventDefault: () => { prevented = true; } };
    if (listeners.click) listeners.click(ev);
    const pushed = ctx.dataLayer ? Array.from(ctx.dataLayer).slice(before).map((a) => Array.from(a)) : [];
    return { pushed, prevented, hrefAfter: anchor.href };
  });
  return {
    name: sc.name,
    dataLayer: ctx.dataLayer ? Array.from(ctx.dataLayer).map((a) => Array.from(a)) : null,
    appended,
    listeners: Object.keys(listeners),
    clicks,
  };
});
process.stdout.write(JSON.stringify(out));
"""

_NOT_LOADED = [
    ("gpc", HOST, {"globalPrivacyControl": True}, {}),
    ("dnt-navigator", HOST, {"doNotTrack": "1"}, {}),
    ("dnt-window", HOST, {}, {"doNotTrack": "1"}),
    ("dnt-ms", HOST, {"msDoNotTrack": "1"}, {}),
    ("dnt-yes", HOST, {"doNotTrack": "yes"}, {}),
    ("gpc-and-dnt", HOST, {"globalPrivacyControl": True, "doNotTrack": "1"}, {}),
    ("local-preview", "127.0.0.1", {}, {}),
    ("other-host", "www.example.com", {}, {}),
]
_TICKET = {
    "href": "https://www.ticketmaster.com/event/EVT1",
    "hostname": "www.ticketmaster.com",
    "protocol": "https:",
    "pathname": "/event/EVT1",
    "inMain": True,
}
_AFFILIATE_TICKET = {
    "href": "https://ticketmaster.evyy.net/c/1/2/3",
    "hostname": "ticketmaster.evyy.net",
    "protocol": "https:",
    "pathname": "/c/1/2/3",
    "inMain": True,
}
_WEBCAL = {
    "href": "webcal://nexthomegame.com/ics/wnba.ics",
    "hostname": "nexthomegame.com",
    "protocol": "webcal:",
    "pathname": "/ics/wnba.ics",
    "inMain": True,
}
_FEED = {
    "href": "https://nexthomegame.com/ics/wnba/minnesota-lynx.ics",
    "hostname": "nexthomegame.com",
    "protocol": "https:",
    "pathname": "/ics/wnba/minnesota-lynx.ics",
    "inMain": True,
}
_FOOTER_TM = {
    "href": "https://developer.ticketmaster.com/support/terms-of-use/",
    "hostname": "developer.ticketmaster.com",
    "protocol": "https:",
    "pathname": "/support/terms-of-use/",
    "inMain": False,
}
_INTERNAL = {
    "href": "https://nexthomegame.com/wnba/",
    "hostname": "nexthomegame.com",
    "protocol": "https:",
    "pathname": "/wnba/",
    "inMain": True,
}
_LOADED = [
    ("no-signal", HOST, {}, {}),
    ("gpc-false-dnt-0", HOST, {"globalPrivacyControl": False, "doNotTrack": "0"}, {}),
    ("dnt-unspecified", HOST, {"doNotTrack": "unspecified"}, {}),
]


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("node is required in CI to execute the GA4 snippet (ci.yml sets it up)")
        pytest.skip("node not installed; this behaviour test runs in CI")
    return node


def _run_snippet(tmp_path: Path, snippet: str, scenarios: list[dict]) -> dict[str, dict]:
    (tmp_path / "harness.js").write_text(_HARNESS, encoding="utf-8")
    (tmp_path / "snippet.html").write_text(snippet, encoding="utf-8")
    (tmp_path / "scenarios.json").write_text(json.dumps(scenarios), encoding="utf-8")
    # node plus three files this test just wrote into its own tmp_path.
    proc = subprocess.run(
        [_node(), str(tmp_path / "harness.js"), str(tmp_path / "snippet.html"), str(tmp_path / "scenarios.json")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return {r["name"]: r for r in json.loads(proc.stdout)}


def _scenarios(rows, clicks=()) -> list[dict]:
    return [
        {"name": name, "hostname": host, "navigator": nav, "window": win, "clicks": list(clicks)}
        for name, host, nav, win in rows
    ]


def _assert_nothing_loaded(result: dict) -> None:
    assert result["dataLayer"] is None, result["name"]
    assert result["appended"] == [], result["name"]
    # Only the footer opt-out control's DOMContentLoaded wiring, never GA's click listener.
    assert result["listeners"] == ["DOMContentLoaded"], result["name"]


def test_snippet_loads_nothing_under_gpc_dnt_or_off_site(tmp_path: Path):
    results = _run_snippet(tmp_path, ga4_head_snippet(TEST_ID, base_url=BASE_URL), _scenarios(_NOT_LOADED))
    assert set(results) == {row[0] for row in _NOT_LOADED}
    for result in results.values():
        _assert_nothing_loaded(result)


def test_snippet_without_a_signal_sets_consent_defaults_config_and_loads_gtag(tmp_path: Path):
    clicks = [_TICKET, _AFFILIATE_TICKET, _WEBCAL, _FEED, _FOOTER_TM, _INTERNAL]
    results = _run_snippet(tmp_path, ga4_head_snippet(TEST_ID, base_url=BASE_URL), _scenarios(_LOADED, clicks))
    assert set(results) == {row[0] for row in _LOADED}
    ad_signals = {"ad_storage": "denied", "ad_user_data": "denied", "ad_personalization": "denied"}
    for name, r in results.items():
        dl = r["dataLayer"]
        assert dl is not None, name
        consent = [entry for entry in dl if entry[0] == "consent"]
        assert [c[1] for c in consent] == ["default", "default"], name
        regional = next(c[2] for c in consent if "region" in c[2])
        everywhere = next(c[2] for c in consent if "region" not in c[2])
        assert set(regional["region"]) == EEA_UK_CH == set(ANALYTICS_DENIED_REGIONS)
        assert len(regional["region"]) == 32
        assert regional == {**ad_signals, "analytics_storage": "denied", "region": regional["region"]}
        assert everywhere == {**ad_signals, "analytics_storage": "granted"}
        # Consent defaults are set before config, so no hit precedes them.
        config_at = next(i for i, entry in enumerate(dl) if entry[0] == "config")
        assert all(i < config_at for i, entry in enumerate(dl) if entry[0] == "consent")
        assert dl[config_at] == [
            "config",
            TEST_ID,
            {"allow_google_signals": False, "allow_ad_personalization_signals": False},
        ]
        assert r["appended"] == [
            {"tag": "script", "async": True, "src": f"https://www.googletagmanager.com/gtag/js?id={TEST_ID}"}
        ]
        assert r["listeners"] == ["DOMContentLoaded", "click"]

        ticket, affiliate, webcal, feed, footer_tm, internal = r["clicks"]
        assert ticket["pushed"] == [
            ["event", "ticket_click", {"link_url": _TICKET["href"], "link_domain": "www.ticketmaster.com"}]
        ]
        assert affiliate["pushed"][0][1] == "ticket_click"
        assert webcal["pushed"] == [["event", "calendar_subscribe", {"link_url": _WEBCAL["href"]}]]
        assert feed["pushed"] == [["event", "calendar_subscribe", {"link_url": _FEED["href"]}]]
        assert footer_tm["pushed"] == [] and internal["pushed"] == []
        for click, link in zip(r["clicks"], clicks, strict=True):
            # Observes only: never cancels the navigation, never rewrites the link.
            assert click["prevented"] is False
            assert click["hrefAfter"] == link["href"]


def test_ticket_click_counts_every_seller_the_buy_links_can_point_at(tmp_path: Path):
    """DECISIONS 0013: "Buy tickets" links now also go to the home team's
    seller (AXS, SeatGeek). The ticket_click matcher is built from
    sellers.ticket_host_names(), so those clicks count too, and a look-alike
    host does not."""

    def link(href: str, host: str) -> dict:
        return {"href": href, "hostname": host, "protocol": "https:", "pathname": "/x", "inMain": True}

    seatgeek = link("https://seatgeek.com/portland-thorns-fc-tickets", "seatgeek.com")
    axs = link("https://www.axs.com/teams/1104736/las-vegas-aces-tickets", "www.axs.com")
    lookalike = link("https://notseatgeek.example/x", "notseatgeek.example")
    results = _run_snippet(
        tmp_path, ga4_head_snippet(TEST_ID, base_url=BASE_URL), _scenarios(_LOADED[:1], [seatgeek, axs, lookalike])
    )
    sg, ax, other = results["no-signal"]["clicks"]
    assert sg["pushed"] == [["event", "ticket_click", {"link_url": seatgeek["href"], "link_domain": "seatgeek.com"}]]
    assert ax["pushed"] == [["event", "ticket_click", {"link_url": axs["href"], "link_domain": "www.axs.com"}]]
    assert other["pushed"] == []


# ---------------------------------------------------------------------------
# 3. Negative controls
# ---------------------------------------------------------------------------


def _sabotage(text: str, old: str, new: str) -> str:
    assert text.count(old) >= 1, f"sabotage target not found: {old!r}"
    sabotaged = text.replace(old, new)
    assert sabotaged != text, "sabotage did not land"
    if old not in new:
        assert old not in sabotaged, "sabotage did not land everywhere"
    return sabotaged


@pytest.mark.parametrize(
    "old,new",
    [
        (GPC_GUARD, ""),
        (DNT_GUARD, ""),
        ("allow_google_signals: false", "allow_google_signals: true"),
        ("<script>", '<script src="https://www.googletagmanager.com/gtag/js"></script>\n<script>'),
    ],
)
def test_control_the_page_checker_rejects_a_broken_tag(old, new):
    html = site.render_privacy(base_url=BASE_URL, ga4_id=TEST_ID)
    _assert_guarded_ga(html, TEST_ID)  # the unbroken page passes
    broken = _sabotage(html, old, new)
    with pytest.raises(AssertionError):
        _assert_guarded_ga(broken, TEST_ID)


def test_control_the_page_checker_rejects_a_page_with_no_tag():
    html = site.render_privacy(base_url=BASE_URL, ga4_id=TEST_ID)
    broken = _sabotage(html, ga4_head_snippet(TEST_ID, base_url=BASE_URL), "")
    assert "<script" not in broken
    with pytest.raises(AssertionError):
        _assert_guarded_ga(broken, TEST_ID)


@pytest.mark.parametrize("guard,scenario", [(GPC_GUARD, "gpc"), (DNT_GUARD, "dnt-navigator")])
def test_control_the_node_harness_sees_ga_load_when_a_guard_is_removed(tmp_path: Path, guard, scenario):
    snippet = _sabotage(ga4_head_snippet(TEST_ID, base_url=BASE_URL), guard, "")
    rows = [row for row in _NOT_LOADED if row[0] == scenario]
    result = _run_snippet(tmp_path, snippet, _scenarios(rows))[scenario]
    assert result["dataLayer"] is not None and result["appended"], "harness missed a removed guard"
    with pytest.raises(AssertionError):
        _assert_nothing_loaded(result)
