"""The footer's "Opt out of analytics" choice (owner decision 2026-09-18,
DECISIONS 0012 addendum): remembered per browser in localStorage, checked
before gtag.js is requested, toggling to "Opt back in", and described on
/privacy/.

The GA4 loader is executed in Node against stubbed window / navigator /
document / localStorage objects (the same approach as test_analytics.py),
so "the flag stops GA from loading" is observed, not inferred from the
markup. Each negative control first asserts its sabotage landed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from wsc_pipeline import build as build_module
from wsc_pipeline import site
from wsc_pipeline.analytics import OPT_OUT_MESSAGES, OPT_OUT_STORAGE_KEY, ga4_head_snippet

TEST_ID = "G-TEST123456"
BASE_URL = "https://nexthomegame.com"
HOST = "nexthomegame.com"
KEY = OPT_OUT_STORAGE_KEY
GA_DISABLE = f"ga-disable-{TEST_ID}"
OPT_OUT_GUARD = "if (optedOut()) return;"

_HARNESS = r"""
const vm = require("vm");
const fs = require("fs");
const [snippetPath, scenariosPath] = process.argv.slice(2);
const code = fs.readFileSync(snippetPath, "utf8").replace(/^\s*<script>/, "").replace(/<\/script>\s*$/, "");
const scenarios = JSON.parse(fs.readFileSync(scenariosPath, "utf8"));
const out = scenarios.map((sc) => {
  const appended = [];
  const docListeners = {};
  const button = {
    hidden: false, textContent: "Opt out of analytics", listeners: {},
    addEventListener(type, fn) { this.listeners[type] = fn; },
  };
  const status = { textContent: "" };
  const box = {
    hidden: true,
    querySelector: (sel) => (sel === "button" ? button : sel === "[role=status]" ? status : null),
  };
  const ctx = {
    navigator: Object.assign({}, sc.navigator),
    location: { hostname: sc.hostname },
    document: {
      head: { appendChild: (el) => appended.push(el) },
      createElement: (tag) => ({ tag }),
      addEventListener: (type, fn) => { docListeners[type] = fn; },
      querySelector: (sel) => (sel === "[data-analytics-choice]" ? box : null),
    },
    Date,
  };
  let data = null;
  if (sc.storage === "throw") {
    Object.defineProperty(ctx, "localStorage", { get() { throw new Error("SecurityError"); } });
  } else if (sc.storage) {
    data = Object.assign({}, sc.storage);
    ctx.localStorage = {
      getItem: (k) => (Object.prototype.hasOwnProperty.call(data, k) ? data[k] : null),
      setItem: (k, v) => { if (sc.setItemThrows) throw new Error("QuotaExceededError"); data[k] = String(v); },
      removeItem: (k) => { delete data[k]; },
    };
  }
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  const loaded = {
    dataLayer: ctx.dataLayer ? ctx.dataLayer.length : null,
    appended: appended.map((el) => el.src || el.tag),
    gaClickListener: Object.prototype.hasOwnProperty.call(docListeners, "click"),
  };
  const snap = () => ({
    boxHidden: box.hidden,
    buttonHidden: button.hidden,
    label: button.textContent,
    status: status.textContent,
    flag: data && Object.prototype.hasOwnProperty.call(data, sc.key) ? data[sc.key] : null,
    gaDisable: Object.prototype.hasOwnProperty.call(ctx, sc.disable) ? ctx[sc.disable] : null,
  });
  const ui = [];
  if (docListeners.DOMContentLoaded) {
    docListeners.DOMContentLoaded();
    ui.push(snap());
    for (let i = 0; i < (sc.toggles || 0); i++) {
      button.listeners.click();
      ui.push(snap());
    }
  }
  return { name: sc.name, loaded, ui };
});
process.stdout.write(JSON.stringify(out));
"""


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("node is required in CI to execute the GA4 snippet (ci.yml sets it up)")
        pytest.skip("node not installed; this behaviour test runs in CI")
    return node


def _run(tmp_path: Path, scenarios: list[dict], snippet: str | None = None) -> dict[str, dict]:
    snippet = ga4_head_snippet(TEST_ID, base_url=BASE_URL) if snippet is None else snippet
    for sc in scenarios:
        sc.setdefault("hostname", HOST)
        sc.setdefault("navigator", {})
        sc.update(key=KEY, disable=GA_DISABLE)
    (tmp_path / "harness.js").write_text(_HARNESS, encoding="utf-8")
    (tmp_path / "snippet.html").write_text(snippet, encoding="utf-8")
    (tmp_path / "scenarios.json").write_text(json.dumps(scenarios), encoding="utf-8")
    # node plus three files this test just wrote into its own tmp_path.
    proc = subprocess.run(  # noqa: S603
        [_node(), str(tmp_path / "harness.js"), str(tmp_path / "snippet.html"), str(tmp_path / "scenarios.json")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return {r["name"]: r for r in json.loads(proc.stdout)}


def _assert_not_loaded(result: dict) -> None:
    assert result["loaded"] == {"dataLayer": None, "appended": [], "gaClickListener": False}, result["name"]


def _assert_loaded(result: dict) -> None:
    loaded = result["loaded"]
    assert loaded["dataLayer"], result["name"]
    assert loaded["appended"] == [f"https://www.googletagmanager.com/gtag/js?id={TEST_ID}"], result["name"]
    assert loaded["gaClickListener"] is True, result["name"]


# ---------------------------------------------------------------------------
# The flag stops GA from loading
# ---------------------------------------------------------------------------


def test_the_opt_out_flag_stops_ga_from_loading(tmp_path: Path):
    results = _run(
        tmp_path,
        [
            {"name": "opted-out", "storage": {KEY: "1"}},
            {"name": "never-chosen", "storage": {}},
            {"name": "other-value", "storage": {KEY: "0"}},
            {"name": "other-key", "storage": {"something-else": "1"}},
            {"name": "storage-blocked", "storage": "throw"},
        ],
    )
    _assert_not_loaded(results["opted-out"])
    for name in ("never-chosen", "other-value", "other-key", "storage-blocked"):
        _assert_loaded(results[name])


def test_the_flag_is_checked_before_gtag_on_every_page(tmp_path: Path):
    out_dir = tmp_path / "dist"
    build_module.build(out_dir=out_dir, base_url=BASE_URL, api_key=None, affiliate_id=None, ga4_id=TEST_ID)
    pages = {str(p.relative_to(out_dir)): p.read_text(encoding="utf-8") for p in out_dir.rglob("*.html")}
    assert len(pages) > 70
    for path, html in pages.items():
        script = re.search(r"<script>.*?</script>", html, flags=re.DOTALL).group(0)
        assert OPT_OUT_GUARD in script, path
        assert script.index(OPT_OUT_GUARD) < script.index("w.dataLayer"), path
        assert script.index(OPT_OUT_GUARD) < script.index("createElement"), path
        assert html.count(site.ANALYTICS_CHOICE) == 1, path
        assert html.index(site.ANALYTICS_CHOICE) > html.index('<footer class="site-footer">'), path


def test_no_id_means_no_opt_out_control_either(tmp_path: Path):
    out_dir = tmp_path / "dist"
    build_module.build(out_dir=out_dir, base_url=BASE_URL, api_key=None, affiliate_id=None, ga4_id=None)
    for path in out_dir.rglob("*.html"):
        html = path.read_text(encoding="utf-8")
        assert "data-analytics-choice" not in html, path
        assert "Opt out of analytics" not in html, path


def test_privacy_page_describes_the_opt_out():
    html = site.render_privacy(base_url=BASE_URL, ga4_id=TEST_ID)
    assert "<strong>Opt out on this device.</strong>" in html
    assert "local storage (not a cookie)" in html
    assert "&ldquo;Opt back in&rdquo;" in html
    assert "doesn't load Google Analytics in this browser at all" in html


# ---------------------------------------------------------------------------
# The footer control
# ---------------------------------------------------------------------------


def test_the_footer_control_opts_out_and_back_in(tmp_path: Path):
    results = _run(
        tmp_path,
        [
            {"name": "fresh", "storage": {}, "toggles": 2},
            {"name": "next-page-after-opting-out", "storage": {KEY: "1"}},
        ],
    )
    start, out, back_in = results["fresh"]["ui"]
    assert start == {
        "boxHidden": False,
        "buttonHidden": False,
        "label": "Opt out of analytics",
        "status": "",
        "flag": None,
        "gaDisable": None,
    }
    assert out == {
        "boxHidden": False,
        "buttonHidden": False,
        "label": "Opt back in",
        "status": OPT_OUT_MESSAGES["__MSG_OPTED_OUT__"],
        "flag": "1",
        "gaDisable": True,
    }
    assert back_in == {
        "boxHidden": False,
        "buttonHidden": False,
        "label": "Opt out of analytics",
        "status": OPT_OUT_MESSAGES["__MSG_BACK_IN__"],
        "flag": None,
        "gaDisable": False,
    }
    later = results["next-page-after-opting-out"]
    _assert_not_loaded(later)
    assert later["ui"] == [
        {
            "boxHidden": False,
            "buttonHidden": False,
            "label": "Opt back in",
            "status": OPT_OUT_MESSAGES["__MSG_IS_OUT__"],
            "flag": "1",
            "gaDisable": None,
        }
    ]


def test_under_gpc_or_dnt_the_control_says_analytics_is_already_off(tmp_path: Path):
    results = _run(
        tmp_path,
        [
            {"name": "gpc", "storage": {}, "navigator": {"globalPrivacyControl": True}},
            {"name": "dnt", "storage": {}, "navigator": {"doNotTrack": "1"}},
        ],
    )
    for result in results.values():
        _assert_not_loaded(result)
        (ui,) = result["ui"]
        assert ui["boxHidden"] is False and ui["buttonHidden"] is True, result["name"]
        assert ui["status"] == OPT_OUT_MESSAGES["__MSG_SIGNAL__"], result["name"]


def test_blocked_storage_hides_the_button_and_says_why(tmp_path: Path):
    results = _run(
        tmp_path,
        [
            {"name": "getter-throws", "storage": "throw"},
            {"name": "setitem-throws", "storage": {}, "setItemThrows": True, "toggles": 1},
        ],
    )
    (ui,) = results["getter-throws"]["ui"]
    assert ui["buttonHidden"] is True and ui["status"] == OPT_OUT_MESSAGES["__MSG_NO_STORAGE__"]
    before, after = results["setitem-throws"]["ui"]
    assert before["buttonHidden"] is False
    assert after["buttonHidden"] is True and after["status"] == OPT_OUT_MESSAGES["__MSG_NO_STORAGE__"]
    assert after["flag"] is None


def test_the_control_is_wired_off_the_production_host_so_pa11y_checks_it(tmp_path: Path):
    """CI's pa11y sweep serves dist/ on 127.0.0.1, where GA never loads; the
    control must still be revealed there, or the sweep would only ever
    check a hidden element."""
    result = _run(tmp_path, [{"name": "local", "hostname": "127.0.0.1", "storage": {}}])["local"]
    _assert_not_loaded(result)
    (ui,) = result["ui"]
    assert ui["boxHidden"] is False and ui["buttonHidden"] is False
    assert ui["label"] == "Opt out of analytics"


# ---------------------------------------------------------------------------
# Negative controls
# ---------------------------------------------------------------------------


def _sabotage(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, f"sabotage target occurs {text.count(old)}x: {old!r}"
    sabotaged = text.replace(old, new)
    assert sabotaged != text and old not in sabotaged, "sabotage did not land"
    return sabotaged


def test_control_the_harness_sees_ga_load_when_the_flag_check_is_removed(tmp_path: Path):
    snippet = _sabotage(ga4_head_snippet(TEST_ID, base_url=BASE_URL), OPT_OUT_GUARD, "")
    result = _run(tmp_path, [{"name": "opted-out", "storage": {KEY: "1"}}], snippet=snippet)["opted-out"]
    _assert_loaded(result)
    with pytest.raises(AssertionError):
        _assert_not_loaded(result)


def test_control_the_harness_sees_a_toggle_that_forgets_to_store(tmp_path: Path):
    snippet = _sabotage(ga4_head_snippet(TEST_ID, base_url=BASE_URL), 'store.setItem(KEY, "1");', "")
    _, out = _run(tmp_path, [{"name": "fresh", "storage": {}, "toggles": 1}], snippet=snippet)["fresh"]["ui"]
    assert out["flag"] is None, "sabotaged toggle still stored the flag"
    assert out["label"] == "Opt out of analytics"
