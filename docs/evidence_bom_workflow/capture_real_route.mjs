/**
 * Capture signed-in /bom-analyzer workflow states from the real Next.js route
 * using synthetic sandbox fixtures. Labels synthetic sample data in the UI.
 */
import { createRequire } from "node:module";
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import http from "node:http";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const require = createRequire(path.join(root, "apps/web/package.json"));
const { chromium } = require("playwright");
const outDir = path.join(root, "docs/evidence_bom_workflow/screenshots");
mkdirSync(outDir, { recursive: true });

const API_PORT = process.env.CADIVOR_EVIDENCE_API_PORT || "8791";
const WEB_PORT = process.env.CADIVOR_EVIDENCE_WEB_PORT || "3005";
const API = process.env.CADIVOR_EVIDENCE_API || `http://127.0.0.1:${API_PORT}`;
const WEB = process.env.CADIVOR_EVIDENCE_WEB || `http://127.0.0.1:${WEB_PORT}`;
const EMAIL = "sandbox-a@cadivor.test";
const PASSWORD = "CadivorSandbox!a";
const FIXTURE = path.join(root, "tests/fixtures/synthetic_bom_25parts.csv");
const VENV_PYTHON =
  process.env.CADIVOR_EVIDENCE_PYTHON ||
  "/Users/sergekashambala/Documents/Businesses/bom-risk-checker-prod-followup/.venv312/bin/python";

const children = [];
const shots = [];
const log = (...args) => console.log(new Date().toISOString(), ...args);

function wait(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function httpOk(url, timeoutMs = 120000) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const tick = () => {
      const req = http.get(url, (res) => {
        res.resume();
        if (res.statusCode && res.statusCode < 500) return resolve(true);
        if (Date.now() - start > timeoutMs) return reject(new Error(`timeout ${url}`));
        setTimeout(tick, 500);
      });
      req.on("error", () => {
        if (Date.now() - start > timeoutMs) return reject(new Error(`timeout ${url}`));
        setTimeout(tick, 500);
      });
    };
    tick();
  });
}

async function apiLogin() {
  const res = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`login failed ${res.status}: ${text}`);
  return JSON.parse(text);
}

function spawnLogged(cmd, args, opts, logName) {
  const child = spawn(cmd, args, { ...opts, stdio: ["ignore", "pipe", "pipe"] });
  children.push(child);
  const sink = (buf) => {
    try {
      writeFileSync(path.join(outDir, logName), buf.toString(), { flag: "a" });
    } catch {}
  };
  child.stdout.on("data", sink);
  child.stderr.on("data", sink);
  child.on("exit", (code) => log(logName, "exit", code));
  return child;
}

function startApi() {
  writeFileSync(path.join(outDir, "api.log"), "");
  return spawnLogged(
    VENV_PYTHON,
    [path.join(root, "docs/evidence_bom_workflow/run_evidence_api.py")],
    {
      cwd: root,
      env: {
        ...process.env,
        PYTHONPATH: root,
        CADIVOR_SANDBOX_AUTH_SECRET: "evidence-sandbox-auth-secret-key",
        CADIVOR_ALLOW_EPHEMERAL_FILE_STORE: "1",
        CADIVOR_ALLOW_SANDBOX_JWT: "1",
        PORT: String(API_PORT),
      },
    },
    "api.log",
  );
}

function startWeb() {
  writeFileSync(path.join(outDir, "web.log"), "");
  return spawnLogged(
    "npm",
    ["run", "dev", "--", "-p", String(WEB_PORT), "-H", "127.0.0.1"],
    {
      cwd: path.join(root, "apps/web"),
      env: {
        ...process.env,
        NEXT_PUBLIC_API_BASE: API,
        NEXT_PUBLIC_ALLOW_LOCAL_API: "1",
        NEXT_PUBLIC_SUPABASE_URL: "",
        NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: "",
        NEXT_PUBLIC_SUPABASE_ANON_KEY: "",
      },
    },
    "web.log",
  );
}

async function shot(page, name) {
  const file = path.join(outDir, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  shots.push({ name, file: path.relative(root, file) });
  log("captured", name);
}

async function injectSession(page, session) {
  await page.addInitScript((sess) => {
    localStorage.setItem("cadivor_next_session", JSON.stringify(sess));
  }, {
    access_token: session.access_token,
    email: session.email || EMAIL,
    workspace: session.workspace || "Sandbox Workspace A",
    workspace_id: session.workspace_id || "ws-sandbox-a",
    user_id: session.user_id || "user-sandbox-a",
    plan: session.plan || "Trial",
    mode: session.mode || "sandbox-jwt",
  });
}

async function capturePair(page, basename) {
  await page.setViewportSize({ width: 1440, height: 960 });
  await wait(300);
  await shot(page, `${basename}_desktop`);
  await page.setViewportSize({ width: 390, height: 844 });
  await wait(300);
  await shot(page, `${basename}_mobile`);
  await page.setViewportSize({ width: 1440, height: 960 });
}

async function dumpFailure(page, label) {
  const html = path.join(outDir, `failure_${label}.html`);
  writeFileSync(html, await page.content());
  await page.screenshot({ path: path.join(outDir, `failure_${label}.png`), fullPage: true }).catch(() => {});
  log("failure dump", label, html);
}

async function main() {
  if (!existsSync(FIXTURE)) throw new Error(`missing fixture ${FIXTURE}`);

  try {
    await httpOk(`${API}/health`, 2000);
    log("API already up", API);
  } catch {
    log("starting API on", API);
    startApi();
    await httpOk(`${API}/health`);
    log("API ready");
  }

  try {
    await httpOk(WEB, 2000);
    log("Web already up", WEB);
  } catch {
    log("starting Next on", WEB);
    startWeb();
    await httpOk(WEB);
    log("Web ready");
  }

  const session = await apiLogin();
  log("logged in", session.email || EMAIL);

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  page.on("console", (msg) => {
    if (["error", "warning"].includes(msg.type())) log("browser", msg.type(), msg.text());
  });
  page.on("pageerror", (err) => log("pageerror", err.message));
  await injectSession(page, session);

  await page.goto(`${WEB}/bom-analyzer`, { waitUntil: "networkidle" });
  await page.waitForSelector('[data-testid="synthetic-sample-label"]', { timeout: 30000 });
  await capturePair(page, "real_initial");

  // Sidebar nav while idle
  await page.goto(`${WEB}/settings`, { waitUntil: "domcontentloaded" });
  await wait(400);
  await page.goto(`${WEB}/bom-analyzer`, { waitUntil: "networkidle" });

  // Upload synthetic fixture
  await page.locator('input[type="file"]').first().setInputFiles(FIXTURE);
  try {
    await page.waitForSelector("text=Ready to analyze", { timeout: 60000 });
  } catch (err) {
    await dumpFailure(page, "ready");
    throw err;
  }
  const current = (await page.locator(".cv-bom-workflow-current strong").textContent()) || "";
  if (/^Analyzing$/i.test(current.trim())) {
    throw new Error(`ready state incorrectly shows Analyzing as current: ${current}`);
  }
  await capturePair(page, "real_ready");

  await page.getByRole("button", { name: /Analyze BOM/i }).first().click();
  try {
    await page.waitForSelector("text=/Analysis in progress|Analyzing is current|Current stage[\\s\\S]*Analyzing/i", {
      timeout: 20000,
    });
  } catch (err) {
    await dumpFailure(page, "analyzing");
    throw err;
  }
  await capturePair(page, "real_analyzing");

  // Leave and return during in-flight analysis
  await page.goto(`${WEB}/settings`, { waitUntil: "domcontentloaded" });
  await wait(500);
  await page.goto(`${WEB}/bom-analyzer`, { waitUntil: "networkidle" });
  await capturePair(page, "real_resume_inflight_or_done");

  try {
    await page.waitForSelector("text=Open saved risk report", { timeout: 180000 });
  } catch (err) {
    await dumpFailure(page, "success");
    throw err;
  }
  await capturePair(page, "real_success");

  await page.getByRole("link", { name: /Open saved risk report/i }).first().click();
  await page.waitForURL(/\/reports\//, { timeout: 60000 });
  await wait(800);
  await capturePair(page, "real_risks");

  // Evidence: mark via scrolling evidence and optional progress helper on page
  await page.evaluate(() => {
    const el = document.querySelector("#report-evidence") || document.body;
    el.scrollIntoView({ behavior: "instant", block: "center" });
  });
  await wait(400);
  await capturePair(page, "real_evidence");

  // Decision queue
  await page.goto(`${WEB}/engineering-decisions`, { waitUntil: "networkidle" });
  await wait(600);
  await capturePair(page, "real_decision");

  const analysisId = await page.evaluate(() => {
    for (const k of Object.keys(localStorage)) {
      if (!k.includes("cadivor_next_last_analysis")) continue;
      try {
        const v = JSON.parse(localStorage.getItem(k) || "{}");
        if (v.analysis_id) return v.analysis_id;
      } catch {}
    }
    return "";
  });
  await page.goto(
    `${WEB}/monitoring${analysisId ? `?analysis_id=${encodeURIComponent(analysisId)}` : ""}`,
    { waitUntil: "networkidle" },
  );
  await wait(800);
  await capturePair(page, "real_monitor");

  // Validation error path
  await page.goto(`${WEB}/bom-analyzer`, { waitUntil: "networkidle" });
  const bad = path.join(outDir, "bad_sample.csv");
  writeFileSync(bad, "Description,Qty\nResistor,2\n");
  await page.locator('input[type="file"]').first().setInputFiles(bad);
  await page.waitForSelector("text=/Fix file|validation|required|Analysis stays disabled/i", {
    timeout: 30000,
  });
  await capturePair(page, "real_validation_error");

  writeFileSync(
    path.join(outDir, "real_route_manifest.json"),
    JSON.stringify(
      {
        captured_at: new Date().toISOString(),
        api: API,
        web: WEB,
        email: EMAIL,
        fixture: path.relative(root, FIXTURE),
        synthetic_label: true,
        analysis_id: analysisId,
        shots,
      },
      null,
      2,
    ),
  );

  await browser.close();
  log("done", shots.length, "screenshots");
}

function shutdown() {
  for (const child of children) {
    try {
      child.kill("SIGTERM");
    } catch {}
  }
}

process.on("exit", shutdown);
process.on("SIGINT", () => {
  shutdown();
  process.exit(130);
});

main()
  .then(() => {
    shutdown();
    process.exit(0);
  })
  .catch((err) => {
    console.error(err);
    shutdown();
    process.exit(1);
  });
