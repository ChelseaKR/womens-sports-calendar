.PHONY: install test build verify clean

BASE_URL ?= https://calendar.chelseakr.com

install:
	uv sync --extra dev

test:
	uv run pytest -q

build:
	uv run python -m wsc_pipeline.build --out dist --base-url $(BASE_URL)

validate-html:
	uv run --with html5validator html5validator --root dist

verify: install test build validate-html

clean:
	rm -rf dist dist.tmp .pytest_cache .venv
