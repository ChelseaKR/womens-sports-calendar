.PHONY: install test build verify clean a11y

BASE_URL ?= https://nexthomegame.com

install:
	uv sync --extra dev

test:
	uv run pytest -q

build:
	uv run python -m wsc_pipeline.build --out dist --base-url $(BASE_URL)

validate-html:
	uv run --with html5validator html5validator --root dist

# Real, CI-enforced accessibility gate -- runs pa11y (WCAG2AA) against every
# HTML page the build actually produced (index, league pages, team pages),
# not a one-time manual check. Requires Node/npx (see .github/workflows/ci.yml).
# `pa11y.config.json` launches Chrome with --no-sandbox, which CI runners need.
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
# not just a workaround.
a11y: install build
	set -e; \
	rm -rf dist/_a11y-fixtures; \
	uv run python scripts/render_a11y_fixtures.py; \
	python3 -m http.server 8917 --directory dist >/tmp/wsc-a11y-server.log 2>&1 & \
	server_pid=$$!; \
	trap "kill $$server_pid 2>/dev/null || true" EXIT; \
	for i in $$(seq 1 20); do \
		curl -sf http://127.0.0.1:8917/style.css > /dev/null 2>&1 && break; \
		sleep 0.25; \
	done; \
	for f in $$(find dist -name '*.html' | sort); do \
		url="http://127.0.0.1:8917/$${f#dist/}"; \
		echo "== pa11y --standard WCAG2AA: $$url =="; \
		npx --yes pa11y --standard WCAG2AA --config pa11y.config.json "$$url"; \
	done

verify: install test build validate-html a11y

clean:
	rm -rf dist dist.tmp .pytest_cache .venv
