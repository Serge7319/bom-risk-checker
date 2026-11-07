/**
 * Minimal ESM runner that evaluates apps/web/src/lib/evidenceNotice.ts
 * via Node's TypeScript strip Types (Node 22+).
 */
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const noticePath = path.join(root, "apps/web/src/lib/evidenceNotice.ts");
const cases = JSON.parse(process.env.EVIDENCE_NOTICE_CASES || "[]");

async function loadClassifier() {
  // Prefer native TypeScript stripping when available.
  try {
    const mod = await import(pathToFileURL(noticePath).href);
    return mod;
  } catch {
    // Fallback: transpile the two exported functions with a tiny strip of types.
    const src = readFileSync(noticePath, "utf8")
      .replace(/: EvidenceNoticeTone/g, "")
      .replace(/export type EvidenceNoticeTone[\s\S]*?;\n/, "")
      .replace(/: unknown/g, "")
      .replace(/: string/g, "");
    const tmp = path.join(root, "tests", "_evidence_notice_runtime.mjs");
    const { writeFileSync, unlinkSync } = await import("node:fs");
    writeFileSync(tmp, src);
    try {
      return await import(pathToFileURL(tmp).href + `?t=${Date.now()}`);
    } finally {
      try {
        unlinkSync(tmp);
      } catch {
        /* ignore */
      }
    }
  }
}

const mod = await loadClassifier();
const results = [];
for (const [text, expected] of cases) {
  const got = mod.classifyEvidenceNotice(text);
  results.push({ text, expected, got });
}
const ok = results.every((item) => item.got === item.expected);
process.stdout.write(JSON.stringify({ ok, results }));
process.exit(ok ? 0 : 1);
