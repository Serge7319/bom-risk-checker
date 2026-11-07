/**
 * Node runner for Find a replacement presentation contracts.
 */
import { pathToFileURL } from "node:url";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const modulePath = path.join(root, "apps/web/src/lib/findReplacementPresentation.ts");

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

async function main() {
  const {
    buildFindReplacementViewModel,
    providerStatusRows,
    redactCredentialValues,
  } = await import(pathToFileURL(modulePath).href);

  const cases = [];

  {
    const redacted = redactCredentialValues(
      "Mouser failed api_key=super-secret-key-value-1234567890abcdef and Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc",
    );
    assert(!/super-secret/i.test(redacted), "secret value must be redacted");
    assert(!/eyJhbGci/i.test(redacted), "bearer token must be redacted");
    assert(/redacted/i.test(redacted), "redaction marker present");
    cases.push("redacts-credentials");
  }

  {
    const rows = providerStatusRows({
      providers: {
        DigiKey: {
          lookup: "not_configured",
          catalog: "not_configured",
          substitutions: "not_configured",
          message: "DIGIKEY_CLIENT_ID missing",
        },
        Mouser: {
          lookup: "error",
          catalog: "timeout",
          substitutions: "not_supported",
          message: "api_key=should-not-leak-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        },
        Newark: {
          lookup: "ok",
          catalog: "ok",
          catalog_count: 0,
          substitutions: "ok",
          explicit_count: 2,
          message: "searched",
        },
      },
    });
    assert(rows.some((r) => r.name === "DigiKey" && r.status === "not_configured"), "digikey not configured");
    assert(rows.some((r) => r.name === "Mouser" && r.status === "timeout"), "mouser timeout");
    assert(rows.some((r) => r.name === "Mouser" && r.status === "failed"), "mouser failed");
    assert(rows.some((r) => r.name === "Newark" && r.status === "searched_no_results"), "newark catalog empty");
    assert(rows.some((r) => r.name === "Newark" && r.status === "returned_results"), "newark substitutions returned");
    assert(rows.every((r) => !/should-not-leak/i.test(r.message)), "provider messages redact secrets");
    cases.push("provider-status-distinctions");
  }

  {
    const empty = buildFindReplacementViewModel({
      candidates: [],
      discovery: {
        providers: {
          DigiKey: { lookup: "not_configured", catalog: "not_configured", substitutions: "not_configured" },
          Mouser: { lookup: "not_configured", catalog: "not_configured", substitutions: "not_configured" },
        },
      },
      missing_evidence: ["live authorized-distributor search"],
      gap: "No candidates were returned by the available sources.",
    });
    assert(
      empty.emptyHeadline === "No candidates were returned by the available sources.",
      `empty headline=${empty.emptyHeadline}`,
    );
    assert(!/no replacement exists/i.test(empty.emptyHeadline), "headline must not claim none exist");
    assert(/does not confirm that no replacement exists/i.test(empty.emptyDetail), "detail clarifies incompleteness");
    assert(empty.providerRows.length >= 1, "empty state still shows provider rows");
    assert(empty.missingEvidence.includes("live authorized-distributor search"), "missing evidence surfaced");
    cases.push("no-provider-empty-state");
  }

  {
    const withCandidates = buildFindReplacementViewModel({
      candidates: [
        {
          mpn: "ALT-123",
          manufacturer: "Example",
          fit: "supplier-listed candidate; qualification required",
          missing_evidence: ["datasheet-backed review"],
        },
      ],
      discovery: {
        providers: {
          DigiKey: { catalog: "ok", catalog_count: 1, substitutions: "ok", explicit_count: 1 },
        },
      },
      gap: "Candidate parts are research leads, not approved substitutes.",
    });
    assert(/unverified/i.test(withCandidates.candidatesUnverifiedNote), "candidates stay unverified");
    assert(
      withCandidates.providerRows.some((r) => r.status === "returned_results"),
      "candidate search shows returned_results",
    );
    cases.push("returned-candidate-rendering");
  }

  console.log(JSON.stringify({ ok: true, cases }));
}

main().catch((err) => {
  console.log(JSON.stringify({ ok: false, error: String(err?.stack || err) }));
  process.exitCode = 1;
});
