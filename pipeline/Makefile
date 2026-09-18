.PHONY: install install-a11y test build verify clean a11y validate-html validate-ics validate-seo validate-fixture-site
.PHONY: lint format-check typecheck markers wheel audit

# Recipes run under bash with errexit, nounset and pipefail. .SHELLFLAGS needs
# GNU make >= 3.82 (CI has 4.x); the make 3.81 that macOS ships ignores it, so
# any recipe with a pipe also says `set -o pipefail` itself.
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

# Every `uv run` / `uv sync` below installs exactly uv.lock and never rewrites
# it (CODE-QUALITY-STANDARD CQ-09). A bare `uv run` silently relocks first,
# which would repair the very drift `install` exists to catch.
export UV_FROZEN := 1

BASE_URL ?= https://nexthomegame.com

# Python only. The nightly deploy (.github/workflows/pages.yml) runs `make
# install`, and it must not need npm, puppeteer, or a ~150MB Chromium
# download to publish the site -- a registry or Chrome-CDN hiccup should
# never be able to block tonight's calendar update.
#
# `uv lock --check` comes first and is the lockfile-drift gate: it exits 1
# when pyproject.toml and uv.lock disagree. `uv sync --frozen` then installs
# exactly the lock (runtime deps plus the PEP 735 `dev` group) -- on its own
# it cannot notice drift, because it never reads pyproject.toml.
install:
	env -u UV_FROZEN uv lock --check
	uv sync --frozen

# npm ci installs pa11y-ci pinned+lockfiled in package.json/package-lock.json
# (the `a11y` target's only JS dependency -- the pipeline itself is pure
# Python) so `make a11y` resolves it from node_modules instead of `npx
# --yes` re-resolving it against the npm registry on every single page, and
# so CI can cache node_modules across runs the same way it already caches
# the uv-managed Python venv. Kept out of `install` so only the a11y gate
# pays for it (see above).
install-a11y:
	npm ci

# Branch coverage with the floor in pyproject.toml ([tool.coverage.report]
# fail_under, CQ-08): pytest exits non-zero below it.
test:
	uv run pytest -q --cov=src --cov-branch --cov-report=term

# CODE-QUALITY-STANDARD §2 / §9 static gates. ruff and mypy read their
# configuration from pyproject.toml; nothing here restates a rule.
lint:
	uv run ruff check .

format-check:
	uv run ruff format --check .

typecheck:
	uv run mypy src

# CQ-34 / CQ-35: no bare TODO/FIXME/HACK and no inline lint/type suppression
# without an issue reference.
markers:
	uv run python scripts/check_markers.py src tests scripts

# CQ-10: the package builds as a wheel with the hatchling backend. Built into
# a throwaway directory -- dist/ is the site output.
wheel:
	tmp=$$(mktemp -d); uv build --wheel --out-dir "$$tmp"; rm -rf "$$tmp"

# CQ-11 / SEC-11: every locked Python dependency against the PyPI/OSV
# advisory databases. No `|| true`: a known vulnerability fails the gate. The
# project itself is skipped because it is not a PyPI distribution.
audit:
	uv run pip-audit --skip-editable

# BUILD_FLAGS is empty for local/CI builds (degraded no-key mode allowed);
# the deploy workflow sets BUILD_FLAGS=--require-api-key.
BUILD_FLAGS ?=

build:
	uv run python -m wsc_pipeline.build --out dist --base-url $(BASE_URL) $(BUILD_FLAGS)

.PHONY: install-perf perf

# Performance, Core Web Vitals lab gate and Lighthouse accessibility score
# (PERFORMANCE-STANDARD §3, OBSERVABILITY-STANDARD §8, ACCESSIBILITY-STANDARD
# A11Y-02), from one config: perf/lighthouse.json. Lighthouse runs against
# the built site on a local server (a separate port from `a11y`), using the
# same Chrome build puppeteer pins for `a11y`, so local and CI measure with
# one browser version. The self-test first proves the budgets reject a page
# with a heavy, blocking script. Regression is checked against the committed
# perf/baseline.json.
PERF_FLAGS ?=

install-perf:
	npm ci --prefix perf --no-audit --no-fund

# bash, not the POSIX /bin/sh CI runners default to (dash has no pipefail).
perf: SHELL := /bin/bash
perf: install install-a11y install-perf build
	set -euo pipefail; \
	rm -rf dist/_a11y-fixtures; \
	uv run python scripts/render_a11y_fixtures.py; \
	CHROME_PATH="$$(node -e 'import("puppeteer").then((p) => console.log(p.default.executablePath()))')"; \
	export CHROME_PATH; \
	python3 -m http.server 8918 --directory dist >/tmp/wsc-perf-server.log 2>&1 & \
	server_pid=$$!; \
	trap 'kill $$server_pid' EXIT; \
	for i in $$(seq 1 20); do \
		curl -sf http://127.0.0.1:8918/style.css > /dev/null 2>&1 && break; \
		sleep 0.25; \
	done; \
	node perf/lighthouse_budgets.mjs --self-test dist http://127.0.0.1:8918; \
	node perf/lighthouse_budgets.mjs http://127.0.0.1:8918 perf/lighthouse.json perf/baseline.json perf/report.json $(PERF_FLAGS)

# Adds `perf` to `verify`; make merges the prerequisites of both `verify` rules.
verify: perf

# html5validator is a pinned dev dependency (pyproject.toml), synced by
# `make install` -- plain `uv run` reuses that venv. It used to be pulled in
# ad hoc via `uv run --with html5validator`, which re-resolves and builds a
# throwaway environment for it on every single invocation (measured at
# ~6s in CI, a real, previously-uncached cost, out of a now ~30s `make
# verify`) instead of reusing the venv `make install` already built. Depends
# on `install` explicitly (the old `--with` form needed no prior setup, so
# this keeps `make validate-html` runnable on its own, not just as part of
# `make verify`).
validate-html: install
	uv run html5validator --root dist

# Every .ics feed the build wrote: exists for each league/team the site
# links, parses as RFC 5545 with the required properties, no duplicate
# UIDs, and carries exactly the games its page shows as in the feed. Run
# by `make verify` and, against the real fetched build, by pages.yml
# before deploy -- see src/wsc_pipeline/validate_ics.py.
validate-ics:
	uv run python -m wsc_pipeline.validate_ics dist

# What search engines read: robots.txt, a sitemap that lists exactly the
# built pages with truthful <lastmod> dates, one title/description/H1 and a
# self-canonical per page, and structured data that says no more than the
# page's own data -- no SportsEvent for a date- or time-TBD game, none on a
# build that fetched nothing. Run by `make verify` and, against the real
# fetched build, by pages.yml before deploy -- see
# src/wsc_pipeline/validate_seo.py.
validate-seo:
	uv run python -m wsc_pipeline.validate_seo dist

# The same HTML, feed and structured-data validators on a populated site.
# `make verify`'s own build has no Ticketmaster key, so its pages never carry
# a game, a next-game hero, a fetch time or a SportsEvent, and a validator
# that only ever sees that build cannot fail on any of them (the 2026-09-18
# nightly deploy failed validate-html on a fetch time no CI build had
# printed). scripts/build_fixture_site.py runs the real build over canned
# Ticketmaster listings (tests/fixture_site.py) into dist-fixture/.
validate-fixture-site: install
	rm -rf dist-fixture
	uv run python scripts/build_fixture_site.py dist-fixture
	uv run html5validator --root dist-fixture
	uv run python -m wsc_pipeline.validate_ics dist-fixture
	uv run python -m wsc_pipeline.validate_seo dist-fixture

# Real, CI-enforced accessibility gate -- runs pa11y (WCAG2AA) against every
# HTML page the build actually produced (index, league pages, team pages),
# not a one-time manual check. Requires Node/npx (see .github/workflows/ci.yml).
# Runs through pa11y-ci rather than one `npx pa11y` process per page: same
# pa11y engine, same WCAG2AA standard, same --no-sandbox Chrome launch config
# (all in pa11y-ci.config.json), just fanned out with real concurrency
# instead of a serial loop -- each page is independent of every other page,
# so this was always embarrassingly parallel. Concurrency is 5, tuned for
# GitHub-hosted runners' 4 vCPUs; bump pa11y-ci.config.json's
# defaults.concurrency if this ever runs somewhere with more cores.
# Also renders and checks the two populated-games-table pages (priced +
# unpriced + date-TBD game together) that a degraded, no-key build never
# produces -- see scripts/render_a11y_fixtures.py.
#
# Pages are checked over a real local HTTP server (127.0.0.1), not as raw
# file:// paths: every page links style.css/fonts/favicon with a
# root-absolute path ("/style.css"), which a browser resolves against the
# filesystem root (not the page's own folder) under file://, so pa11y would
# silently check unstyled, default-browser-styled markup -- passing on any
# palette/contrast choice, real or broken, because none of this site's own
# CSS ever loaded. Serving dist/ at an HTTP root is also what really
# happens in production (GitHub Pages), so this is the more faithful check,
# not just a workaround. pa11y-ci's own URL list is built from that same
# server, not passed as file globs, so this stays correct.
#
# pa11y-ci.config.json sets useIncognitoBrowserContext: false -- measured
# during this fix, the default (true) makes concurrent runs intermittently
# throw "Protocol error (Target.closeTarget): No target with given id
# found" on an otherwise-clean page (a pa11y-ci/puppeteer race creating and
# tearing down incognito contexts under concurrency, not a real a11y
# failure) -- false makes every page share plain browser tabs instead, which
# was reliable across repeated full runs against every page in dist/.
#
# A faster sweep that quietly checks fewer pages would be a regression, not
# a speedup, so the next step refuses to pass unless pa11y-ci's own JSON
# report (pa11y-ci-results.json) names exactly the URLs handed to it, all
# passing, and that URL list covers every page the site config says the
# build must produce -- see scripts/check_a11y_coverage.py.
#
# pa11y-ci runs both the HTML_CodeSniffer and axe runners. axe results that
# axe itself marks "needs review" (it could not compute a background behind
# a pseudo-element, say) are capped at warning: they are logged, and each
# kind is recorded with a measured value in docs/a11y/README.md.
#
# Then scripts/a11y_browser_checks.mjs runs what pa11y cannot: axe at
# moderate and above as a hard failure, a keyboard walk of every tab stop,
# 320 px reflow and reduced motion (ACCESSIBILITY-STANDARD A11Y-01/05/06/07/
# 08/09/26), on the same URL list. Its --self-test first plants one defect
# per check in a copy of a fixture page and fails unless each is caught;
# scripts/check_a11y_browser_report.py then refuses a report that skipped
# a page or examined nothing on one.
a11y: install install-a11y build
	set -e; \
	rm -rf dist/_a11y-fixtures pa11y-ci-results.json a11y-browser-results.json; \
	uv run python scripts/render_a11y_fixtures.py; \
	python3 -m http.server 8917 --directory dist >/tmp/wsc-a11y-server.log 2>&1 & \
	server_pid=$$!; \
	trap "kill $$server_pid 2>/dev/null || true" EXIT; \
	for i in $$(seq 1 20); do \
		curl -sf http://127.0.0.1:8917/style.css > /dev/null 2>&1 && break; \
		sleep 0.25; \
	done; \
	urls=""; \
	for f in $$(find dist -name '*.html' | sort); do \
		urls="$$urls http://127.0.0.1:8917/$${f#dist/}"; \
	done; \
	./node_modules/.bin/pa11y-ci --config pa11y-ci.config.json $$urls; \
	uv run python scripts/check_a11y_coverage.py pa11y-ci-results.json $$urls; \
	node scripts/a11y_browser_checks.mjs --self-test http://127.0.0.1:8917/_a11y-fixtures/team.html; \
	node scripts/a11y_browser_checks.mjs a11y-browser-results.json $$urls; \
	uv run python scripts/check_a11y_browser_report.py a11y-browser-results.json $$urls

verify: install lint format-check typecheck markers test wheel build validate-html validate-ics validate-seo validate-fixture-site a11y audit

clean:
	rm -rf dist dist.tmp dist-fixture .pytest_cache .venv node_modules pa11y-ci-results.json a11y-browser-results.json
