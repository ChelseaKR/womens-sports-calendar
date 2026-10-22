"""IndexNow on the populated fixture build and in the pages workflow.

The key file is in the build root, every sitemap URL is announceable (own
host, built, indexable), robots.txt lets Bingbot in and names the sitemap, a
changed page fingerprint is what selects a page, and the workflow selects
before the deploy replaces the live site and submits only after it."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from wsc_pipeline import indexnow as ix
from wsc_pipeline import sitemap

from .fixture_site import BASE_URL, CHANGED_PAGE, NEW_PAGE, build_fixture_site, previous_state_for

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pages.yml"


@pytest.fixture(scope="module")
def site_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("ixfixture") / "dist"
    build_fixture_site(out)
    return out


def test_the_build_carries_exactly_one_matching_key_file(site_dir):
    key = ix.find_key(site_dir)
    assert (site_dir / f"{key}.txt").read_text(encoding="utf-8").strip() == key


def test_robots_allows_bingbot_and_lists_the_sitemap(site_dir):
    assert ix.check_robots((site_dir / "robots.txt").read_text(encoding="utf-8"), BASE_URL) == []


def test_every_sitemap_url_is_announceable_and_the_404_is_not_listed(site_dir):
    entries = ix.parse_sitemap((site_dir / "sitemap.xml").read_text(encoding="utf-8"))
    assert len(entries) > 10
    kept, notes = ix.filter_submittable(sorted(entries), base_url=BASE_URL, site_dir=site_dir)
    assert notes == []
    assert kept == sorted(entries)
    noindexed = [p for p in site_dir.rglob("*.html") if ix.is_noindex(p.read_text(encoding="utf-8", errors="replace"))]
    assert noindexed, "the build has no noindex page, so this check proves nothing"
    for p in noindexed:
        rel = p.relative_to(site_dir).as_posix().removesuffix("index.html")
        assert f"{BASE_URL}/{rel}" not in entries


def test_the_repos_own_yesterday_manifest_selects_the_changed_and_the_new_page(site_dir):
    text = (site_dir / sitemap.STATE_PATH).read_text(encoding="utf-8")
    manifest = sitemap.parse_state(json.loads(text))
    assert manifest is not None
    current = ix.tokens("manifest", text, BASE_URL)
    previous_state = previous_state_for(manifest)
    previous = {BASE_URL + p: st.fingerprint for p, st in previous_state.items()}
    assert previous != current  # the sabotage applied
    assert ix.select_changed(previous, current) == sorted([BASE_URL + CHANGED_PAGE, BASE_URL + NEW_PAGE])
    assert ix.select_changed(current, current) == []


def _jobs() -> dict[str, str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    body = text[text.index("\njobs:\n") :]
    parts = re.split(r"\n  (?=[a-z-]+:\n)", body)
    return {p.split(":", 1)[0]: p for p in parts[1:]}


def test_workflow_selects_in_build_and_submits_in_a_job_after_deploy():
    jobs = _jobs()
    assert {"build", "deploy", "indexnow"} <= set(jobs)
    build, deploy, job = jobs["build"], jobs["deploy"], jobs["indexnow"]
    assert "indexnow select" in build
    assert build.index("make validate-seo") < build.index("indexnow select") < build.index("Upload the built site")
    assert "indexnow select" not in deploy and "indexnow submit" not in deploy
    assert "needs: deploy" in job
    assert "wsc_pipeline/indexnow.py submit" in job
    assert "secrets." not in job
    assert "continue-on-error: true" in job
    assert "contents: read" in job


def test_workflow_never_runs_from_pull_request_ci():
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "indexnow" not in ci
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request" not in text.split("\njobs:\n")[0]
