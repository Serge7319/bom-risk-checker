#!/usr/bin/env node
/**
 * Controlled Priority 1 production smoke for a dedicated Cadivor QA workspace.
 *
 * Creates one clearly named synthetic analysis and one Hold for review decision.
 * It never approves an alternate, opts in to email, sends email, refreshes
 * supplier data, or changes monitoring preferences. Use --free-audit to also
 * run the public five-result audit; that path does not submit the email form.
 */
import { randomBytes } from "node:crypto";
import { stat } from "node:fs/promises";

const BASE_URL = (process.env.CADIVOR_P1_BASE_URL || "https://app.cadivor.com").replace(/\/$/, "");
const QA_EMAIL = (process.env.CADIVOR_P1_QA_EMAIL || "").trim();
const QA_PASSWORD = process.env.CADIVOR_P1_QA_PASSWORD || "";
const QA_WORKSPACE_ID = (process.env.CADIVOR_P1_QA_WORKSPACE_ID || "").trim();
const WRITE_ACK = process.env.CADIVOR_P1_WRITE_ACK || "";
const RUN_FREE_AUDIT = process.argv.includes("--free-audit");
const EXPECTED_WRITE_ACK = "I_ACKNOWLEDGE_SYNTHETIC_WRITES_TO_THE_QA_WORKSPACE";

const checks = [];
let stage = "preflight";

function record(name, detail = {}) {
  checks.push({ name, status: "passed", ...detail });
}

function fail(name, error) {
  const safeMessage = error instanceof Error ? error.message : "Smoke step failed.";
  checks.push({ name, status: "failed", detail: safeMessage.slice(0, 240) });
  throw error;
}

function assertPreflight() {
  const url = new URL(BASE_URL);
  if (url.origin !== "https://app.cadivor.com") {
    throw new Error("Production smoke is restricted to https://app.cadivor.com.");
  }
  if (!QA_EMAIL || !QA_PASSWORD || !QA_WORKSPACE_ID) {
    throw new Error(
      "Set CADIVOR_P1_QA_EMAIL, CADIVOR_P1_QA_PASSWORD, and CADIVOR_P1_QA_WORKSPACE_ID for a dedicated QA account.",
    );
  }
  if (WRITE_ACK !== EXPECTED_WRITE_ACK) {
    throw new Error(
      `Set CADIVOR_P1_WRITE_ACK=${EXPECTED_WRITE_ACK} only when the account belongs to a dedicated QA workspace.`,
    );
  }
}

function syntheticCsv(filename) {
  const rows = [
    ["MPN", "Manufacturer", "Description", "Quantity"],
    ["LM358DR", "Texas Instruments", "Dual operational amplifier", "2"],
    ["NE555P", "Texas Instruments", "Timer IC", "1"],
    ["LM7805CT", "Texas Instruments", "5 V linear regulator", "1"],
    ["STM32F103C8T6", "STMicroelectronics", "32-bit microcontroller", "1"],
    ["RC0603FR-0710KL", "YAGEO", "10 kOhm resistor", "4"],
    ["GRM188R71H104KA93D", "Murata Electronics", "100 nF capacitor", "6"],
  ];
  const csv = rows.map((row) => row.map((value) => `"${value.replaceAll('"', '""')}"`).join(",")).join("\n");
  return { name: filename, mimeType: "text/csv", buffer: Buffer.from(`${csv}\n`, "utf8") };
}

async function waitForEither(page, selectors, timeout = 120000) {
  await page.waitForFunction(
    (items) => items.some((selector) => document.querySelector(selector)),
    selectors,
    { timeout },
  );
}

async function run() {
  assertPreflight();
  const { chromium } = await import("playwright");
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ acceptDownloads: true });
  const page = await context.newPage();
  const runTag = `${new Date().toISOString().replace(/\D/g, "").slice(0, 14)}-${randomBytes(2).toString("hex")}`;
  const projectName = `Cadivor QA Priority 1 ${runTag}`;
  const bomName = `Synthetic smoke ${runTag}`;

  try {
    stage = "sign_in";
    await page.goto(`${BASE_URL}/login`, { waitUntil: "domcontentloaded" });
    await page.getByLabel("Email", { exact: true }).fill(QA_EMAIL);
    await page.getByLabel("Password", { exact: true }).fill(QA_PASSWORD);
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    await page.waitForURL((url) => url.pathname !== "/login", { timeout: 30000 });

    const session = await page.evaluate(() => {
      try {
        return JSON.parse(window.localStorage.getItem("cadivor_next_session") || "null");
      } catch {
        return null;
      }
    });
    if (!session?.workspace_id || session.workspace_id !== QA_WORKSPACE_ID) {
      throw new Error("Signed-in workspace does not match CADIVOR_P1_QA_WORKSPACE_ID; no test data was created.");
    }
    record("sign_in_and_qa_workspace_guard");

    if (RUN_FREE_AUDIT) {
      stage = "free_bom_audit";
      await page.goto(`${BASE_URL}/public-bom-audit?embed=true&qa_smoke=1`, { waitUntil: "domcontentloaded" });
      await page.getByTestId("public-bom-run-audit").waitFor({ state: "visible", timeout: 30000 });
      await page.locator('input[type="file"]').first().setInputFiles(syntheticCsv(`p1-free-audit-${runTag}.csv`));
      const runAudit = page.getByTestId("public-bom-run-audit");
      if (await runAudit.isDisabled()) {
        throw new Error("Free audit is gated for this QA account. Confirm its verified email is on CADIVOR_PUBLIC_BOM_QA_EMAILS.");
      }
      await runAudit.click();
      await page.getByRole("heading", { name: "Preliminary BOM audit" }).waitFor({ timeout: 180000 });
      const freeAuditText = await page.locator(".cv-public-stress-panel").innerText();
      if (!/first 5 results/i.test(freeAuditText) || !/not checked yet/i.test(freeAuditText)) {
        throw new Error("Free audit did not show the expected five-result preview and remaining-component notice.");
      }
      record("free_audit_five_result_preview", { emailSubmitted: false });
    }

    stage = "bom_analysis";
    await page.goto(`${BASE_URL}/bom-analyzer`, { waitUntil: "domcontentloaded" });
    await page.getByLabel("Project", { exact: true }).fill(projectName);
    await page.getByLabel("BOM name", { exact: true }).fill(bomName);
    await page.getByLabel("Revision", { exact: true }).fill("A");
    await page.locator('input[type="file"]').first().setInputFiles(syntheticCsv(`${bomName}.csv`));
    await page.getByText("Ready to analyze", { exact: false }).waitFor({ timeout: 60000 });
    await page.getByRole("button", { name: "Analyze BOM", exact: true }).click();
    await page.getByRole("link", { name: /Open saved risk report/i }).waitFor({ timeout: 240000 });
    record("synthetic_bom_analyzed_and_saved", { uniqueParts: 6 });

    stage = "report_exports";
    await page.getByRole("link", { name: /Open saved risk report/i }).click();
    await page.waitForURL(/\/reports\/[^/]+$/, { timeout: 30000 });
    await page.locator(".cv-report-export").waitFor({ state: "visible", timeout: 30000 });
    const analysisId = new URL(page.url()).pathname.split("/").filter(Boolean).at(-1);
    if (!analysisId) throw new Error("Saved report route did not include an analysis selector.");
    for (const [label, button] of [
      ["pdf", "Download PDF"],
      ["xlsx", "Download Excel"],
      ["csv", "Download CSV audit"],
    ]) {
      const downloadPromise = page.waitForEvent("download", { timeout: 30000 });
      await page.getByRole("button", { name: button, exact: true }).click();
      const download = await downloadPromise;
      const downloadedPath = await download.path();
      if (!downloadedPath || (await stat(downloadedPath)).size < 100) {
        throw new Error(`${label.toUpperCase()} export was empty or unavailable.`);
      }
      record(`export_${label}`);
    }

    stage = "replacement_search";
    const replacementUrl = new URL("/find-replacement", BASE_URL);
    replacementUrl.searchParams.set("analysis_id", analysisId);
    replacementUrl.searchParams.set("mpn", "LM358DR");
    replacementUrl.searchParams.set("manufacturer", "Texas Instruments");
    await page.goto(replacementUrl.toString(), { waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: "Find candidates", exact: true }).click();
    await page.getByText("Original part", { exact: true }).waitFor({ timeout: 180000 });
    const providerOutcomeVisible = await page.getByTestId("replacement-provider-status").isVisible().catch(() => false);
    record("replacement_search_rendered", { providerOutcomeVisible });

    stage = "compare_and_decision";
    const compareUrl = new URL("/compare-parts", BASE_URL);
    compareUrl.searchParams.set("analysis_id", analysisId);
    compareUrl.searchParams.set("part_a", "LM358DR");
    compareUrl.searchParams.set("manufacturer_a", "Texas Instruments");
    compareUrl.searchParams.set("part_b", "LM358N");
    compareUrl.searchParams.set("manufacturer_b", "Texas Instruments");
    await page.goto(compareUrl.toString(), { waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: "Compare parts", exact: true }).click();
    await page.locator(".cv-compare-screening").waitFor({ timeout: 180000 });
    const finding = (await page.locator(".cv-compare-screening strong").innerText()).trim();
    if (!finding) throw new Error("Comparison completed without a user-facing finding.");
    await page.getByRole("button", { name: /Record a decision/i }).click();
    const dialog = page.getByRole("dialog", { name: "Record an engineering decision" });
    await dialog.waitFor({ state: "visible", timeout: 15000 });
    await dialog.locator("#decision-bom-scope").selectOption(analysisId);
    await dialog.getByLabel("Decision", { exact: true }).selectOption("hold_for_review");
    await dialog.getByLabel("Reviewer", { exact: true }).fill("Cadivor QA smoke");
    await dialog.getByLabel("Rationale", { exact: true }).fill("Synthetic QA comparison; hold pending engineering validation.");
    await dialog.getByRole("button", { name: "Record decision", exact: true }).click();
    await page.getByText(/Decision recorded for/i).waitFor({ timeout: 30000 });
    record("comparison_and_hold_for_review_decision", { finding });

    stage = "monitoring_read_only";
    const monitorUrl = new URL("/monitoring", BASE_URL);
    monitorUrl.searchParams.set("analysis_id", analysisId);
    await page.goto(monitorUrl.toString(), { waitUntil: "domcontentloaded" });
    await page.getByRole("region", { name: "Monitoring freshness" }).waitFor({ timeout: 60000 });
    await page.getByRole("region", { name: "Monitoring preferences" }).waitFor({ timeout: 60000 });
    record("monitoring_page_read_only", { supplierRefreshClicked: false, emailPreferenceChanged: false });

    console.log(JSON.stringify({ ok: true, base: BASE_URL, runTag, checks }, null, 2));
  } finally {
    await context.close().catch(() => undefined);
    await browser.close().catch(() => undefined);
  }
}

try {
  assertPreflight();
} catch (error) {
  console.error(JSON.stringify({ ok: false, blocked: true, stage, detail: error.message }, null, 2));
  process.exit(2);
}

run().catch((error) => {
  console.error(JSON.stringify({ ok: false, stage, checks, detail: error instanceof Error ? error.message.slice(0, 300) : "Smoke failed." }, null, 2));
  process.exitCode = 1;
});
