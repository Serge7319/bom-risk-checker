#!/usr/bin/env node
/**
 * Report-delivery smoke for the public BOM audit (Next app preview).
 *
 * Labels:
 * - Uses a local stub API with bearer-gated verified-report (not production Supabase OTP).
 * - Proves the Reports UI loads the full audit after a confirmed session and
 *   reopens it after reload via cache + re-fetch.
 * - Does NOT replace live OTP email delivery; that remains an environment check.
 */
import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";
import { createWriteStream } from "node:fs";
import path from "node:path";

const BASE = (process.env.PUBLIC_BOM_APP_PREVIEW_URL || "http://127.0.0.1:13017").replace(
  /\/$/,
  "",
);
const OUT_DIR =
  process.env.PUBLIC_BOM_SMOKE_OUT || ".evidence_ui/public_bom_audit_smoke";

const SESSION = {
  access_token: "owner-token",
  email: "preview@example.com",
  workspace: "preview",
  workspace_id: "preview-ws",
  user_id: "preview-user",
  plan: "trial",
  mode: "preview-stub",
};

async function main() {
  await mkdir(OUT_DIR, { recursive: true });
  const log = createWriteStream(path.join(OUT_DIR, "delivery_smoke.log"), {
    flags: "w",
  });
  const note = (msg) => {
    log.write(`${msg}\n`);
    console.log(msg);
  };

  const results = {
    kind: "report-delivery",
    stubApi: true,
    liveOtp: false,
    base: BASE,
    authorizedVisible: false,
    crossUserHidden: false,
    reopenAfterReload: false,
  };

  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.addInitScript((session) => {
      window.localStorage.setItem(
        "cadivor_next_session",
        JSON.stringify(session),
      );
    }, SESSION);

    await page.goto(`${BASE}/reports?public_bom_stress=1`, {
      waitUntil: "domcontentloaded",
    });
    await page.getByTestId("public-bom-verified-report").waitFor({ timeout: 20000 });
    await page.getByTestId("public-bom-verified-table").waitFor({ timeout: 20000 });
    await page.getByText("LM358DR").waitFor({ timeout: 10000 });
    results.authorizedVisible = true;

    // Reload without the query flag — cached + re-fetch should still show the audit.
    await page.goto(`${BASE}/reports`, { waitUntil: "domcontentloaded" });
    await page.getByTestId("public-bom-verified-table").waitFor({ timeout: 20000 });
    await page.getByText("LM358DR").waitFor({ timeout: 10000 });
    results.reopenAfterReload = true;

    // Cross-user denial: swap token and ensure the verified table is absent.
    const denied = await browser.newPage();
    await denied.addInitScript((session) => {
      window.localStorage.setItem(
        "cadivor_next_session",
        JSON.stringify({ ...session, access_token: "cross-user-token" }),
      );
    }, SESSION);
    await denied.goto(`${BASE}/reports?public_bom_stress=1`, {
      waitUntil: "domcontentloaded",
    });
    await denied
      .getByText("Verified public audit not found")
      .or(denied.getByText("not available"))
      .waitFor({ timeout: 20000 });
    const tableVisible = await denied
      .getByTestId("public-bom-verified-table")
      .isVisible()
      .catch(() => false);
    results.crossUserHidden = !tableVisible;
    await denied.close();

    if (!results.authorizedVisible || !results.reopenAfterReload || !results.crossUserHidden) {
      throw new Error(`Delivery smoke incomplete: ${JSON.stringify(results)}`);
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
