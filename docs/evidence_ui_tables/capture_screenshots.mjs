/**
 * MARKUP FIXTURE CAPTURE — not a live Next.js route verification.
 *
 * This script rebuilds page markup by hand and serves it with the live
 * apps/web/src/app/globals.css. It does NOT boot the Next app shell, auth,
 * or /design-impact|/portfolio-intelligence|/compare-parts routes.
 * Do not treat these PNGs as proof that real routes render overflow-free.
 *
 * It does check documentElement.scrollWidth against the viewport width for
 * the fixture markup at 390px, 696px, and desktop.
 */
import { createRequire } from "node:module";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import http from "node:http";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const require = createRequire(path.join(root, "apps/web/package.json"));
const { chromium } = require("playwright");
const css = readFileSync(path.join(root, "apps/web/src/app/globals.css"), "utf8");
const outDir = path.join(root, "docs/evidence_ui_tables/screenshots");
mkdirSync(outDir, { recursive: true });

const designImpactBody = `
<main class="cv-main">
  <header class="cv-page-header"><div><div class="cv-eyebrow">Engineering</div>
  <h1>Design Impact</h1>
  <p class="cv-page-description">Trace how a component change affects saved BOMs.</p></div></header>
  <p class="cv-evidence-context">Based on saved analyses in this workspace</p>
  <div class="cv-grid-2 cv-grid-2--tables">
    <section class="cv-card pad cv-card--table">
      <h3 class="cv-card-title">Component catalog</h3>
      <p class="cv-card-subtitle">4 parts from saved analyses</p>
      <div class="cv-table-wrap cv-table-wrap--fit" style="margin-top:12px">
        <table class="cv-table cv-table--fit">
          <thead><tr><th>Part</th><th>Manufacturer</th><th>Lifecycle</th><th class="cv-num">Risk</th></tr></thead>
          <tbody>
            <tr><td data-label="Part"><strong>LM358DR</strong></td><td data-label="Manufacturer">TI</td><td data-label="Lifecycle">Active</td><td class="cv-num" data-label="Risk">Low</td></tr>
            <tr><td data-label="Part"><strong>AM29F010B-70EC</strong></td><td data-label="Manufacturer">AMD</td><td data-label="Lifecycle">NRND</td><td class="cv-num" data-label="Risk">High</td></tr>
            <tr><td data-label="Part"><strong>CRCW060310K0FKEA</strong></td><td data-label="Manufacturer">Vishay</td><td data-label="Lifecycle">Active</td><td class="cv-num" data-label="Risk">Low</td></tr>
            <tr><td data-label="Part"><strong>GRM188R71H104KA93D</strong></td><td data-label="Manufacturer">Murata</td><td data-label="Lifecycle">Active</td><td class="cv-num" data-label="Risk">Low</td></tr>
          </tbody>
        </table>
      </div>
    </section>
    <section class="cv-card pad cv-card--table">
      <h3 class="cv-card-title">Selected impact</h3>
      <p class="cv-card-subtitle">LM358DR</p>
      <dl class="cv-record-meta" style="margin-top:12px;grid-template-columns:1fr 1fr">
        <div class="cv-record-field"><dt>Lifecycle</dt><dd>Active</dd></div>
        <div class="cv-record-field"><dt>Risk</dt><dd>Low</dd></div>
      </dl>
      <h3 class="cv-card-title" style="margin-top:16px">Affected context</h3>
      <p class="cv-small-note">3 related rows</p>
    </section>
  </div>
</main>`;

const portfolioBody = `
<main class="cv-main">
  <header class="cv-page-header"><div><div class="cv-eyebrow">Engineering</div>
  <h1>Portfolio Intelligence</h1>
  <p class="cv-page-description">Cross-BOM health and shared components.</p></div></header>
  <p class="cv-evidence-context">Based on saved analyses in this workspace</p>
  <div class="cv-grid-2 cv-grid-2--tables">
    <section class="cv-card pad cv-card--table">
      <h3 class="cv-card-title">Analyses</h3>
      <div class="cv-table-wrap cv-table-wrap--fit" style="margin-top:12px">
        <table class="cv-table cv-table--fit">
          <thead><tr><th>File</th><th class="cv-num">Health</th><th class="cv-num">Parts</th><th class="cv-num">High</th></tr></thead>
          <tbody>
            <tr><td data-label="File"><strong>motor-controller.csv</strong></td><td class="cv-num" data-label="Health">82</td><td class="cv-num" data-label="Parts">48</td><td class="cv-num" data-label="High">3</td></tr>
            <tr><td data-label="File"><strong>power-board.xlsx</strong></td><td class="cv-num" data-label="Health">71</td><td class="cv-num" data-label="Parts">112</td><td class="cv-num" data-label="High">9</td></tr>
          </tbody>
        </table>
      </div>
    </section>
    <section class="cv-card pad cv-card--table">
      <h3 class="cv-card-title">Project health</h3>
      <div class="cv-table-wrap cv-table-wrap--fit" style="margin-top:12px">
        <table class="cv-table cv-table--fit">
          <thead><tr><th>Project</th><th class="cv-num">Health</th><th class="cv-num">Components</th><th class="cv-num">High-risk</th></tr></thead>
          <tbody>
            <tr><td data-label="Project"><strong>Drive Unit</strong></td><td class="cv-num" data-label="Health">82</td><td class="cv-num" data-label="Components">48</td><td class="cv-num" data-label="High-risk">3</td></tr>
            <tr><td data-label="Project"><strong>Power Stage</strong></td><td class="cv-num" data-label="Health">71</td><td class="cv-num" data-label="Components">112</td><td class="cv-num" data-label="High-risk">9</td></tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</main>`;

const compareBody = `
<main class="cv-main">
  <header class="cv-page-header"><div><div class="cv-eyebrow">Engineering</div>
  <h1>Compare Parts</h1></div></header>
  <div class="cv-decision-banner" role="note"><div>
    <strong>Evidence note</strong>
    <span>Offline catalog — incomplete evidence for this compare. Confirm manufacturer datasheets before approval.</span>
  </div></div>
</main>`;

function pageHtml(title, body) {
  const cleaned = css.replace(/@tailwind[^;]+;/g, "");
  return `<!doctype html><html><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>${title} (markup fixture)</title><style>${cleaned}</style></head>
<body data-capture-mode="markup-fixture">
<p style="margin:0;padding:8px 12px;background:#fff7ed;color:#9a3412;font:12px/1.4 system-ui">
  Markup fixture — not a live Next.js route. Overflow checks apply to this fixture only.
</p>
<div class="cv-shell" style="grid-template-columns:1fr">${body}</div>
</body></html>`;
}

const pages = {
  "/design-impact": pageHtml("Design Impact", designImpactBody),
  "/portfolio-intelligence": pageHtml("Portfolio", portfolioBody),
  "/compare-parts": pageHtml("Compare Parts", compareBody),
};

const viewports = [
  { label: "mobile_390", width: 390, height: 844 },
  { label: "tablet_696", width: 696, height: 900 },
  { label: "desktop", width: 1280, height: 900 },
];

const server = http.createServer((req, res) => {
  const html = pages[req.url?.split("?")[0] || ""];
  if (!html) {
    res.writeHead(404);
    res.end("not found");
    return;
  }
  res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
  res.end(html);
});

await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const { port } = server.address();
const browser = await chromium.launch();
const report = {
  mode: "markup-fixture",
  note: "Does not boot Next routes or the app shell. Overflow results are fixture-only.",
  captures: [],
};

for (const [route, prefix] of [
  ["/design-impact", "after_design_impact"],
  ["/portfolio-intelligence", "after_portfolio"],
  ["/compare-parts", "after_compare"],
]) {
  for (const vp of viewports) {
    const page = await browser.newPage({
      viewport: { width: vp.width, height: vp.height },
    });
    await page.goto(`http://127.0.0.1:${port}${route}`, { waitUntil: "networkidle" });
    const metrics = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
      bodyScrollWidth: document.body.scrollWidth,
    }));
    const overflow = metrics.scrollWidth > metrics.clientWidth + 1;
    const file =
      vp.label === "desktop"
        ? `${prefix}_desktop.png`
        : vp.label === "mobile_390"
          ? `${prefix}_mobile.png`
          : `${prefix}_${vp.label}.png`;
    await page.screenshot({ path: path.join(outDir, file), fullPage: true });
    report.captures.push({
      route,
      viewport: vp,
      file,
      ...metrics,
      overflow,
    });
    await page.close();
    if (overflow) {
      console.warn(`OVERFLOW fixture ${file}: scrollWidth=${metrics.scrollWidth} clientWidth=${metrics.clientWidth}`);
    }
  }
}

await browser.close();
server.close();
writeFileSync(path.join(outDir, "overflow_report.json"), JSON.stringify(report, null, 2));
const failed = report.captures.filter((c) => c.overflow);
console.log(
  `Markup-fixture capture complete (${report.captures.length} PNGs). Overflow failures: ${failed.length}`,
);
if (failed.length) process.exitCode = 1;
