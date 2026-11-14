#!/usr/bin/env node
/**
 * Signed-out Next.js app preview smoke for /public-bom-audit.
 * Requires PLAYWRIGHT against a running Next app (not Cloudflare Pages marketing).
 */
import { chromium } from "playwright";
import { createWriteStream } from "node:fs";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const BASE =
  (process.env.PUBLIC_BOM_APP_PREVIEW_URL || "http://127.0.0.1:3000").replace(
    /\/$/,
    "",
  );
const OUT_DIR = process.env.PUBLIC_BOM_SMOKE_OUT || ".evidence_ui/public_bom_audit_smoke";

async function main() {
  await mkdir(OUT_DIR, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const logPath = path.join(OUT_DIR, "smoke.log");
  const log = createWriteStream(logPath, { flags: "w" });
  const note = (msg) => {
    log.write(`${msg}\n`);
    console.log(msg);
  };

  const results = {
    base: BASE,
    statusLoadingSeen: false,
    statusEnabledUpload: false,
    auditUploadOk: false,
    leadSubmitOk: false,
    statusErrorPath: false,
    anonymousTurnstileBlocksSubmit: false,
    qaSessionSubmitsWithoutToken: false,
    normalSignedInStillNeedsTurnstile: false,
    clientQaFlagDoesNotBypass: false,
  };

  const csv =
    "MPN,Qty,Manufacturer\nLM358DR,2,Texas Instruments\nMCP2551-I/SN,1,Microchip\n";

  try {
    // 1) Normal enabled flow: loading then upload + lead.
    await page.goto(`${BASE}/public-bom-audit`, { waitUntil: "domcontentloaded" });
    const loading = page.getByTestId("public-bom-status-loading");
    results.statusLoadingSeen = await loading
      .waitFor({ state: "visible", timeout: 3000 })
      .then(() => true)
      .catch(() => false);

    await page.getByTestId("public-bom-run-audit").waitFor({
      state: "visible",
      timeout: 15000,
    });
    results.statusEnabledUpload = true;

    await page.locator('input[type="file"]').setInputFiles({
      name: "preview-bom.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(csv, "utf8"),
    });
    await page.getByTestId("public-bom-run-audit").click();
    await page.getByText("Preliminary BOM audit").waitFor({ timeout: 15000 });
    results.auditUploadOk = true;

    await page.locator('input[type="email"]').fill("preview@example.com");
    await page.locator('input[type="checkbox"]').check();
    await page.getByRole("button", { name: "Email my full report" }).click();
    await page
      .getByText("Check preview@example.com for your Cadivor verification email")
      .waitFor({ timeout: 15000 });
    results.leadSubmitOk = true;

    // 2) Turnstile three cases via server qa_verified (never client QA flag).
    await page.unroute("**/api/public/bom-stress/status").catch(() => undefined);
    await page.route("**/api/public/bom-stress/status", async (route) => {
      const auth = (route.request().headers()["authorization"] || "").toLowerCase();
      const qaVerified = auth.includes("qa-allowlisted-smoke-token");
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          enabled: true,
          turnstile_required: true,
          qa_verified: qaVerified,
        }),
      });
    });
    await page.goto(`${BASE}/public-bom-audit?embed=true&qa_smoke=1`, {
      waitUntil: "domcontentloaded",
    });
    await page.getByTestId("public-bom-run-audit").waitFor({
      state: "visible",
      timeout: 15000,
    });
    await page.locator('input[type="file"]').setInputFiles({
      name: "qa-smoke.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(csv, "utf8"),
    });
    const anonDisabled = await page
      .getByTestId("public-bom-run-audit")
      .isDisabled();
    results.anonymousTurnstileBlocksSubmit = anonDisabled;
    if (!anonDisabled) {
      throw new Error("Anonymous submit stayed enabled without Turnstile token");
    }

    // Client QA flag / query must not unlock Turnstile.
    await page.goto(
      `${BASE}/public-bom-audit?embed=true&qa_mode=1&qa_verified=true`,
      { waitUntil: "domcontentloaded" },
    );
    await page.getByTestId("public-bom-run-audit").waitFor({
      state: "visible",
      timeout: 15000,
    });
    await page.locator('input[type="file"]').setInputFiles({
      name: "flag-smoke.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(csv, "utf8"),
    });
    const flagStillBlocked = await page
      .getByTestId("public-bom-run-audit")
      .isDisabled();
    results.clientQaFlagDoesNotBypass = flagStillBlocked;
    if (!flagStillBlocked) {
      throw new Error("Client QA query flag bypassed Turnstile");
    }

    // Confirmed allowlisted QA: status returns qa_verified → submit without token.
    await page.evaluate(() => {
      window.localStorage.setItem(
        "cadivor_next_session",
        JSON.stringify({
          access_token: "qa-allowlisted-smoke-token",
          email: "qa@company.com",
          user_id: "qa-user",
        }),
      );
    });
    await page.goto(`${BASE}/public-bom-audit?embed=true&qa_smoke=1`, {
      waitUntil: "domcontentloaded",
    });
    await page.getByTestId("public-bom-run-audit").waitFor({
      state: "visible",
      timeout: 15000,
    });
    await page.locator('input[type="file"]').setInputFiles({
      name: "qa-smoke.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(csv, "utf8"),
    });
    const qaEnabled = !(await page.getByTestId("public-bom-run-audit").isDisabled());
    if (!qaEnabled) {
      throw new Error("QA-verified submit stayed disabled without Turnstile token");
    }

    let sawQaAudit = false;
    await page.route("**/api/public/bom-stress/audit", async (route) => {
      const auth = (route.request().headers()["authorization"] || "").toLowerCase();
      if (auth.includes("qa-allowlisted-smoke-token")) {
        sawQaAudit = true;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            ok: true,
            id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            filename: "qa-smoke.csv",
            row_count: 2,
            preview: [],
            remaining_count: 0,
            qa_mode: true,
            full_enriched: false,
          }),
        });
        return;
      }
      await route.fulfill({
        status: 400,
        contentType: "application/json",
        body: JSON.stringify({
          detail: "Complete the security check and try again.",
        }),
      });
    });

    await page.getByTestId("public-bom-run-audit").click();
    await page.getByText("Preliminary BOM audit").waitFor({ timeout: 15000 });
    results.qaSessionSubmitsWithoutToken = sawQaAudit;
    if (!sawQaAudit) {
      throw new Error("QA session did not submit audit without Turnstile token");
    }

    // Signed-in non-QA: status qa_verified=false → Turnstile still required.
    await page.evaluate(() => {
      window.localStorage.setItem(
        "cadivor_next_session",
        JSON.stringify({
          access_token: "normal-user-smoke-token",
          email: "user@company.com",
          user_id: "normal-user",
        }),
      );
    });
    await page.goto(`${BASE}/public-bom-audit?embed=true&qa_smoke=1`, {
      waitUntil: "domcontentloaded",
    });
    await page.getByTestId("public-bom-run-audit").waitFor({
      state: "visible",
      timeout: 15000,
    });
    await page.locator('input[type="file"]').setInputFiles({
      name: "normal-smoke.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(csv, "utf8"),
    });
    const normalStillNeedsToken = await page
      .getByTestId("public-bom-run-audit")
      .isDisabled();
    results.normalSignedInStillNeedsTurnstile = normalStillNeedsToken;
    if (!normalStillNeedsToken) {
      throw new Error("Signed-in non-QA could submit without Turnstile token");
    }

    // 3) Status error path via route interception (still Next app, signed-out).
    await page.unroute("**/api/public/bom-stress/audit").catch(() => undefined);
    await page.evaluate(() => {
      window.localStorage.removeItem("cadivor_next_session");
    });
    await page.route("**/api/public/bom-stress/status", async (route) => {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Forced status failure for smoke." }),
      });
    });
    await page.goto(`${BASE}/public-bom-audit?embed=true`, {
      waitUntil: "domcontentloaded",
    });
    await page.getByTestId("public-bom-status-unavailable").waitFor({
      timeout: 15000,
    });
    await page.getByTestId("public-bom-status-error").waitFor({ timeout: 15000 });
    const runVisible = await page.getByTestId("public-bom-run-audit").isVisible().catch(() => false);
    results.statusErrorPath = !runVisible;
    if (runVisible) {
      throw new Error("Upload remained visible after status failure");
    }

    note(JSON.stringify({ ok: true, results }, null, 2));
    process.exitCode = 0;
  } catch (err) {
    note(JSON.stringify({ ok: false, results, error: String(err) }, null, 2));
    process.exitCode = 1;
  } finally {
    await browser.close();
    log.end();
  }
}

main();
