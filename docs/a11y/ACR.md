# Next Home Game Accessibility Conformance Report (ACR)

Based on the VPAT® 2.5 Rev WCAG edition.

> **Status: draft, not issued.** This report is the result of automated
> testing and code review. No person has yet used the site with a screen
> reader, and no person has done a keyboard-only or browser-zoom pass.
> The repository's accessibility standard (ACCESSIBILITY-STANDARD §2.0)
> requires that human walkthrough before this report is issued as a formal
> ACR. Appendix A lists the steps. Rows marked **Supports (pending human
> check)** rest on automated and code evidence; they become plain
> "Supports" only once the matching Appendix A step passes. Nothing here is
> a claim that the site is "WCAG compliant" or "screen-reader tested".
>
> The remarks describe the site **after** the changes on branch
> `a11y/acr-2026-11` (listed under "Changes made for this report"). Until
> that branch is merged and deployed, those rows describe the next
> deployment, not the one live today.

## Name of product and version

Next Home Game (https://nexthomegame.com), the static website and its
calendar feeds, built by the `wsc_pipeline` package 0.1.0 (unreleased; the
deployed site is the release, see #7). Evaluated at `origin/main` eff0566
plus branch `a11y/acr-2026-11`.

## Report date

2026-11-20

## Product description

A free, static website that lists women's professional and college sports
games read from the Ticketmaster Discovery API, one page per league and per
team, each with calendar feeds (`.ics`) a reader subscribes to in Google
Calendar, Apple Calendar or Outlook, and a link to buy tickets from the home
team's seller. There are no accounts, no forms and no sign-in. The only
script on the HTML pages is the Google Analytics loader with its footer
opt-out button (DECISIONS 0012).

## Contact information

https://chelseakr.com/contact (the reporting channel named on
https://nexthomegame.com/accessibility/).

## Notes

- **Scope.** Every page template the build produces: the home page, the
  week-ahead schedule, each league page, each team page (with games, with
  only away games, and the empty "waiting for next season" and "not fetched"
  states), the moved-team notice, the about, help, accessibility, privacy
  and terms pages, and the 404 page. The subscribe flows are in scope up to
  the link that leaves this site.
- **Out of scope.** Pages this site links to and does not control:
  Ticketmaster and the teams' ticket sellers, Google Calendar's and
  Outlook's own subscribe pages, and each reader's calendar app. Their
  accessibility is theirs.
- **Calendar feeds (`.ics`).** Plain-text iCalendar files read by the
  reader's calendar app, which renders them. They are not web content under
  WCAG; their text (titles, notes, locations) is plain words with no color,
  images or layout. Rated N/A below where a row would otherwise reach them.
- **Atom feeds (`/feeds/*.atom`).** Machine-readable XML for feed readers,
  not web pages; not WCAG web content. N/A.
- **Light and dark.** The stylesheet follows the device's light or dark
  setting and swaps every content color. Both were tested; contrast numbers
  below are given for each.
- **Third-party content.** No third-party content is embedded on any page
  (no frames, widgets, maps or video). The Google Analytics script adds no
  visible content.

## Evaluation methods used

All runs on 2026-11-20, Chrome for Testing as pinned by puppeteer 25.16.0,
axe-core 4.11.4, pa11y-ci 5.0.0, against two local builds: the
no-API-key build (`make build`, every page in its "not fetched" state, 110
pages) and the populated fixture build (`scripts/build_fixture_site.py`,
canned listings that produce every games-table and hero state).

1. `make verify`, the repository's merge gate, on the final branch head:
   pa11y-ci (WCAG2AA, HTML_CodeSniffer and axe runners) on every page;
   `scripts/a11y_browser_checks.mjs` on every page (axe wcag2a through
   wcag22aa at moderate and above, in the light and, from this branch, the
   dark color scheme; a Tab walk checking the skip link, reachability,
   visible focus and that no focused element is covered; 320 CSS px reflow;
   from this branch, WCAG 1.4.12 text spacing at 320 CSS px; reduced
   motion), each check first proving it can fail on a planted defect.
   Before this branch the axe pass ran in whatever scheme the machine
   reported (light on CI's runners), so CI never checked dark mode;
   Lighthouse (accessibility score floor 0.90) on four pages; HTML
   validation (html5validator) on both builds.
2. A one-off review script (not committed) on 17 representative pages, light
   and dark, at 1280 and 320 CSS px: axe with every A and AA tag including
   "needs review" results and the measured contrast of every text node;
   heading outline; landmarks; image alternatives; `title` attributes; link
   and button sizes; a Tab walk recording order, outline and whether the
   focused element is covered; and WCAG 1.4.12 spacing applied as a user
   stylesheet.
3. Chrome's accessibility tree (puppeteer `accessibility.snapshot`) for
   computed link names.
4. Code review of `pipeline/src/wsc_pipeline/site.py` (all markup and
   `STYLE_CSS`) and `analytics.py` (the only script), and contrast computed
   from the stylesheet's color tokens for states the browser run does not
   reach (visited links, hover, focus outlines, borders).

Not used: any screen reader (NVDA, JAWS, VoiceOver, TalkBack), a person
using only a keyboard, real browser zoom, Windows High Contrast by a person,
or Firefox and Safari rendering. See Appendix A.

## Applicable standards and guidelines

| Standard / guideline | Included in report |
|---|---|
| Web Content Accessibility Guidelines 2.2 | Level A (Yes), Level AA (Yes), Level AAA (No) |

WCAG 2.2 includes every success criterion of WCAG 2.0 and 2.1 at the same
levels (except 4.1.1 Parsing, which 2.2 removed; it is kept below for 2.0
and 2.1 readers), so this report also covers WCAG 2.0 and 2.1 Level A and
AA.

## Terms

- **Supports**: the functionality of the product has at least one method
  that meets the criterion without known defects or meets with equivalent
  facilitation.
- **Supports (pending human check)**: as "Supports" on the automated and
  code evidence named in the remark; the matching Appendix A step by a
  person with assistive technology has not been done.
- **Partially Supports**: some functionality of the product does not meet
  the criterion.
- **Does Not Support**: the majority of product functionality does not meet
  the criterion.
- **Not Applicable**: the criterion is not relevant to the product.
- **Not Evaluated**: the product has not been evaluated against the
  criterion. Not used in this report.

## WCAG 2.2 Report

### Table 1: Success Criteria, Level A

| Criteria | Conformance Level | Remarks and Explanations |
|---|---|---|
| 1.1.1 Non-text Content | Supports | The only image on any page is the header's brand mark, decorative and marked `alt=""` beside the visible name "Next Home Game". The hero's month/day date chip is `aria-hidden` and the same date is in the text beside it. Shapes drawn in CSS (the subscribe card's tabs, the ticket notches, the heading stripe) are decoration. Social-card images carry `og:image:alt` text. |
| 1.2.1 Audio-only and Video-only (Prerecorded) | Not Applicable | No audio or video. |
| 1.2.2 Captions (Prerecorded) | Not Applicable | No audio or video. |
| 1.2.3 Audio Description or Media Alternative (Prerecorded) | Not Applicable | No audio or video. |
| 1.3.1 Info and Relationships | Supports (pending human check) | One `h1` per page and no skipped heading levels on any page checked; `header`, `nav` (labelled "Site" and "breadcrumb"), `main` and `footer` landmarks; sections named by their headings; lists for lists. Games tables have a caption, `th scope="col"` headers and explicit table roles, kept because on a phone the rows are restyled as stacked blocks. Pending: Appendix A step 3, that VoiceOver on iPhone still announces the column header with each cell in the stacked layout. |
| 1.3.2 Meaningful Sequence | Supports (pending human check) | Reading order is source order on every template; nothing is reordered by CSS position or flex order. Team lists in two columns read down the first column then the second, which is their A to Z order. Pending: Appendix A step 2. |
| 1.3.3 Sensory Characteristics | Supports | Instructions name controls by their labels. On this branch the team and league pages' Google Calendar step changed from "select the + icon" to "select Add other calendars (+)", the name Google gives the control and the one the help page already used. "Paste the address above" names the address as well as its place. |
| 1.4.1 Use of Color | Supports | Links in running text keep their underline. Home and away games are labelled with the words "Home" and "Away"; cancelled and postponed games with the word. The "Paid link" label is text. No information is carried by color alone. |
| 1.4.2 Audio Control | Not Applicable | No audio. |
| 2.1.1 Keyboard | Supports (pending human check) | Everything is a native link or button. The automated Tab walk on every page reaches every focusable element. The games table's sideways-scrolling wrapper is focusable (`tabindex="0"`, named by the table caption) so it can be scrolled from the keyboard. Pending: Appendix A step 1, a person completing each task with the keyboard alone. |
| 2.1.2 No Keyboard Trap | Supports (pending human check) | No widget captures keys; the Tab walk passes through every page and returns to the browser. Pending: Appendix A step 1. |
| 2.1.4 Character Key Shortcuts | Not Applicable | The site defines no keyboard shortcuts. |
| 2.2.1 Timing Adjustable | Not Applicable | No time limits. A former team address shows a notice that redirects at once (0 seconds) to the new page, which is not a time limit. |
| 2.2.2 Pause, Stop, Hide | Not Applicable | Nothing moves, blinks, scrolls or updates on its own. The only motion is a 120 ms color change on hover, which is removed under `prefers-reduced-motion: reduce` (gated on every page). |
| 2.3.1 Three Flashes or Below Threshold | Supports | Nothing flashes. |
| 2.4.1 Bypass Blocks | Supports | "Skip to main content" is the first Tab stop on every page (gated) and lands on `main`; landmarks as in 1.3.1. |
| 2.4.2 Page Titled | Supports | Every page has its own title naming the team, league or topic and the site; `validate_seo` fails the build on a missing or duplicate title. |
| 2.4.3 Focus Order | Supports (pending human check) | Focus follows source order, which follows the visual order; no positive `tabindex`. The "Use the calendar address" link jumps to the "Other calendar apps" section and the next Tab continues from there. Pending: Appendix A step 1. |
| 2.4.4 Link Purpose (In Context) | Supports (pending human check) | Link text says where it goes. A games-table ticket link shows "Tickets (AXS)" and carries the matchup, date, any status and the seller in visually hidden text inside the link, so each is distinct in a links list. Home page league links read "WNBA 8 upcoming games" in Chrome's accessibility tree; this branch adds a space between the two parts in the markup so no engine can run them together. Pending: Appendix A step 4, the links list in VoiceOver and NVDA. |
| 2.5.1 Pointer Gestures | Not Applicable | No multipoint or path-based gestures. |
| 2.5.2 Pointer Cancellation | Supports | Only native links and buttons, which act on release. |
| 2.5.3 Label in Name | Supports | Every link and button's accessible name starts with its visible text ("Tickets (AXS) for ..."; "Add to Google Calendar"; "Opt out of analytics"). |
| 2.5.4 Motion Actuation | Not Applicable | Nothing responds to device motion. |
| 3.1.1 Language of Page | Supports | `<html lang="en">` on every page (gated by axe). |
| 3.2.1 On Focus | Supports | Focus never changes the page or opens anything. |
| 3.2.2 On Input | Not Applicable | No form fields. The footer's analytics opt-out is a button that acts when pressed. |
| 3.2.6 Consistent Help | Supports | The header's "Help" link and the footer's contact lines (an email for a removal or a mistake, and the accessibility statement with its contact page) come from one template and are in the same place and order on every page. |
| 3.3.1 Error Identification | Not Applicable | No input. |
| 3.3.2 Labels or Instructions | Not Applicable | No input. |
| 3.3.7 Redundant Entry | Not Applicable | No multi-step process and no input. |
| 4.1.1 Parsing (WCAG 2.0 and 2.1 only) | Supports | Removed in WCAG 2.2. Every page of both builds passes html5validator in `make verify`. |
| 4.1.2 Name, Role, Value | Supports (pending human check) | Native links and buttons only; the scroll wrapper is a named `region`; the opt-out button's name changes to "Opt back in" when pressed. No custom widgets, so no ARIA states to keep in sync. axe finds no name, role or ARIA errors on any page. Pending: Appendix A steps 3 to 5. |

### Table 2: Success Criteria, Level AA

| Criteria | Conformance Level | Remarks and Explanations |
|---|---|---|
| 1.2.4 Captions (Live) | Not Applicable | No live audio or video. |
| 1.2.5 Audio Description (Prerecorded) | Not Applicable | No video. |
| 1.3.4 Orientation | Supports | Nothing locks orientation; the layout works in portrait and landscape. |
| 1.3.5 Identify Input Purpose | Not Applicable | No input fields. |
| 1.4.3 Contrast (Minimum) | Supports | Measured by axe on every text node of 17 pages in both schemes, and from the stylesheet for states the run does not reach. Lowest body text: light `#57526a` on `#f3f1f6`, 6.63:1; dark `#b3adc2` on `#1a1722`, 8.13:1; footer small print `#a29cb4` on `#16131d`, 6.94:1 (both). Links: `#16131d` on white 18.34:1; visited `#7b2d6b` 8.64:1 on white and 7.71:1 on the light panel; dark visited `#f2a7d8` 9.49:1 or more. Ticket button and date chip `#16131d` on lime `#d4f24a` 14.49:1 (hover 16.09:1); "Date TBD" chip `#16131d` on `#a29cb4` 6.94:1; table headers white on `#16131d` 18.34:1. From this branch the gate checks the dark scheme too. |
| 1.4.4 Resize Text | Supports (pending human check) | Sizes are in rem and nothing sets a fixed page width; at 320 CSS px wide (the width of a 1280 px window at 400%) no content is lost and nothing scrolls sideways (gated). Pending: Appendix A step 6, real browser zoom to 200% and a 200% text-only setting. |
| 1.4.5 Images of Text | Supports | No images of text on any page; the wordmark is styled text. |
| 1.4.10 Reflow | Supports | At 320 CSS px no page scrolls sideways and no box inside one does (gated on every page). Games tables restack as one game per block below 45rem; long feed addresses wrap. |
| 1.4.11 Non-text Contrast | Supports | Focus outline 3px: `#16131d` on white 18.34:1, on the light panel 16.35:1; lime `#d4f24a` on the dark page 15.26:1 and on black chrome 14.5:1. Subscribe buttons: black on the light panel 16.35:1; in dark mode their `#a29cb4` border 6.68:1 on `#1a1722`. Ticket button lime on black 14.5:1. Thin grey borders (table edge, "Away" pill, card edges in dark mode, 1.39 to 1.49:1) are decoration: no control or state depends on them. |
| 1.4.12 Text Spacing | Supports | With the criterion's spacing applied, no text is clipped or overlaps on any template at 1280 or 320 CSS px. Before this branch the home page at 320 CSS px grew to 367 px wide (the all-games feed address and the long NCAA league names beside their game count); both now wrap, and the gate checks every page at 320 CSS px with this spacing. |
| 1.4.13 Content on Hover or Focus | Not Applicable | Nothing appears on hover or focus: no tooltips, menus or pop-ups. The only `title` attribute is on the `<link>` to the Atom feed in the page head. |
| 2.4.5 Multiple Ways | Supports | The header links to the league list, the week ahead and help; the home page lists every league and every team; league pages list their teams; team pages list the other teams; breadcrumbs on league and team pages. |
| 2.4.6 Headings and Labels | Supports | Headings name their sections ("Add the Las Vegas Aces schedule to your calendar", "Upcoming games", "Other calendar apps"). |
| 2.4.7 Focus Visible | Supports | A 3px outline with a 2px offset on every link, button and the table wrapper, recolored on the black header, footer and ticket card (gated: every Tab stop on every page must show one). Contrast in 1.4.11. |
| 2.4.11 Focus Not Obscured (Minimum) | Supports | No sticky or fixed content; the gate checks that every focused element is at least partly visible. |
| 2.5.7 Dragging Movements | Not Applicable | Nothing is dragged. |
| 2.5.8 Target Size (Minimum) | Supports | Header links, subscribe buttons and the ticket button are at least 44px tall; team list links are at least 24px; the opt-out button is at least 24px tall. Links inside sentences are excepted as inline. Games-table ticket links can be under 24px tall but sit one per table row, with no other target within 24px, which meets the spacing exception; axe `target-size` passes on every page. |
| 3.1.2 Language of Parts | Supports | All text is English; team, venue and place names (such as "Montréal Victoire") are proper names, which the criterion excepts. |
| 3.2.3 Consistent Navigation | Supports | One header and one footer template on every page, in the same order. |
| 3.2.4 Consistent Identification | Supports | The same function has the same name everywhere ("Add to Google Calendar", "Tickets", "Paid link", "Calendar help"). |
| 3.3.3 Error Suggestion | Not Applicable | No input. |
| 3.3.4 Error Prevention (Legal, Financial, Data) | Not Applicable | No transactions; ticket purchases happen on the sellers' own sites. |
| 3.3.8 Accessible Authentication (Minimum) | Not Applicable | No accounts or sign-in. |
| 4.1.3 Status Messages | Supports (pending human check) | The one status message, the footer line after "Opt out of analytics" is pressed, is in a `role="status"` region that is on the page before its text changes. Pending: Appendix A step 5, that VoiceOver and NVDA read it without moving focus. |

### Table 3: Success Criteria, Level AAA

Not evaluated; AAA is outside this product's target.

## Counts

| Level | Supports | Supports (pending human check) | Partially Supports | Does Not Support | Not Applicable | Total |
|---|---|---|---|---|---|---|
| A (with 4.1.1) | 12 | 7 | 0 | 0 | 13 | 32 |
| AA | 14 | 2 | 0 | 0 | 8 | 24 |

These counts describe the site after this branch. On `main` before it, two
rows were weaker: 1.4.12 (the home page scrolled sideways at 320 CSS px
with text spacing, though nothing was lost) and 1.3.3 (one instruction
named a control by its "+" shape).

## Changes made for this report

On branch `a11y/acr-2026-11`:

- The browser gate runs axe a second time with `prefers-color-scheme:
  dark` on every page, with a planted dark-only contrast defect it must
  catch first (1.4.3, 1.4.11).
- The browser gate checks WCAG 1.4.12 text spacing at 320 CSS px on every
  page, with a planted clipped box it must catch first.
- The home page's all-games feed address and league names wrap under text
  spacing (1.4.12). No change at default settings.
- League rows on the home page have a space between the league name and
  its game count in the markup (2.4.4, 4.1.2).
- The Google Calendar step on team and league pages names the control,
  "Add other calendars (+)", instead of its shape (1.3.3).
- The accessibility page and `docs/a11y/STATEMENT.md` say axe runs in both
  color schemes; the statement's 3.2.6 row is corrected.

## Appendix A: human walkthrough still to do

About 2.5 to 3 hours in all. Record the result in
`docs/a11y/screen-reader-walkthrough-YYYY-MM-DD.md` (ACCESSIBILITY-STANDARD
§2), pass or fail per step with the AT and browser used, then change each
"Supports (pending human check)" row it covers.

Pages to use (from a populated night; if a league is off-season, use one
that has games): the home page; `/wnba/` or another league with games; a
team page with games, such as `/wnba/las-vegas-aces/`; an empty team page
waiting for next season; `/help/`; `/accessibility/`.

1. **Keyboard only** (any desktop browser, no mouse; 20 min). On the home
   page, a league page and a team page: Tab from the address bar. The first
   stop is "Skip to main content" and Enter moves into the page. Reach every
   link in reading order; the outline is always visible and never hidden.
   On a team page: Tab to the games table and scroll it with the arrow keys
   at a narrow window; follow "Use the calendar address" and confirm the
   next Tab continues in "Other calendar apps"; open "Add to Google
   Calendar" and come back. In the footer, press "Opt out of analytics" with
   Space and with Enter. Covers 2.1.1, 2.1.2, 2.4.3.
2. **VoiceOver on macOS with Safari** (30 min). Read the home page and a
   team page top to bottom with VO+Right. Listen for: headings in a sensible
   order, the skip link, the hero read as one game (matchup, date and time,
   venue, then the ticket link), no stray "SEP 19" from the date chip.
   Covers 1.3.1, 1.3.2.
3. **VoiceOver on iPhone with Safari** (30 min). On a team page with games,
   swipe through the games table. Listen for each cell announced with its
   column ("Date", "Matchup", "Venue", "Tickets") even though the rows are
   stacked on a phone. Use the rotor's Headings and Links. Subscribe with
   "Add to Apple Calendar" and confirm the system sheet is announced.
   Covers 1.3.1, 4.1.2.
4. **NVDA with Firefox or Chrome on Windows** (40 min). Press Insert+F7 for
   the links list on a team page: each ticket link should be distinct
   ("Tickets (AXS) for Las Vegas Aces vs Seattle Storm on ..."), and league
   rows on the home page should read "WNBA 8 upcoming games" with a pause,
   not "WNBA8". Use T to jump to the games table and Ctrl+Alt+arrows to move
   by cell; headers should be read. Covers 2.4.4, 1.3.1, 4.1.2.
5. **Status message** (10 min, VoiceOver and NVDA). Press "Opt out of
   analytics" in the footer. Listen for "Opted out. From the next page you
   open ..." read without focus moving, and the button now named "Opt back
   in". Press again for "Opted back in ...". Covers 4.1.3, 4.1.2.
6. **Zoom and text size** (15 min). In Chrome or Safari zoom to 200% and to
   400% on a team page and the home page: nothing cut off or overlapping,
   no sideways scrolling at 400%. In Safari or Firefox, enlarge text only to
   200%. Covers 1.4.4, 1.4.10.
7. **Windows contrast theme** (10 min, optional). With a Windows contrast
   theme on, the ticket button and date chip keep a visible border, and
   focus is visible.

---

VPAT® is a registered service mark of the Information Technology Industry
Council (ITI).
