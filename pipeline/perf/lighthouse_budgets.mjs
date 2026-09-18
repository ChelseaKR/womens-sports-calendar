// Lighthouse budgets and the committed-baseline regression check for `make perf`.
//
// For every path in perf/lighthouse.json, run Lighthouse `runs` times
// (default mobile profile, simulated throttling) against the built site on a
// local server, take the median run by performance score, and fail on:
//
//   PERF-02            performance score < 0.9, or script transfer > 200 KB
//   A11Y-02            accessibility score < 0.9
//   OBS-23 / OBS-25    LCP >= 2500 ms, CLS >= 0.1
//   OBS-24             total blocking time >= 200 ms (INP has no lab measure;
//                      TBT is Lighthouse's lab proxy for it)
//   PERF-03            any baseline metric more than 10% worse than
//                      perf/baseline.json, direction-aware (§2 of the standard)
//
// A run that errors, or a category Lighthouse could not score, fails: an
// unmeasured page is not a pass. The report (perf/report.json) keeps every
// run's numbers.
//
// `--self-test <dist> <base-url>` first writes a page with a 300 KB script
// that blocks the main thread, checks the file landed, and requires the
// budgets to reject it, so a budget that silently stopped applying fails
// the build.
//
// `--write-baseline` records the aggregate of this run as the new baseline;
// PERFORMANCE-STANDARD §2 says when that is allowed.
//
// Usage:
//   node perf/lighthouse_budgets.mjs <base-url> <lighthouse.json> <baseline.json> <report.json> [--write-baseline]
//   node perf/lighthouse_budgets.mjs --self-test <dist-dir> <base-url>

import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import * as chromeLauncher from "chrome-launcher";
import lighthouse from "lighthouse";

const TOLERANCE = 0.1;

async function measure(chrome, url) {
  const result = await lighthouse(url, {
    port: chrome.port,
    output: "json",
    logLevel: "error",
    onlyCategories: ["performance", "accessibility"],
  });
  const lhr = result.lhr;
  if (lhr.runtimeError) throw new Error(`${url}: Lighthouse runtime error ${lhr.runtimeError.code}`);
  const scripts = lhr.audits["resource-summary"].details.items.find((item) => item.resourceType === "script");
  return {
    performance: lhr.categories.performance.score,
    accessibility: lhr.categories.accessibility.score,
    lcp_ms: lhr.audits["largest-contentful-paint"].numericValue,
    cls: lhr.audits["cumulative-layout-shift"].numericValue,
    tbt_ms: lhr.audits["total-blocking-time"].numericValue,
    script_bytes: scripts ? scripts.transferSize : 0,
    total_bytes: lhr.audits["total-byte-weight"].numericValue,
  };
}

function median(runs) {
  const sorted = [...runs].sort((a, b) => a.performance - b.performance);
  return sorted[Math.floor(sorted.length / 2)];
}

function budgetProblems(path, m, budgets) {
  const problems = [];
  for (const [key, value] of Object.entries(m)) {
    if (typeof value !== "number" || Number.isNaN(value)) problems.push(`${path}: ${key} was not measured (${value})`);
  }
  if (m.performance < budgets.performance_score_min)
    problems.push(`${path}: performance ${m.performance} < ${budgets.performance_score_min}`);
  if (m.accessibility < budgets.accessibility_score_min)
    problems.push(`${path}: accessibility ${m.accessibility} < ${budgets.accessibility_score_min}`);
  if (m.lcp_ms >= budgets.largest_contentful_paint_ms_max)
    problems.push(`${path}: LCP ${Math.round(m.lcp_ms)} ms >= ${budgets.largest_contentful_paint_ms_max}`);
  if (m.cls >= budgets.cumulative_layout_shift_max)
    problems.push(`${path}: CLS ${m.cls.toFixed(3)} >= ${budgets.cumulative_layout_shift_max}`);
  if (m.tbt_ms >= budgets.total_blocking_time_ms_max)
    problems.push(`${path}: TBT ${Math.round(m.tbt_ms)} ms >= ${budgets.total_blocking_time_ms_max}`);
  if (m.script_bytes > budgets.script_transfer_bytes_max)
    problems.push(`${path}: script transfer ${m.script_bytes} B > ${budgets.script_transfer_bytes_max}`);
  return problems;
}

// The baseline tracks the worst page: the lowest score, the slowest LCP, the
// heaviest page.
function aggregate(medians) {
  const values = Object.values(medians);
  return {
    lighthouse_performance: Math.min(...values.map((m) => m.performance)),
    lcp_ms: Math.max(...values.map((m) => m.lcp_ms)),
    total_byte_weight_kb: Math.max(...values.map((m) => m.total_bytes)) / 1024,
  };
}

function regressionProblems(current, baseline) {
  const problems = [];
  for (const [metric, base] of Object.entries(baseline.metrics)) {
    if (base === null) continue;
    const now = current[metric];
    if (typeof now !== "number") {
      problems.push(`baseline metric ${metric} was not measured this run`);
      continue;
    }
    const direction = baseline.direction[metric];
    if (direction === "lower_is_better" && now > base * (1 + TOLERANCE)) {
      problems.push(`${metric} regressed: ${now.toFixed(2)} > baseline ${base} x 1.10`);
    } else if (direction === "higher_is_better" && now < base * (1 - TOLERANCE)) {
      problems.push(`${metric} regressed: ${now.toFixed(2)} < baseline ${base} x 0.90`);
    } else if (direction !== "lower_is_better" && direction !== "higher_is_better") {
      problems.push(`baseline metric ${metric} has no direction`);
    }
  }
  return problems;
}

async function withChrome(fn) {
  const chrome = await chromeLauncher.launch({
    chromePath: process.env.CHROME_PATH || undefined,
    chromeFlags: ["--headless=new", "--no-sandbox"],
  });
  try {
    return await fn(chrome);
  } finally {
    await chrome.kill();
  }
}

async function selfTest(distDir, baseUrl) {
  const config = JSON.parse(readFileSync("perf/lighthouse.json", "utf8"));
  const dir = join(distDir, "_perf-self-test");
  mkdirSync(dir, { recursive: true });
  const blocker = "const end = Date.now() + 600; while (Date.now() < end) {}\n";
  const padding = `/* ${"x".repeat(300 * 1024)} */\n`;
  writeFileSync(join(dir, "heavy.js"), blocker + padding);
  const page = readFileSync(join(distDir, "index.html"), "utf8").replace(
    "</head>",
    '<script src="/_perf-self-test/heavy.js"></script></head>',
  );
  writeFileSync(join(dir, "heavy.html"), page);
  try {
    if (!existsSync(join(dir, "heavy.js")) || !readFileSync(join(dir, "heavy.html"), "utf8").includes("heavy.js")) {
      throw new Error("self-test: the planted page was not written, so a failure would prove nothing");
    }
    const m = await withChrome((chrome) => measure(chrome, `${baseUrl}/_perf-self-test/heavy.html`));
    const problems = budgetProblems("/_perf-self-test/heavy.html", m, config.budgets);
    const caught = ["script transfer", "TBT"].filter((needle) => problems.some((p) => p.includes(needle)));
    if (caught.length !== 2) {
      throw new Error(`self-test: expected script-transfer and TBT failures, got ${JSON.stringify(problems)}`);
    }
    // The regression half: the heavy page must also read as a regression
    // against the committed baseline's page weight.
    const baseline = JSON.parse(readFileSync("perf/baseline.json", "utf8"));
    if (typeof baseline.metrics.total_byte_weight_kb !== "number") {
      throw new Error("self-test: perf/baseline.json has no page-weight baseline, so the regression check cannot fail");
    }
    const regressions = regressionProblems(aggregate({ heavy: m }), baseline);
    if (!regressions.some((p) => p.startsWith("total_byte_weight_kb regressed"))) {
      throw new Error(`self-test: expected a page-weight regression, got ${JSON.stringify(regressions)}`);
    }
    console.log("lighthouse budgets self-test: a 300 KB main-thread-blocking script is rejected, and reads as a regression");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

async function main() {
  const args = process.argv.slice(2);
  if (args[0] === "--self-test") {
    await selfTest(args[1], args[2]);
    return;
  }
  const [baseUrl, configPath, baselinePath, reportPath, flag] = args;
  if (!reportPath) {
    console.error("usage: lighthouse_budgets.mjs <base-url> <lighthouse.json> <baseline.json> <report.json> [--write-baseline]");
    process.exit(2);
  }
  const config = JSON.parse(readFileSync(configPath, "utf8"));
  const runs = {};
  await withChrome(async (chrome) => {
    for (const path of config.paths) {
      runs[path] = [];
      for (let i = 0; i < config.runs; i += 1) runs[path].push(await measure(chrome, `${baseUrl}${path}`));
    }
  });
  const medians = Object.fromEntries(Object.entries(runs).map(([path, list]) => [path, median(list)]));
  const current = aggregate(medians);
  const problems = Object.entries(medians).flatMap(([path, m]) => budgetProblems(path, m, config.budgets));

  const baseline = JSON.parse(readFileSync(baselinePath, "utf8"));
  if (flag === "--write-baseline") {
    baseline.metrics = { ...baseline.metrics, ...Object.fromEntries(Object.entries(current).map(([k, v]) => [k, Number(v.toFixed(3))])) };
    baseline.meta.date = new Date().toISOString().slice(0, 10);
    writeFileSync(baselinePath, `${JSON.stringify(baseline, null, 2)}\n`);
    console.log(`wrote ${baselinePath}; fill in meta.commit and meta.environment before committing it`);
  } else {
    problems.push(...regressionProblems(current, baseline));
  }
  writeFileSync(reportPath, `${JSON.stringify({ medians, current, runs }, null, 2)}\n`);

  for (const [path, m] of Object.entries(medians)) {
    console.log(
      `${path}: performance ${m.performance}, accessibility ${m.accessibility}, LCP ${Math.round(m.lcp_ms)} ms, ` +
        `CLS ${m.cls.toFixed(3)}, TBT ${Math.round(m.tbt_ms)} ms, script ${m.script_bytes} B, total ${Math.round(m.total_bytes / 1024)} KB`,
    );
  }
  for (const p of problems) console.error(`PERF FAILED: ${p}`);
  if (problems.length > 0) process.exit(1);
  console.log(`lighthouse budgets: ${config.paths.length} pages within budget and within 10% of the baseline`);
}

await main();
