# site/

The static HTML generator lives at `pipeline/src/wsc_pipeline/site.py`
instead of here, deliberately: it renders directly from the same `Game` and
`League` types `pipeline/src/wsc_pipeline/normalize.py` and `config.py`
define, so keeping it in the same Python package avoided a second package,
a second dependency lockfile, and a cross-package import path for one
module that has nothing to do apart from that rendering. The CSS is
embedded there too (`site.STYLE_CSS`), for the same reason — one file per
concept, not one file per directory.

This directory is what a build actually publishes to: `pipeline/dist/`
(gitignored, rebuilt on every run — never commit it) is what
`.github/workflows/pages.yml` uploads to GitHub Pages. Nothing here is
committed output; run `make build` inside `pipeline/` to generate it
locally and look at `pipeline/dist/`.
