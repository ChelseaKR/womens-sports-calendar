.PHONY: install install-a11y test build verify clean a11y

BASE_URL ?= https://nexthomegame.com

# Python only. The nightly deploy (.github/workflows/pages.yml) runs `make
# install`, and it must not need npm, puppeteer, or a ~150MB Chromium
# download to publish the site -- a registry or Chrome-CDN hiccup should
# never be able to block tonight's calendar update.
install:
	uv sync --extra dev

# npm ci installs pa11y-ci pinned+lockfiled in package.json/package-lock.json
# (the `a11y` target's only JS dependency -- the pipeline itself is pure
# Python) so `make a11y` resolves it from node_modules instead of `npx
# --yes` re-resolving it against the npm registry on every single page, and
# so CI can cache node_modules across runs the same way it already caches
# the uv-managed Python venv. Kept out of `install` so only the a11y gate
# pays for it (see above).
install-a11y:
	npm ci

test:
	uv run pytest -q

# BUILD_FLAGS is empty for local/CI builds (degraded no-key mode allowed);
# the deploy workflow sets BUILD_FLAGS=--require-api-key.
BUILD_FLAGS ?=

build:
	uv run python -m wsc_pipeline.build --out dist --base-url $(BASE_URL) $(BUILD_FLAGS)

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
# a speedup, so the last step refuses to pass unless pa11y-ci's own JSON
# report (pa11y-ci-results.json) names exactly the URLs handed to it, all
# passing, and that URL list covers every page the site config says the
# build must produce -- see scripts/check_a11y_coverage.py.
a11y: install install-a11y build
	set -e; \
	rm -rf dist/_a11y-fixtures pa11y-ci-results.json; \
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
	uv run python scripts/check_a11y_coverage.py pa11y-ci-results.json $$urls

verify: install test build validate-html validate-ics a11y

clean:
	rm -rf dist dist.tmp .pytest_cache .venv node_modules pa11y-ci-results.json
