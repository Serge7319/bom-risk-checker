"use client";

import Link from "next/link";
import { FormEvent, Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Shell } from "@/components/Shell";
import { LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import { cleanUserText } from "@/lib/display";
import { findReplacement } from "@/lib/api";
import {
  shouldShowIdentityDisambiguation,
  shouldShowIdentityRetryButton,
} from "@/lib/findReplacementIdentity";
import { PAGE_META } from "@/lib/routes";
import { useRequireSession } from "@/lib/session";

function providerRawCatalogCount(state: Record<string, unknown>): number | null {
  // Catalog-only: never infer from explicit_count / lead_count / generic totals.
  if (state.catalog_raw_count !== undefined && state.catalog_raw_count !== null) {
    const raw = Number(state.catalog_raw_count);
    return Number.isFinite(raw) && raw >= 0 ? raw : null;
  }
  if (state.catalog_count !== undefined && state.catalog_count !== null) {
    const raw = Number(state.catalog_count);
    return Number.isFinite(raw) && raw >= 0 ? raw : null;
  }
  return null;
}

function providerRetainedCatalogCount(state: Record<string, unknown>): number | null {
  if (state.catalog_retained_count === undefined || state.catalog_retained_count === null) {
    return null;
  }
  const retained = Number(state.catalog_retained_count);
  return Number.isFinite(retained) && retained >= 0 ? retained : null;
}

function providerExplicitSubstitutionCount(state: Record<string, unknown>): number | null {
  // Honor explicit_retained_count when present — including zero. Never fall back
  // to raw explicit_count once retained has been computed.
  if (state.explicit_retained_count !== undefined && state.explicit_retained_count !== null) {
    const retained = Number(state.explicit_retained_count);
    return Number.isFinite(retained) && retained >= 0 ? retained : null;
  }
  const explicit = Number(state.explicit_count);
  return Number.isFinite(explicit) && explicit >= 0 ? explicit : null;
}

const AUTHORITATIVE_FIT_MARKERS = [
  "manufacturer-datasheet",
  "uploaded-manufacturer-datasheet",
  "datasheet-backed",
  "engineering-verified",
  "authoritative fit",
  "authoritative-fit",
];

function candidateHasAuthoritativeFitEvidence(row: Record<string, unknown>): boolean {
  if (
    row.authoritative_fit_evidence === true
    || row.engineering_fit_verified === true
    || row.datasheet_fit_verified === true
  ) {
    return true;
  }
  const evidenceText = [
    "evidence_class",
    "Evidence Class",
    "fit_evidence",
    "Fit Evidence",
    "fit",
    "Fit",
    "Evidence Source",
    "evidence_source",
    "Recommendation",
    "rationale",
  ]
    .map((key) => String(row[key] || ""))
    .join(" ")
    .toLowerCase();
  return AUTHORITATIVE_FIT_MARKERS.some((marker) => evidenceText.includes(marker));
}

function candidateHasVerifiedFit(row: Record<string, unknown>): boolean {
  const fitText = ["fit", "Fit", "disposition", "Candidate Disposition"]
    .map((key) => String(row[key] || ""))
    .join(" ")
    .toLowerCase();
  // Fit status wins: never treat "not qualified" / "qualification required" as verified.
  if (fitText.includes("not qualified") || fitText.includes("qualification required")) {
    return false;
  }
  let claimsCompatible = false;
  for (const key of ["classification", "Classification", "category", "Category", "fit", "Fit"]) {
    const value = String(row[key] || "").trim().toLowerCase();
    if (!value) continue;
    if (value === "compatible" || value === "verified direct substitute") {
      claimsCompatible = true;
      break;
    }
    if (value.startsWith("compatible ")) {
      claimsCompatible = true;
      break;
    }
  }
  // Compatible / verified-direct classification alone is not enough.
  return claimsCompatible && candidateHasAuthoritativeFitEvidence(row);
}

function candidateListHeading(candidates: Array<Record<string, unknown>>): string {
  if (!candidates.length) return "Replacement candidates";
  if (candidates.some((row) => candidateHasVerifiedFit(row))) {
    return "Verified replacements";
  }
  return "Supplier-listed candidates";
}

function searchOutcomeLabel(
  outcome: unknown,
  explicitLabel?: unknown,
  candidates?: Array<Record<string, unknown>>,
): string {
  const provided = String(explicitLabel || "").trim();
  const verified = Array.isArray(candidates)
    ? candidates.some((row) => candidateHasVerifiedFit(row))
    : false;
  // Never keep a "Verified…" banner when no candidate carries Compatible fit evidence.
  if (
    provided
    && /verified replacements found/i.test(provided)
    && Array.isArray(candidates)
    && !verified
  ) {
    return "Supplier-listed candidates found — fit unverified";
  }
  if (provided) return provided;
  const key = String(outcome || "").trim();
  if (key === "success" || key === "candidates_found") {
    return verified
      ? "Verified replacements found"
      : "Supplier-listed candidates found — fit unverified";
  }
  if (key === "partial_success") {
    return verified
      ? "Partial success — verified replacements found"
      : "Partial success — fit unverified";
  }
  const labels: Record<string, string> = {
    catalog_leads_only: "No verified replacement; catalog leads available",
    partial_supplier_results: "Partial supplier results",
    no_results: "No results",
    failure: "Search failed",
    identity_ambiguous: "Could not verify manufacturer identity",
    unable_to_confirm: "Unable to confirm a replacement",
  };
  return labels[key] || key;
}

function providerOutcomeLabel(state: Record<string, unknown>): string {
  const values = ["lookup", "catalog", "substitutions", "family_search", "parametric_search"].map(
    (key) => String(state[key] || "").toLowerCase(),
  );
  const rawCount = providerRawCatalogCount(state);
  const retainedCount = providerRetainedCatalogCount(state);
  const explicitCount = providerExplicitSubstitutionCount(state);
  if (values.some((value) => value === "not_configured")) return "Not configured";
  if (values.some((value) => value === "timeout")) return "Timed out";
  if (values.some((value) => value === "error" || value === "rate_limited")) return "Failed";
  if (values.some((value) => value === "part_not_found" || value === "no_results")) {
    return "No results";
  }
  const parts: string[] = [];
  if (rawCount !== null && rawCount > 0) {
    if (retainedCount !== null && retainedCount !== rawCount) {
      parts.push(`${rawCount} raw catalog matches · ${retainedCount} retained`);
    } else {
      parts.push(`${rawCount} raw catalog matches`);
    }
  }
  if (explicitCount !== null && explicitCount > 0) {
    parts.push(
      `${explicitCount} supplier substitution${explicitCount === 1 ? "" : "s"}`,
    );
  } else if (
    explicitCount === 0
    && Number(state.explicit_count) > 0
  ) {
    // Zero retained must stay visible when raw substitutions were filtered out.
    parts.push("0 retained supplier substitutions");
  }
  if (parts.length) return parts.join("; ");
  if (
    values.some(
      (value) =>
        value === "ok" || value === "available" || value === "searched" || value === "partial",
    )
  ) {
    // Catalog fields present and zero → honest empty catalog; do not invent matches.
    if (rawCount === 0) return "Searched — no results";
    return "Searched — no results";
  }
  return "Searched";
}

function providerHasRawCatalogMatches(outcome: string): boolean {
  return /\d+\s+raw catalog matches/i.test(outcome) || /returned \d+ leads/i.test(outcome);
}

function compareHref(
  partA: string,
  partB?: string | string[],
  analysisId?: string,
  opts?: {
    manufacturerA?: string;
    manufacturerB?: string | string[];
  },
) {
  const query = new URLSearchParams({ part_a: partA });
  const manufacturerA = String(opts?.manufacturerA || "").trim();
  if (manufacturerA) query.set("manufacturer_a", manufacturerA);
  const candidates = Array.isArray(partB)
    ? partB
    : partB
      ? [partB]
      : [];
  const manufacturersB = Array.isArray(opts?.manufacturerB)
    ? opts?.manufacturerB || []
    : opts?.manufacturerB
      ? [opts.manufacturerB]
      : [];
  candidates.slice(0, 4).forEach((candidate, index) => {
    const mpn = candidate.trim();
    if (!mpn) return;
    query.append("part_b", mpn);
    const brand = String(manufacturersB[index] || "").trim();
    // Keep manufacturer_b aligned with each part_b (including empty slots) so
    // multi-candidate handoffs preserve per-side identity independently.
    query.append("manufacturer_b", brand);
  });
  // Only attach BOM context when this search was opened from a valid BOM row.
  if (analysisId) query.set("analysis_id", analysisId);
  return `/compare-parts?${query.toString()}`;
}

function FindReplacementInner() {
  const session = useRequireSession();
  const search = useSearchParams();
  const [mpn, setMpn] = useState("");
  const [manufacturer, setManufacturer] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [selectedCandidates, setSelectedCandidates] = useState<string[]>([]);

  // Explicit BOM-row link only — never reuse last-analysis localStorage for this tool.
  const bomAnalysisId = (search.get("analysis_id") || "").trim();

  useEffect(() => {
    const q = (search.get("mpn") || search.get("part") || "").trim();
    const mfr = (search.get("manufacturer") || "").trim();
    if (q) setMpn(q);
    if (mfr) setManufacturer(mfr);
  }, [search]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!session) return;
    setBusy(true);
    setError("");
    setResult(null);
    setSelectedCandidates([]);
    try {
      const data = await findReplacement(session.access_token, {
        mpn,
        manufacturer: manufacturer || undefined,
        // Standalone: MPN (+ optional manufacturer) only.
        // analysis_id only when the page was opened from a BOM-row link.
        analysis_id: bomAnalysisId || null,
      });
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setBusy(false);
    }
  }

  if (!session) return null;
  const candidates = (result?.candidates || []) as Array<Record<string, unknown>>;
  const unclassifiedLeads = (result?.unclassified_leads || []) as Array<Record<string, unknown>>;
  const unfilteredLeads = (result?.unfiltered_leads || []) as Array<Record<string, unknown>>;
  const original = (result?.original || {}) as Record<string, unknown>;
  const identityReviewOnly = Boolean(result?.identity_review_only);
  const hasSeparatedLeads = unclassifiedLeads.length > 0 || unfilteredLeads.length > 0;
  // Compare Parts inherits BOM context only when the API confirmed bom_context.
  const compareAnalysisId = result?.bom_context
    ? String(
        (result.bom_context as Record<string, unknown>).analysis_id ||
          result.analysis_id ||
          bomAnalysisId ||
          "",
      )
    : "";
  // Part A identity for Compare handoff: resolved original, else requested brand.
  const compareManufacturerA = String(
    original.manufacturer
      || result?.requested_manufacturer
      || manufacturer
      || "",
  ).trim();
  const manufacturerForCandidate = (candMpn: string) => {
    const row = [...candidates, ...unclassifiedLeads, ...unfilteredLeads].find(
      (item) => String(item.mpn || "").trim() === candMpn.trim(),
    );
    return String(row?.manufacturer || "").trim();
  };
  const contextNotice = String(result?.context_unavailable || "").trim();
  const discovery = (result?.discovery || {}) as Record<string, unknown>;
  const providerStatus = (discovery.providers || {}) as Record<string, Record<string, unknown>>;
  const providerFailures = Array.isArray(discovery.provider_failures)
    ? (discovery.provider_failures as Array<Record<string, unknown>>)
    : Array.isArray(result?.provider_failures)
      ? (result?.provider_failures as Array<Record<string, unknown>>)
      : [];
  const providerRows = Object.entries(providerStatus).map(([name, state]) => ({
    name,
    outcome: providerOutcomeLabel(state || {}),
    message: String((state || {}).message || "").trim(),
  }));

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.replacement}
        actions={
          <>
            <PrimaryLink href="/compare-parts">Compare Parts</PrimaryLink>
            <SecondaryLink href="/bom-analyzer">BOM Analyzer</SecondaryLink>
          </>
        }
      />

      <form className="cv-card pad" onSubmit={onSubmit}>
        <p className="cv-card-subtitle" style={{ marginBottom: 14 }}>
          Search by manufacturer part number without a prior BOM analysis. When
          you open this page from a BOM row, the part is prefilled. BOM context
          is optional.
        </p>
        <div className="cv-form-grid">
          <div className="cv-field">
            <label htmlFor="replacement-mpn">Manufacturer part number</label>
            <input
              id="replacement-mpn"
              value={mpn}
              onChange={(e) => setMpn(e.target.value)}
              placeholder="e.g. LM358DR"
              required
            />
          </div>
          <div className="cv-field">
            <label htmlFor="replacement-mfr">Manufacturer (required for dual-source MPNs)</label>
            <input
              id="replacement-mfr"
              value={manufacturer}
              onChange={(e) => setManufacturer(e.target.value)}
              placeholder="e.g. Texas Instruments"
            />
          </div>
        </div>
        <div style={{ marginTop: 14 }}>
          <button className="cv-button primary" type="submit" disabled={busy}>
            {busy ? "Searching…" : "Find candidates"}
          </button>
        </div>
      </form>

      {busy ? <LoadingCard label="Searching the part catalog…" /> : null}
      {error ? <div className="cv-error">{error}</div> : null}

      {result ? (
        <>
          {shouldShowIdentityDisambiguation(result) ? (
            <section className="cv-card pad" style={{ marginBottom: 14 }} role="status" data-testid="identity-disambiguation">
              <h3 className="cv-card-title">
                {identityReviewOnly
                  ? "Manufacturer identity unverified"
                  : String(result.identity_status || "").toLowerCase() === "ambiguous"
                    ? "Manufacturer identity required"
                    : "Manufacturer lineage context"}
              </h3>
              <p className="cv-card-subtitle">
                {cleanUserText(result.detail || result.gap) ||
                  (identityReviewOnly
                    ? "Catalog leads below are review-only. Typed manufacturer text is not identity proof — retry with a supplier-confirmed brand when available."
                    : `${mpn} is offered by more than one manufacturer with official product evidence. Choose the intended brand before reviewing replacements.`)}
              </p>
              <div style={{ display: "grid", gap: 10, marginTop: 12 }}>
                {((result.identity_choices || []) as Array<Record<string, unknown>>).map((choice) => {
                  const choiceMfr = String(choice.manufacturer || "");
                  const typedMfr = String(manufacturer || result.requested_manufacturer || "").trim();
                  // Review-only: allow escalating to a different lineage/supplier brand;
                  // repeating the same unverified typed brand would re-trap the user.
                  const showRetry = shouldShowIdentityRetryButton({
                    identityReviewOnly,
                    typedManufacturer: typedMfr,
                    choiceManufacturer: choiceMfr,
                  });
                  return (
                    <div
                      key={choiceMfr || String(choice.canonical || "")}
                      className="cv-card pad"
                      style={{ boxShadow: "none" }}
                    >
                      <strong>{choiceMfr || "Manufacturer"}</strong>
                      