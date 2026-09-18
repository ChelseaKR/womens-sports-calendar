# Accessibility records

| File | What it is |
|---|---|
| `STATEMENT.md` | The accessibility statement (A11Y-16). |

## axe "needs review" results

pa11y-ci's axe runner reports results axe itself marks as *needs review*.
These are cases where axe could not work out a value, for example the
background behind text that shares a box with a pseudo-element. They are
capped at warning (`levelCapWhenNeedsReview` in
`pipeline/pa11y-ci.config.json`), so they're logged but don't fail the build.
Definite axe violations at moderate and above still fail, through
`scripts/a11y_browser_checks.mjs`. Every kind of needs-review result seen on
the site is recorded here with a measured value. A new kind gets measured
and added in the PR that introduces it.

| Element | Why axe can't decide | Measured (2026-09-17, Chrome, computed colours) |
|---|---|---|
| Text in the subscribe box (`code`, `strong` in the instructions) | `.subscribe::before` / `::after` pseudo-elements share the box | `rgb(238,242,248)` on `rgb(16,28,48)`: 15.19:1 |
| Footer `h2` "Sources and terms" | footer children use `max-width` + auto margins over the navy band | `#ffffff` on `#0b1f3a`: 16.52:1 |

Both are well above 4.5:1.
