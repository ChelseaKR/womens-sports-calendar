// Browser-level accessibility gates for every page `make a11y` serves.
//
// pa11y-ci (HTML_CodeSniffer + axe runners) reports axe "moderate" findings
// only as warnings, and cannot see anything that needs a keyboard, a narrow
// viewport or a motion preference. This script closes those gaps for each
// URL it is given (ACCESSIBILITY-STANDARD §1):
//
//   A11Y-01/05/06/26  axe-core, tags wcag2a/wcag2aa/wcag21a/wcag21aa/wcag22aa:
//                     any critical, serious OR moderate violation fails
//                     (includes color-contrast, target-size, html-has-lang).
//   A11Y-07           keyboard: Tab from the top of the page reaches every
//                     tabbable element, the first stop is the skip link,
//                     every stop shows a visible focus indicator, and no
//                     focused element is fully covered by other content.
//   A11Y-09           reflow: at 320x256 CSS px the page does not scroll
//                     horizontally.
//   A11Y-08           reduced motion: with prefers-reduced-motion: reduce,
//                     no element has a running animation or a non-zero
//                     animation/transition duration.
//
// Every request that is not to the local test server is aborted, so the
// checks are hermetic and never touch a third-party service.
//
// It writes a JSON report and exits 1 if any page fails, 2 if it was given
// no URLs. The report lists every page with the number of axe rules that
// ran and the number of tab stops it walked, so a page that was checked
// against nothing is visible as such, and scripts/check_a11y_browser_report.py
// then asserts every expected page is present.
//
// `--self-test <url>` first plants one defect per check in copies of a real
// page (served from memory) and exits 1 unless every check catches its
// defect, so a check that silently stopped working cannot pass everything.
//
// Usage: node scripts/a11y_browser_checks.mjs <report.json> <url> [<url> ...]
//        node scripts/a11y_browser_checks.mjs --self-test <url>

import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import puppeteer from "puppeteer";

const require = createRequire(import.meta.url);
const AXE_SOURCE = readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");
const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const BLOCKING_IMPACTS = new Set(["critical", "serious", "moderate"]);
const CONCURRENCY = Number(process.env.A11Y_BROWSER_CONCURRENCY || 4);
const NAV_TIMEOUT_MS = 60_000;
// URL -> HTML for --self-test's sabotaged copies, served from memory.
const SELF_TEST_PAGES = new Map();

// Each case breaks one rule in a copy of a real page and names the problem
// prefix the check must report. `apply` must change the HTML; the self-test
// asserts that it did before trusting a failure.
const SABOTAGE = [
  {
    name: "low-contrast text",
    expect: "axe serious color-contrast",
    apply: (html) => html.replace("</head>", "<style>main p { color: #b8b8b8 !important; background: #fff !important; }</style></head>"),
  },
  {
    name: "focus outline removed",
    expect: "keyboard: no visible focus indicator",
    apply: (html) => html.replace("</head>", "<style>*:focus, *:focus-visible { outline: none !important; box-shadow: none !important; }</style></head>"),
  },
  {
    name: "skip link removed",
    expect: "keyboard: first tab stop",
    apply: (html) => html.replace(/<a class="skip-link"[^>]*>[^<]*<\/a>/, ""),
  },
  {
    name: "fixed-width content",
    expect: "reflow:",
    apply: (html) => html.replace("</main>", '<div style="width: 900px">wide</div></main>'),
  },
  {
    name: "transition outside reduced-motion",
    expect: "reduced motion:",
    apply: (html) => html.replace("</head>", "<style>a { transition: color 400ms linear !important; }</style></head>"),
  },
];

function isLocal(url) {
  const { hostname, protocol } = new URL(url);
  return protocol === "data:" || hostname === "127.0.0.1" || hostname === "localhost";
}

async function openPage(browser, url, viewport, reducedMotion = false) {
  const page = await browser.newPage();
  // Pages are checked several at a time in one browser, and only one tab has
  // real focus; without this, :focus-visible does not match in the others
  // and a correct focus style reads as missing.
  const session = await page.createCDPSession();
  await session.send("Emulation.setFocusEmulationEnabled", { enabled: true });
  await page.setRequestInterception(true);
  page.on("request", (request) => {
    const planted = SELF_TEST_PAGES.get(request.url());
    if (planted !== undefined) return request.respond({ status: 200, contentType: "text/html", body: planted });
    return isLocal(request.url()) ? request.continue() : request.abort();
  });
  await page.setViewport(viewport);
  if (reducedMotion) {
    await page.emulateMediaFeatures([{ name: "prefers-reduced-motion", value: "reduce" }]);
  }
  await page.goto(url, { waitUntil: "load", timeout: NAV_TIMEOUT_MS });
  await page.evaluate(() => document.fonts.ready);
  return page;
}

async function runAxe(page) {
  await page.evaluate(AXE_SOURCE);
  return page.evaluate(async (tags) => {
    const result = await window.axe.run(document, {
      runOnly: { type: "tag", values: tags },
      resultTypes: ["violations"],
    });
    return {
      rulesRun: result.violations.length + result.passes.length + result.inapplicable.length + result.incomplete.length,
      violations: result.violations.map((v) => ({
        id: v.id,
        impact: v.impact,
        help: v.help,
        targets: v.nodes.slice(0, 5).map((n) => n.target.join(" ")),
      })),
    };
  }, AXE_TAGS);
}

// Tab from the top of the document until focus returns to <body> or to an
// element already visited, recording what each stop looks like.
async function walkTabOrder(page) {
  const expected = await page.evaluate(() => {
    const selector =
      'a[href], area[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), ' +
      'select:not([disabled]), textarea:not([disabled]), iframe, summary, [tabindex]:not([tabindex="-1"]), ' +
      '[contenteditable="true"]';
    const visible = (el) => {
      const style = getComputedStyle(el);
      return style.visibility !== "hidden" && style.display !== "none" && el.getClientRects().length > 0;
    };
    const all = [...document.querySelectorAll(selector)].filter((el) => el.tabIndex >= 0);
    // The skip link is off-screen until focused; count it as tabbable.
    return all.filter((el) => visible(el) || el.classList.contains("skip-link")).length;
  });

  const stops = [];
  const seen = new Set();
  for (let i = 0; i < expected + 5; i += 1) {
    await page.keyboard.press("Tab");
    const stop = await page.evaluate(() => {
      const el = document.activeElement;
      if (!el || el === document.body) return null;
      el.dataset.a11yTabId ||= String(Math.random());
      const style = getComputedStyle(el);
      const outlineWidth = parseFloat(style.outlineWidth) || 0;
      const indicator =
        (style.outlineStyle !== "none" && outlineWidth >= 1) || (style.boxShadow && style.boxShadow !== "none");
      const rect = el.getBoundingClientRect();
      const points = [
        [rect.left + rect.width / 2, rect.top + rect.height / 2],
        [rect.left + 2, rect.top + 2],
        [rect.right - 2, rect.bottom - 2],
      ];
      const visiblePoint = points.some(([x, y]) => {
        if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) return false;
        const hit = document.elementFromPoint(x, y);
        return hit !== null && (hit === el || el.contains(hit) || hit.contains(el));
      });
      return {
        id: el.dataset.a11yTabId,
        tag: el.tagName.toLowerCase(),
        text: (el.textContent || el.getAttribute("aria-label") || "").trim().slice(0, 60),
        isSkipLink: el.classList.contains("skip-link"),
        indicator,
        visiblePoint,
      };
    });
    if (stop === null || seen.has(stop.id)) break;
    seen.add(stop.id);
    stops.push(stop);
  }
  return { expected, stops };
}

async function checkPage(browser, url) {
  const problems = [];

  const desktop = await openPage(browser, url, { width: 1280, height: 800 });
  const axe = await runAxe(desktop);
  for (const v of axe.violations) {
    if (BLOCKING_IMPACTS.has(v.impact)) {
      problems.push(`axe ${v.impact} ${v.id}: ${v.help} (${v.targets.join(", ")})`);
    }
  }
  if (axe.rulesRun === 0) problems.push("axe ran no rules");
  await desktop.close();

  const keyboardPage = await openPage(browser, url, { width: 1280, height: 800 });
  const { expected, stops } = await walkTabOrder(keyboardPage);
  await keyboardPage.close();
  if (stops.length === 0) {
    problems.push("keyboard: Tab reached nothing");
  } else if (!stops[0].isSkipLink) {
    problems.push(`keyboard: first tab stop is <${stops[0].tag}> "${stops[0].text}", not the skip link`);
  }
  if (stops.length !== expected) {
    problems.push(`keyboard: Tab reached ${stops.length} of ${expected} tabbable elements`);
  }
  for (const stop of stops) {
    if (!stop.indicator) problems.push(`keyboard: no visible focus indicator on <${stop.tag}> "${stop.text}"`);
    if (!stop.visiblePoint) problems.push(`keyboard: focused <${stop.tag}> "${stop.text}" is fully obscured`);
  }

  const narrow = await openPage(browser, url, { width: 320, height: 256 });
  const reflow = await narrow.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  await narrow.close();
  if (reflow.scrollWidth > reflow.clientWidth + 1) {
    problems.push(`reflow: ${reflow.scrollWidth}px of content in a ${reflow.clientWidth}px viewport at 320 CSS px`);
  }

  const calm = await openPage(browser, url, { width: 1280, height: 800 }, true);
  const moving = await calm.evaluate(() => {
    const seconds = (value) => Math.max(...value.split(",").map((part) => parseFloat(part) || 0));
    const offenders = [];
    for (const el of document.querySelectorAll("*")) {
      const style = getComputedStyle(el);
      const animated = style.animationName !== "none" && seconds(style.animationDuration) > 0.01;
      const transitioned = seconds(style.transitionDuration) > 0.01;
      if (animated || transitioned) offenders.push(`<${el.tagName.toLowerCase()} class="${el.className}">`);
    }
    return { running: document.getAnimations().length, offenders: offenders.slice(0, 5), total: offenders.length };
  });
  await calm.close();
  if (moving.running > 0 || moving.total > 0) {
    problems.push(
      `reduced motion: ${moving.running} running animation(s), ${moving.total} element(s) still animate or transition (${moving.offenders.join(", ")})`,
    );
  }

  return { url, axeRulesRun: axe.rulesRun, tabStops: stops.length, tabbable: expected, problems };
}

// Prove each check can fail: fetch a real page, plant one defect per case,
// confirm the planted HTML differs from the original, and require the check
// to report that defect. Returns a list of self-test failures.
async function selfTest(browser, baseUrl) {
  const original = await (await fetch(baseUrl)).text();
  const failures = [];
  const clean = await checkPage(browser, baseUrl);
  if (clean.problems.length > 0) failures.push(`the unmodified page already fails: ${clean.problems.join("; ")}`);
  for (const [index, sabotage] of SABOTAGE.entries()) {
    const planted = sabotage.apply(original);
    if (planted === original) {
      failures.push(`${sabotage.name}: the sabotage did not change the page, so a pass would prove nothing`);
      continue;
    }
    const url = new URL(`/_a11y-self-test/${index}.html`, baseUrl).href;
    SELF_TEST_PAGES.set(url, planted);
    const result = await checkPage(browser, url);
    if (!result.problems.some((p) => p.startsWith(sabotage.expect))) {
      failures.push(`${sabotage.name}: expected a "${sabotage.expect}" problem, got ${JSON.stringify(result.problems)}`);
    }
  }
  return failures;
}

async function main() {
  if (process.argv[2] === "--self-test") {
    const browser = await puppeteer.launch({ args: ["--no-sandbox"] });
    let failures;
    try {
      failures = await selfTest(browser, process.argv[3]);
    } finally {
      await browser.close();
    }
    for (const f of failures) console.error(`self-test: ${f}`);
    if (failures.length > 0) process.exit(1);
    console.log(`a11y browser checks self-test: all ${SABOTAGE.length} planted defects caught`);
    return;
  }
  const [reportPath, ...urls] = process.argv.slice(2);
  if (!reportPath || urls.length === 0) {
    console.error("usage: a11y_browser_checks.mjs <report.json> <url> [<url> ...]");
    process.exit(2);
  }
  const browser = await puppeteer.launch({ args: ["--no-sandbox"] });
  const results = [];
  try {
    const queue = [...urls];
    const workers = Array.from({ length: Math.min(CONCURRENCY, urls.length) }, async () => {
      while (queue.length > 0) {
        const url = queue.shift();
        try {
          results.push(await checkPage(browser, url));
        } catch (error) {
          results.push({ url, axeRulesRun: 0, tabStops: 0, tabbable: 0, problems: [`could not be checked: ${error.message}`] });
        }
      }
    });
    await Promise.all(workers);
  } finally {
    await browser.close();
  }
  results.sort((a, b) => a.url.localeCompare(b.url));
  writeFileSync(reportPath, `${JSON.stringify({ urls, results }, null, 2)}\n`);

  const failing = results.filter((r) => r.problems.length > 0);
  for (const r of failing) {
    console.error(`\n${r.url}`);
    for (const p of r.problems) console.error(`  - ${p}`);
  }
  console.log(
    `a11y browser checks: ${results.length - failing.length}/${results.length} pages pass ` +
      "(axe wcag2a..wcag22aa at moderate+, keyboard, 320px reflow, reduced motion)",
  );
  process.exit(failing.length > 0 ? 1 : 0);
}

await main();
