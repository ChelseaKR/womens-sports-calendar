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
a11y: install build
	set -e; \
	for f in $$(find dist -name '*.html' | sort); do \
		echo "== pa11y --standard WCAG2AA: $$f =="; \
		npx --yes pa11y --standard WCAG2AA --config pa11y.config.json "$$f"; \
	done; \
	rm -rf dist-a11y-fixtures; \
	uv run python scripts/render_a11y_fixtures.py; \
	for f in dist-a11y-fixtures/league.html dist-a11y-fixtures/team.html; do \
		echo "== pa11y --standard WCAG2AA (populated games table): $$f =="; \
		npx --yes pa11y --standard WCAG2AA --config pa11y.config.json "$$f"; \
	done

verify: install test build validate-html a11y

clean:
	rm -rf dist dist.tmp dist-a11y-fixtures .pytest_cache .venv
