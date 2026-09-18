"""sitemap.xml lastmod (sitemap.py): when a page's schedule last changed, from
the live site's own lastmod.json -- never the build time -- plus robots.txt
and the validator's sitemap checks."""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from wsc_pipeline import build as build_module
from wsc_pipeline import site, sitemap, validate_seo
from wsc_pipeline.normalize import display_date

from .conftest import REAL_FETCH_PREVIOUS_STATE
from .fixture_site import (
    BASE_URL,
    CHANGED_PAGE,
    NEW_PAGE,
    PREVIOUS_CHANGED_AT,
    UNCHANGED_PAGE,
    build_fixture_site,
    build_fixture_site_with_history,
)

NOW = datetime(2026, 9, 18, 8, 31, 30, tzinfo=UTC)
LOC_RE = re.compile(r"<url><loc>([^<]+)</loc>(?:<lastmod>([^<]+)</lastmod>)?</url>")


def _lastmods(dist: Path) -> dict[str, str | None]:
    text = (dist / "sitemap.xml").read_text()
    return {loc[len(BASE_URL) :]: lastmod or None for loc, lastmod in LOC_RE.findall(text)}


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------


def test_no_history_means_no_dates_never_the_build_time():
    state = sitemap.next_state({"/a/": "sha256:1", "/b/": "sha256:2"}, None, NOW)
    assert {p: s.changed_at for p, s in state.items()} == {"/a/": None, "/b/": None}


def test_a_build_that_fetched_nothing_records_no_dates_even_with_history():
    previous = {"/a/": sitemap.PageState("sha256:0", "2026-09-01T08:00:00+00:00")}
    state = sitemap.next_state({"/a/": "sha256:1"}, previous, None)
    assert state["/a/"].changed_at is None


def test_unchanged_carries_over_changed_and_new_pages_take_this_fetch_time():
    previous = {
        "/same/": sitemap.PageState("sha256:s", "2026-09-01T08:00:00+00:00"),
        "/same-unknown/": sitemap.PageState("sha256:u", None),
        "/changed/": sitemap.PageState("sha256:old", "2026-09-01T08:00:00+00:00"),
        "/gone/": sitemap.PageState("sha256:g", "2026-09-01T08:00:00+00:00"),
    }
    current = {"/same/": "sha256:s", "/same-unknown/": "sha256:u", "/changed/": "sha256:new", "/new/": "sha256:n"}
    state = sitemap.next_state(current, previous, NOW)
    assert {p: s.changed_at for p, s in state.items()} == {
        "/same/": "2026-09-01T08:00:00+00:00",
        "/same-unknown/": None,
        "/changed/": NOW.isoformat(),
        "/new/": NOW.isoformat(),
    }


def test_the_fingerprint_ignores_when_the_listings_were_fetched():
    payload = {"games": [{"event_id": "E1"}], "fetched": True}
    a = sitemap.fingerprint({**payload, "fetched_at": "2026-09-17T08:31:00+00:00", "source": "x"})
    b = sitemap.fingerprint({**payload, "fetched_at": "2026-09-18T08:31:00+00:00", "source": "x"})
    assert a == b
    assert a != sitemap.fingerprint({**payload, "games": [{"event_id": "E2"}]})


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        {"schema": 2, "pages": {}},
        {"schema": 1},
        {"schema": 1, "pages": {"/a/": {"fingerprint": 1, "changed_at": None}}},
        {"schema": 1, "pages": {"/a/": {"fingerprint": "sha256:x", "changed_at": "yesterday"}}},
        {"schema": 1, "pages": {"/a/": {"fingerprint": "sha256:x", "changed_at": "2026-09-18T08:00:00"}}},
    ],
)
def test_a_malformed_manifest_is_no_history(body):
    assert sitemap.parse_state(body) is None


def test_the_manifest_round_trips():
    state = {
        "/a/": sitemap.PageState("sha256:x", "2026-09-18T08:31:30+00:00"),
        "/b/": sitemap.PageState("sha256:y", None),
    }
    assert sitemap.parse_state(json.loads(sitemap.render_state(state))) == state


# ---------------------------------------------------------------------------
# Reading the live manifest: never raises, never trusts a bad body
# ---------------------------------------------------------------------------


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_reads_the_live_manifest(capsys):
    body = sitemap.render_state({"/a/": sitemap.PageState("sha256:x", "2026-09-18T08:31:30+00:00")})

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == f"{BASE_URL}/lastmod.json"
        return httpx.Response(200, text=body)

    state = REAL_FETCH_PREVIOUS_STATE(BASE_URL, client=_client(handler))
    assert state == {"/a/": sitemap.PageState("sha256:x", "2026-09-18T08:31:30+00:00")}


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404, text="Not found"),
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, text='{"schema": 1, "pages": "nope"}'),
    ],
)
def test_an_unreadable_live_manifest_is_no_history(response, capsys):
    assert REAL_FETCH_PREVIOUS_STATE(BASE_URL, client=_client(lambda request: response)) is None
    assert "start unknown" in capsys.readouterr().err


def test_a_network_failure_is_no_history_not_a_failed_build(capsys):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    assert REAL_FETCH_PREVIOUS_STATE(BASE_URL, client=_client(handler)) is None
    assert "could not read" in capsys.readouterr().err


def test_main_reads_the_live_manifest_only_for_a_build_that_fetches(tmp_path: Path, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(sitemap, "fetch_previous_state", lambda base_url, **kw: calls.append(base_url))
    monkeypatch.delenv("TICKETMASTER_API_KEY", raising=False)
    assert build_module.main(["--out", str(tmp_path / "a"), "--base-url", BASE_URL]) == 0
    assert calls == []
    monkeypatch.setenv("TICKETMASTER_API_KEY", "fake-key")

    def stop(api_key: str):
        raise RuntimeError("stop")

    monkeypatch.setattr(build_module, "fetch_all_games", stop)
    with pytest.raises(RuntimeError, match="stop"):
        build_module.main(["--out", str(tmp_path / "b"), "--base-url", BASE_URL])
    assert calls == [BASE_URL]


# ---------------------------------------------------------------------------
# End to end, on built sites
# ---------------------------------------------------------------------------


def test_sitemap_dates_follow_the_previous_live_manifest(tmp_path: Path):
    dist = tmp_path / "dist"
    build_fixture_site_with_history(dist)
    lastmods = _lastmods(dist)
    fetched_at = json.loads((dist / "version.json").read_text())["fetched_at"]
    assert lastmods[UNCHANGED_PAGE] == PREVIOUS_CHANGED_AT  # carried over
    assert lastmods[CHANGED_PAGE] == fetched_at  # its content changed
    assert lastmods[NEW_PAGE] == fetched_at  # the previous site did not have it
    assert lastmods["/nwsl/"] is None  # unchanged, and never dated before
    # Privacy and accessibility: the date printed on each page.
    assert lastmods[site.PRIVACY_PATH] == site.PRIVACY_UPDATED.isoformat()
    assert lastmods[site.ACCESSIBILITY_PATH] == site.ACCESSIBILITY_UPDATED.isoformat()
    assert f"Updated {display_date(site.PRIVACY_UPDATED)}." in (dist / "privacy/index.html").read_text()
    assert f"Updated {display_date(site.ACCESSIBILITY_UPDATED)}." in (dist / "accessibility/index.html").read_text()
    assert validate_seo.validate_dist(dist)


def test_rebuilding_unchanged_listings_moves_no_date(tmp_path: Path):
    first = tmp_path / "first"
    build_fixture_site(first)
    state = sitemap.parse_state(json.loads((first / sitemap.STATE_PATH).read_text()))
    assert state is not None
    dated = {p: sitemap.PageState(s.fingerprint, PREVIOUS_CHANGED_AT) for p, s in state.items()}
    second = tmp_path / "second"
    build_fixture_site(second, previous_state=dated)
    for path, lastmod in _lastmods(second).items():
        if path in dated:
            assert lastmod == PREVIOUS_CHANGED_AT, path


def test_sitemap_lists_every_indexable_page_and_not_the_404(tmp_path: Path):
    dist = tmp_path / "dist"
    build_module.build(out_dir=dist, base_url=BASE_URL, api_key=None, affiliate_id=None)
    paths = set(_lastmods(dist))
    assert "/" in paths and "/privacy/" in paths and "/wnba/las-vegas-aces/" in paths
    assert not any("404" in p for p in paths)
    assert (dist / "robots.txt").read_text() == f"User-agent: *\nAllow: /\n\nSitemap: {BASE_URL}/sitemap.xml\n"
    # A degraded build dates no schedule page at all.
    assert {p: m for p, m in _lastmods(dist).items() if m} == {
        site.PRIVACY_PATH: site.PRIVACY_UPDATED.isoformat(),
        site.ACCESSIBILITY_PATH: site.ACCESSIBILITY_UPDATED.isoformat(),
    }


# ---------------------------------------------------------------------------
# Controls: the validator's sitemap checks can fail
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def history_dist(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("history") / "dist"
    build_fixture_site_with_history(out)
    return out


def _corrupt(src: Path, dst: Path, rel: str, old: str, new: str) -> Path:
    shutil.copytree(src, dst)
    path = dst / rel
    text = path.read_text()
    assert old in text, f"sabotage target not found: {old!r}"
    path.write_text(text.replace(old, new, 1))
    assert path.read_text() != text
    return dst


@pytest.mark.parametrize(
    "rel,old,new,match",
    [
        ("robots.txt", "Allow: /", "Disallow: /", "disallows"),
        ("robots.txt", "Sitemap:", "Sitemaps:", "does not name"),
        ("sitemap.xml", f"<url><loc>{BASE_URL}/ausl/</loc></url>\n", "", "disagree"),
        (
            "sitemap.xml",
            f"<lastmod>{PREVIOUS_CHANGED_AT}</lastmod>",
            "<lastmod>2026-09-01T00:00:00+00:00</lastmod>",
            "disagrees with lastmod.json",
        ),
        (
            "sitemap.xml",
            f"<loc>{BASE_URL}/ausl/</loc>",
            f"<loc>{BASE_URL}/ausl/</loc><lastmod>2026-09-01</lastmod>",
            "disagrees",
        ),
        ("sitemap.xml", "<lastmod>2026-09-17</lastmod>", "<lastmod>17 Sep 2026</lastmod>", "not a W3C date"),
        ("sitemap.xml", "<lastmod>2026-09-17</lastmod>", "<lastmod>2099-01-01</lastmod>", "in the future"),
        ("sitemap.xml", "</urlset>", "<url>", "not well-formed"),
    ],
)
def test_control_a_corrupted_sitemap_or_robots_fails(history_dist: Path, tmp_path: Path, rel, old, new, match):
    dist = _corrupt(history_dist, tmp_path / "dist", rel, old, new)
    with pytest.raises(validate_seo.SeoError, match=re.escape(match)):
        validate_seo.validate_dist(dist)


def test_control_a_404_in_the_sitemap_fails(history_dist: Path, tmp_path: Path):
    dist = tmp_path / "dist"
    shutil.copytree(history_dist, dist)
    (dist / "gone").mkdir()
    shutil.copyfile(dist / "404.html", dist / "gone" / "index.html")
    sm = dist / "sitemap.xml"
    sm.write_text(sm.read_text().replace("</urlset>", f"  <url><loc>{BASE_URL}/gone/</loc></url>\n</urlset>"))
    with pytest.raises(validate_seo.SeoError, match="noindex page"):
        validate_seo.validate_dist(dist)
