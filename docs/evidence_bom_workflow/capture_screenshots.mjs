/**
 * Capture BOM analyzer guided-workflow states (desktop + mobile).
 * Serves static HTML with live globals.css — no invented stage percentages.
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
const outDir = path.join(root, "docs/evidence_bom_workflow/screenshots");
mkdirSync(outDir, { recursive: true });

function stage(name, status) {
  return `<li class="cv-bom-stage is-${status}${status === "current" ? " is-current" : ""}" ${
    status === "current" ? 'aria-current="step"' : ""
  }>
    <span class="cv-bom-stage-name">${name}</span>
    <span class="cv-bom-stage-status">${status}</span>
  </li>`;
}

function stepper({ analysis, engineering, current, explain, next, indeterminate = false }) {
  return `
  <section class="cv-bom-workflow" aria-label="BOM workflow progress">
    <div class="cv-bom-workflow-groups">
      <div class="cv-bom-workflow-group">
        <p class="cv-bom-workflow-group-label">Analysis</p>
        <ol class="cv-bom-stages" aria-label="Analysis stages">${analysis}</ol>
      </div>
      <div class="cv-bom-workflow-group">
        <p class="cv-bom-workflow-group-label">Engineering workflow</p>
        <ol class="cv-bom-stages cv-bom-stages--engineering" aria-label="Engineering stages">${engineering}</ol>
      </div>
    </div>
    <div class="cv-bom-progress${indeterminate ? " is-indeterminate" : ""}" role="progressbar" aria-valuetext="${current}">
      <i></i>
    </div>
    <div class="cv-bom-workflow-status" aria-live="polite">
      <p class="cv-bom-workflow-current">
        <span class="cv-bom-workflow-current-label">Current stage</span>
        <strong>${current}</strong>
        <span class="cv-bom-stage-pill is-current">Current</span>
      </p>
      <p class="cv-bom-workflow-explain">${explain}</p>
      <p class="cv-bom-workflow-next"><span>Next useful action</span>${next}</p>
    </div>
  </section>`;
}

function shell(title, body) {
  return `
<main class="cv-main">
  <header class="cv-page-header"><div>
    <div class="cv-eyebrow">Engineering</div>
    <h1>BOM Analyzer</h1>
    <p class="cv-page-description">Guided analysis and review without locking other navigation.</p>
  </div></header>
  <p class="cv-bom-guidance-note" role="note">
    This workflow guides analysis and review. Sidebar navigation and other tools stay available — leave anytime and resume this draft later.
  </p>
  <div class="cv-bom-workspace-grid">
    <section class="cv-card pad cv-bom-create-card">
      <div class="cv-bom-card-heading">
        <div>
          <h2 class="cv-card-title">Create a BOM analysis</h2>
          <p class="cv-card-subtitle">${title}</p>
        </div>
        <span class="cv-bom-step">Guided stages</span>
      </div>
      ${body}
    </section>
    <aside class="cv-bom-side-cards">
      <section class="cv-card pad cv-bom-side-card cv-bom-recent-card">
        <div class="cv-bom-recent-heading">
          <div>
            <h2 class="cv-card-title">Recent analyses</h2>
            <p class="cv-card-subtitle">Resume a saved analysis at Risks or later.</p>
          </div>
          <a href="#" class="cv-bom-view-all">View all</a>
        </div>
        <ul class="cv-bom-recent-list">
          <li>
            <a class="cv-bom-recent-link" href="#">
              <span class="cv-bom-recent-copy">
                <strong>Motor controller · rev A</strong>
                <small>48 parts · updated today</small>
              </span>
              <span class="cv-button small">Resume</span>
            </a>
          </li>
        </ul>
      </section>
    </aside>
  </div>
</main>`;
}

const states = {
  initial: shell(
    "Add project details, upload the file, then review validation before analysis.",
    `
    ${stepper({
      analysis:
        stage("Received", "current") +
        stage("Validating", "blocked") +
        stage("Analyzing", "blocked"),
      engineering:
        stage("Risks", "blocked") +
        stage("Evidence", "blocked") +
        stage("Decision", "blocked") +
        stage("Monitor", "blocked"),
      current: "Received",
      explain: "Choose a CSV or XLSX BOM to begin. You can leave anytime and resume later.",
      next: "Select a BOM file.",
    })}
    <div class="cv-upload-zone cv-bom-upload-zone cv-bom-dropzone">
      <h3>New analysis</h3>
      <p>Upload a CSV or XLSX BOM.</p>
      <label class="cv-bom-file-picker"><span>Choose file</span><small>CSV or XLSX · up to 10 MB</small></label>
    </div>
    <div class="cv-bom-analyze-actions cv-bom-primary-cta">
      <button type="button" class="cv-button primary">Choose BOM file</button>
    </div>`,
  ),
  validation: shell(
    "Validation preview after file selection.",
    `
    ${stepper({
      analysis:
        stage("Received", "complete") +
        stage("Validating", "current") +
        stage("Analyzing", "blocked"),
      engineering:
        stage("Risks", "blocked") +
        stage("Evidence", "blocked") +
        stage("Decision", "blocked") +
        stage("Monitor", "blocked"),
      current: "Validating",
      explain: "Validated 2 parts across 2 rows.",
      next: "Run analysis when ready.",
    })}
    <section class="cv-bom-validation">
      <div class="cv-bom-validation-heading">
        <h3 class="cv-card-title">Validation preview</h3>
        <p class="cv-card-subtitle">Uses the same parse path as analysis.</p>
      </div>
      <dl class="cv-bom-validation-stats">
        <div><dt>Rows</dt><dd>2</dd></div>
        <div><dt>Unique parts</dt><dd>2</dd></div>
        <div><dt>Columns detected</dt><dd>3</dd></div>
        <div><dt>Ready to analyze</dt><dd>Yes</dd></div>
      </dl>
      <div class="cv-bom-column-list">
        <p class="cv-small-note">Detected columns</p>
        <ul>
          <li><strong>MPN</strong><span>→ mpn</span></li>
          <li><strong>Quantity</strong><span>→ quantity</span></li>
          <li><strong>Manufacturer</strong><span>→ manufacturer</span></li>
        </ul>
      </div>
    </section>
    <div class="cv-bom-analyze-actions cv-bom-primary-cta">
      <button type="button" class="cv-button primary">Analyze BOM</button>
    </div>`,
  ),
  progress: shell(
    "Analysis request in progress — indeterminate indicator only.",
    `
    ${stepper({
      analysis:
        stage("Received", "complete") +
        stage("Validating", "complete") +
        stage("Analyzing", "current"),
      engineering:
        stage("Risks", "blocked") +
        stage("Evidence", "blocked") +
        stage("Decision", "blocked") +
        stage("Monitor", "blocked"),
      current: "Analyzing",
      explain: "Running the existing BOM risk analysis and saving the report.",
      next: "Stay on this page or leave — the request continues in this browser session.",
      indeterminate: true,
    })}
    <p class="cv-small-note cv-bom-background-note" role="status">
      Analysis continues in this browser session while you use other pages. Return here to see status.
    </p>
    <div class="cv-bom-analyze-actions cv-bom-primary-cta">
      <button type="button" class="cv-button primary" disabled>Analysis in progress…</button>
    </div>`,
  ),
  completed: shell(
    "Analysis complete — Risks is the current review stage.",
    `
    ${stepper({
      analysis:
        stage("Received", "complete") +
        stage("Validating", "complete") +
        stage("Analyzing", "complete"),
      engineering:
        stage("Risks", "current") +
        stage("Evidence", "blocked") +
        stage("Decision", "blocked") +
        stage("Monitor", "blocked"),
      current: "Risks",
      explain: "Review high and medium risks in the saved report.",
      next: "Open the saved report and review risk counts.",
    })}
    <div class="cv-bom-success" role="status">
      <p class="cv-bom-summary">Saved Motor controller · 48 parts · health 82</p>
      <p class="cv-small-note">Received, Validating, and Analyzing are complete. Continue with Risks in the saved report.</p>
    </div>
    <div class="cv-bom-analyze-actions cv-bom-primary-cta">
      <a class="cv-button primary" href="#">Open saved risk report</a>
    </div>`,
  ),
  error: shell(
    "Analysis error keeps the selected file and project details.",
    `
    ${stepper({
      analysis:
        stage("Received", "complete") +
        stage("Validating", "complete") +
        stage("Analyzing", "error"),
      engineering:
        stage("Risks", "blocked") +
        stage("Evidence", "blocked") +
        stage("Decision", "blocked") +
        stage("Monitor", "blocked"),
      current: "Analyzing",
      explain: "Analysis did not finish. Your file and project details are still here.",
      next: "Start analysis after validation passes.",
    })}
    <div class="cv-error" role="alert">
      Supplier connectors timed out for this workspace.
      <p class="cv-small-note" style="margin-top:8px">Your selected file and project details are still available. Fix the issue, then retry analysis.</p>
    </div>
    <div class="cv-bom-analyze-actions cv-bom-primary-cta">
      <button type="button" class="cv-button primary">Retry analysis</button>
    </div>`,
  ),
};

function pageHtml(title, body) {
  const cleaned = css.replace(/@tailwind[^;]+;/g, "");
  return `<!doctype html><html><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>${title}</title><style>${cleaned}</style></head>
<body><div class="cv-shell" style="grid-template-columns:1fr">${body}</div></body></html>`;
}

const pages = Object.fromEntries(
  Object.entries(states).map(([key, body]) => [`/${key}`, pageHtml(key, body)]),
);

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
const manifest = [];

for (const key of Object.keys(states)) {
  for (const [label, viewport] of [
    ["desktop", { width: 1440, height: 1100 }],
    ["mobile", { width: 390, height: 900 }],
  ]) {
    const page = await browser.newPage({ viewport });
    await page.goto(`http://127.0.0.1:${port}/${key}`, { waitUntil: "networkidle" });
    const file = `${key}_${label}.png`;
    await page.screenshot({ path: path.join(outDir, file), fullPage: true });
    writeFileSync(path.join(outDir, `${key}_${label}.html`), pages[`/${key}`]);
    manifest.push(file);
    await page.close();
  }
}

await browser.close();
server.close();
writeFileSync(path.join(outDir, "manifest.json"), JSON.stringify(manifest, null, 2));
console.log(`Wrote ${manifest.length} screenshots to ${outDir}`);
