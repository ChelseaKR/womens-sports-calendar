# Accessibility statement: Next Home Game (nexthomegame.com)

**Accessibility status: WCAG 2.2 AA target. Automated checks pass on every
page of every build. No human assistive-technology review has been done
yet.**

Date: 2026-09-17 · Applies to: https://nexthomegame.com and its calendar
feeds · Published at https://nexthomegame.com/accessibility/, linked from
every page's footer. The page renders the status sentence above from
`pipeline/src/wsc_pipeline/site.py` (`ACCESSIBILITY_STATUS`), and a test
keeps the two identical.

## Target

WCAG 2.2 Level AA (ACCESSIBILITY-STANDARD, vendored in `docs/standards/`).
This is a target, not a conformance claim: nothing here has been checked
with a screen reader by a person, and nothing below should be read as
"WCAG compliant" or "screen-reader tested".

## What is checked on every change

Each check below runs in `make verify` (and so in CI) against every HTML page
the build produces, plus two fixture pages with a populated games table:

- pa11y-ci, WCAG2AA, with both the HTML_CodeSniffer and axe runners; zero
  errors.
- axe-core with the wcag2a, wcag2aa, wcag21a, wcag21aa and wcag22aa tags;
  any critical, serious or moderate violation fails. This covers colour
  contrast (SC 1.4.3 / 1.4.11), target size (2.5.8) and the page language
  (3.1.1).
- A keyboard walk: Tab from the top reaches every link, the first stop is
  the skip link, every stop shows a visible focus indicator, and no focused
  element is fully covered (2.1.1, 2.4.1, 2.4.7, 2.4.11).
- Reflow at 320 CSS px: no horizontal scrolling (1.4.10).
- Reduced motion: with `prefers-reduced-motion: reduce` nothing animates or
  transitions (2.3.3, as a courtesy; the site has no essential motion).

Each browser check first proves it can fail: a copy of a real page with one
planted defect per check has to be caught before the real pages are
checked.

## WCAG 2.2 success criteria new at AA

| SC | Status here |
|---|---|
| 2.4.11 Focus Not Obscured (Minimum) | Checked automatically on every page (keyboard walk). No sticky or fixed content exists to obscure focus. |
| 2.5.7 Dragging Movements | Not applicable: nothing on the site is dragged. |
| 2.5.8 Target Size (Minimum) | Checked by axe `target-size` on every page. |
| 3.2.6 Consistent Help | Not applicable: the site offers no help mechanism (no contact form, chat or help page) on its pages. |
| 3.3.7 Redundant Entry | Not applicable: the site has no forms. |
| 3.3.8 Accessible Authentication (Minimum) | Not applicable: no accounts, no sign-in. |

## Known gaps

- **No human review.** A screen-reader walkthrough (NVDA with Firefox or
  Chrome; VoiceOver with Safari on macOS and iOS) and a human keyboard-only
  pass have not been done (A11Y-11, A11Y-12, A11Y-18). There is no
  Accessibility Conformance Report (A11Y-14).
- **Calendar apps.** The `.ics` feeds are plain text read by each reader's
  own calendar app; their accessibility is that app's.
- Pages that link out go to Ticketmaster and other ticket sellers, whose
  sites are outside this statement.

## Reporting a barrier

Use the contact page at https://chelseakr.com/contact and say which page
and what got in the way. Reports are read and answered; a barrier on a
primary task (finding a team, subscribing to a feed, following a ticket
link) is fixed first.
