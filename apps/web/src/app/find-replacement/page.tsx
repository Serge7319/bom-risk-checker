"use client";

import Link from "next/link";
import { FormEvent, Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Shell } from "@/components/Shell";
import { LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import { findReplacement } from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { useRequireSession } from "@/lib/session";

function providerLeadCount(state: Record<string, unknown>): number {
  const explicit = Number(state.explicit_count ?? state.lead_count ?? 0);
  const catalog = Number(state.catalog_count ?? 0);
  const total = (Number.isFinite(explicit) ? explicit : 0) + (Number.isFinite(catalog) ? catalog : 0);
  if (total > 0) return total;
  const single = Number(state.result_count ?? state.count ?? 0);
  return Number.isFinite(single) && single > 0 ? single : 0;
}

function providerOutcomeLabel(state: Record<string, unknown>): string {
  const values = ["lookup", "catalog", "substitutions", "family_search", "parametric_search"].map(
    (key) => String(state[key] || "").toLowerCase(),
  );
  const leadCount = providerLeadCount(state);
  if (values.some((value) => value === "not_configured")) return "Not configured";
  if (values.some((value) => value === "timeout")) return "Timed out";
  if (values.some((value) => value === "error" || value === "rate_limited")) return "Failed";
  if (values.some((value) => value === "part_not_found" || value === "no_results")) {
    return "No results";
  }
  if (values.some((value) => value === "ok" || value === "available" || value === "searched")) {
    return leadCount > 0 ? `Returned ${leadCount} leads` : "Searched — no results";
  }
  if (leadCount > 0) return `Returned ${leadCount} leads`;
  return "Searched";
}

function compareHref(partA: string, partB?: string | string[], analysisId?: string) {
  const query = new URLSearchParams({ part_a: partA });
  const candidates = Array.isArray(partB)
    ? partB
    : partB
      ? [partB]
      : [];
  for (const candidate of candidates.slice(0, 4)) {
    if (candidate.trim()) query.append("part_b", candidate.trim());
  }
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
            <label htmlFor="replacement-mfr">Manufacturer (optional)</label>
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
          <section className="cv-card pad" style={{ marginBottom: 14 }}>
            <h3 className="cv-card-title">Original part</h3>
            <p className="cv-card-subtitle">
              {String(original.mpn || result.requested_mpn || mpn)}
              {original.manufacturer ? ` · ${String(original.manufacturer)}` : ""}
              {original.description ? ` · ${String(original.description)}` : ""}
            </p>
            <p className="cv-small-note" style={{ marginTop: 8 }}>
              Lifecycle: {String(original.lifecycle_status || "Unknown")}
              {original.lifecycle_conflict ? " · conflicting supplier records" : ""}
            </p>
            {Array.isArray(original.lifecycle_evidence) && original.lifecycle_evidence.length ? (
              <ul className="cv-small-note" style={{ marginTop: 6, paddingLeft: 18 }}>
                {(original.lifecycle_evidence as Array<Record<string, unknown>>).slice(0, 4).map((row, index) => (
                  <li key={index}>
                    {String(row.source || "Supplier")}: {String(row.status || row.normalized_status || "status not recorded")}
                    {row.retrieved_at ? ` (${String(row.retrieved_at)})` : ""}
                  </li>
                ))}
              </ul>
            ) : null}
            {result.bom_context ? (
              <p className="cv-small-note" style={{ marginTop: 8 }}>
                Prefill linked to a saved BOM analysis in this workspace.
              </p>
            ) : (
              <p className="cv-small-note" style={{ marginTop: 8 }}>
                Standalone search — no BOM required.
              </p>
            )}
            {contextNotice ? (
              <p className="cv-small-note" role="status" style={{ marginTop: 8 }}>
                {contextNotice}
              </p>
            ) : null}
          </section>

          {(providerRows.length || providerFailures.length) ? (
            <section className="cv-card pad" style={{ marginBottom: 14 }} data-testid="replacement-provider-status">
              <h3 className="cv-card-title">Provider search outcomes</h3>
              <p className="cv-card-subtitle">
                Leads stay unverified until datasheet evidence supports qualification. Provider coverage does not imply Compatible fit.
              </p>
              <div className="cv-table-wrap" style={{ marginTop: 12 }}>
                <table className="cv-table">
                  <thead>
                    <tr>
                      <th>Provider</th>
                      <th>Outcome</th>
                      <th>Detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {providerRows.map((row) => (
                      <tr key={row.name}>
                        <td><strong>{row.name}</strong></td>
                        <td>{row.outcome}</td>
                        <td>{row.message || "—"}</td>
                      </tr>
                    ))}
                    {providerFailures.map((row, index) => (
                      <tr key={`failure-${index}`}>
                        <td><strong>{String(row.provider || row.source || "Provider")}</strong></td>
                        <td>{String(row.status || row.outcome || "Failed")}</td>
                        <td>{String(row.message || row.detail || "—")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {result.search_outcome ? (
                <p className="cv-small-note" style={{ marginTop: 10 }}>
                  Search outcome: {String(result.search_outcome)}
                </p>
              ) : null}
            </section>
          ) : null}

          {candidates.length || hasSeparatedLeads ? (
            <>
              <section className="cv-card pad">
                <h3 className="cv-card-title">Relevant candidates</h3>
                <p className="cv-card-subtitle">
                  Same or compatible component family. Still research leads — fit is not confirmed until datasheet evidence is reviewed.
                </p>
                {candidates.length ? (
                  <div style={{ marginTop: 12 }}>
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        gap: 12,
                        alignItems: "center",
                        marginBottom: 10,
                        flexWrap: "wrap",
                      }}
                    >
                      <p className="cv-small-note" style={{ margin: 0 }}>
                        Select 3–4 candidates for one multi-alternate matrix, or compare one at a time.
                        Selection never implies drop-in compatibility.
                      </p>
                      <Link
                        className={`cv-button secondary${selectedCandidates.length < 2 ? " disabled" : ""}`}
                        href={
                          selectedCandidates.length
                            ? compareHref(
                                String(result.requested_mpn || mpn),
                                selectedCandidates.slice(0, 4),
                                compareAnalysisId || undefined,
                              )
                            : "#"
                        }
                        aria-disabled={selectedCandidates.length < 2}
                        onClick={(event) => {
                          if (selectedCandidates.length < 2) event.preventDefault();
                        }}
                      >
                        Compare selected ({Math.min(4, selectedCandidates.length)})
                      </Link>
                    </div>
                    <div className="cv-table-wrap cv-table-wrap--replacement">
                    <table className="cv-table cv-table-replacement cv-table-replacement--candidates">
                      <thead>
                        <tr>
                          <th>Candidate</th>
                          <th>Manufacturer</th>
                          <th>Lifecycle</th>
                          <th>Fit status</th>
                          <th>Evidence to verify</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {candidates.map((row) => {
                          const cand = String(row.mpn || "");
                          const missingBits = ((row.missing_evidence || []) as string[]).filter(Boolean);
                          const lifecycleConflict = Boolean(row.lifecycle_conflict);
                          const lifecycleLabel = lifecycleConflict
                            ? `${String(row.lifecycle_status || "Unknown")} · conflict`
                            : String(row.lifecycle_status || "Unknown");
                          const fitLabel = String(row.fit || "not qualified").replace(/_/g, " ");
                          const checked = selectedCandidates.includes(cand);
                          return (
                            <tr key={cand}>
                              <td className="cv-mpn-cell" data-label="Candidate">
                                <label style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={() => {
                                      setSelectedCandidates((current) => {
                                        if (current.includes(cand)) {
                                          return current.filter((item) => item !== cand);
                                        }
                                        if (current.length >= 4) return current;
                                        return [...current, cand];
                                      });
                                    }}
                                    aria-label={`Select ${cand} for multi-alternate compare`}
                                  />
                                  <span>
                                    <strong>{cand}</strong>
                                    <div className="cv-small-note">{String(row.rationale || "")}</div>
                                  </span>
                                </label>
                              </td>
                              <td data-label="Manufacturer">
                                <span className="cv-table-value">{String(row.manufacturer || "—")}</span>
                              </td>
                              <td data-label="Lifecycle">
                                <span className={`cv-table-value cv-badge ${lifecycleConflict ? "amber" : "gray"}`}>
                                  {lifecycleLabel}
                                </span>
                              </td>
                              <td className="cv-fit-cell" data-label="Fit status">
                                <span className="cv-table-value cv-badge gray">
                                  {fitLabel}
                                </span>
                              </td>
                              <td className="cv-evidence-cell" data-label="Evidence to verify">
                                <span className="cv-table-value">
                                  {missingBits.length ? missingBits.join("; ") : "—"}
                                </span>
                              </td>
                              <td className="cv-table-action" data-label="Action">
                                <span className="cv-table-value">
                                  <Link
                                    href={compareHref(
                                      String(result.requested_mpn || mpn),
                                      cand,
                                      compareAnalysisId || undefined,
                                    )}
                                  >
                                    Compare →
                                  </Link>
                                </span>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                    </div>
                  </div>
                ) : (
                  <p className="cv-small-note" style={{ marginTop: 12 }}>
                    No same-family candidates were returned. Unclassified and cross-family distributor hits are listed separately below when present.
                  </p>
                )}
              </section>
              {unclassifiedLeads.length ? (
                <section className="cv-card pad">
                  <h3 className="cv-card-title">Unclassified leads</h3>
                  <p className="cv-card-subtitle">
                    Catalog hits without confirmed component-family evidence. Not relevant replacement candidates until family is classified.
                  </p>
                  <div className="cv-table-wrap cv-table-wrap--replacement" style={{ marginTop: 12 }}>
                    <table className="cv-table cv-table-replacement cv-table-replacement--leads">
                      <thead>
                        <tr>
                          <th>Lead</th>
                          <th>Manufacturer</th>
                          <th>Fit status</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {unclassifiedLeads.map((row) => {
                          const cand = String(row.mpn || "");
                          const fitLabel = String(
                            row.fit ||
                              "not qualified — component family not classified from available evidence",
                          ).replace(/_/g, " ");
                          return (
                            <tr key={`unclassified-${cand}`}>
                              <td className="cv-mpn-cell" data-label="Lead">
                                <strong>{cand}</strong>
                                <div className="cv-small-note">{String(row.rationale || "")}</div>
                              </td>
                              <td data-label="Manufacturer">
                                <span className="cv-table-value">{String(row.manufacturer || "—")}</span>
                              </td>
                              <td className="cv-fit-cell" data-label="Fit status">
                                <span className="cv-table-value cv-badge amber">{fitLabel}</span>
                              </td>
                              <td className="cv-table-action" data-label="Action">
                                <span className="cv-table-value">
                                  <Link
                                    href={compareHref(
                                      String(result.requested_mpn || mpn),
                                      cand,
                                      compareAnalysisId || undefined,
                                    )}
                                  >
                                    Compare →
                                  </Link>
                                </span>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </section>
              ) : null}
              {unfilteredLeads.length ? (
                <section className="cv-card pad">
                  <h3 className="cv-card-title">Unfiltered leads</h3>
                  <p className="cv-card-subtitle">
                    Distributor keyword hits from a different component family. Not relevant replacement candidates until family and fit are verified.
                  </p>
                  <div className="cv-table-wrap cv-table-wrap--replacement" style={{ marginTop: 12 }}>
                    <table className="cv-table cv-table-replacement cv-table-replacement--leads">
                      <thead>
                        <tr>
                          <th>Lead</th>
                          <th>Manufacturer</th>
                          <th>Fit status</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {unfilteredLeads.map((row) => {
                          const cand = String(row.mpn || "");
                          const fitLabel = String(
                            row.fit || "not qualified — different component family",
                          ).replace(/_/g, " ");
                          return (
                            <tr key={`lead-${cand}`}>
                              <td className="cv-mpn-cell" data-label="Lead">
                                <strong>{cand}</strong>
                                <div className="cv-small-note">{String(row.rationale || "")}</div>
                              </td>
                              <td data-label="Manufacturer">
                                <span className="cv-table-value">{String(row.manufacturer || "—")}</span>
                              </td>
                              <td className="cv-fit-cell" data-label="Fit status">
                                <span className="cv-table-value cv-badge amber">{fitLabel}</span>
                              </td>
                              <td className="cv-table-action" data-label="Action">
                                <span className="cv-table-value">
                                  <Link
                                    href={compareHref(
                                      String(result.requested_mpn || mpn),
                                      cand,
                                      compareAnalysisId || undefined,
                                    )}
                                  >
                                    Compare →
                                  </Link>
                                </span>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </section>
              ) : null}
            </>
          ) : (
            <section className="cv-card pad">
              <h3 className="cv-card-title">Unable to confirm</h3>
              <p className="cv-card-subtitle">
                No verified replacement was found in this search. Check current
                manufacturer documentation and authorized distributors before
                changing the design.
              </p>
              <div style={{ marginTop: 12 }}>
                <SecondaryLink
                  href={compareHref(mpn, undefined, compareAnalysisId || undefined)}
                >
                  Open Compare Parts
                </SecondaryLink>
              </div>
            </section>
          )}
        </>
      ) : null}
    </Shell>
  );
}

export default function FindReplacementPage() {
  return (
    <Suspense fallback={null}>
      <FindReplacementInner />
    </Suspense>
  );
}
