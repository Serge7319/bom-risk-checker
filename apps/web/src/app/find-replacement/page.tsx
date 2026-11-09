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

function compareHref(partA: string, partB?: string, analysisId?: string) {
  const query = new URLSearchParams({ part_a: partA });
  if (partB) query.set("part_b", partB);
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
  const unfilteredLeads = (result?.unfiltered_leads || []) as Array<Record<string, unknown>>;
  const original = (result?.original || {}) as Record<string, unknown>;
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

          {candidates.length || unfilteredLeads.length ? (
            <>
              <section className="cv-card pad">
                <h3 className="cv-card-title">Relevant candidates</h3>
                <p className="cv-card-subtitle">
                  Same or compatible component family. Still research leads — fit is not confirmed until datasheet evidence is reviewed.
                </p>
                {candidates.length ? (
                  <div className="cv-table-wrap" style={{ marginTop: 12 }}>
                    <table className="cv-table cv-table-actions">
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
                          const missingBits = ((row.missing_evidence || []) as string[])
                            .filter((item) => !/(credential|transport|provider|catalog|lookup|search coverage)/i.test(item));
                          const lifecycleConflict = Boolean(row.lifecycle_conflict);
                          const lifecycleLabel = lifecycleConflict
                            ? `${String(row.lifecycle_status || "Unknown")} · conflict`
                            : String(row.lifecycle_status || "Unknown");
                          return (
                            <tr key={cand}>
                              <td className="cv-mpn-cell">
                                <strong>{cand}</strong>
                                <div className="cv-small-note">{String(row.rationale || "")}</div>
                              </td>
                              <td>{String(row.manufacturer || "—")}</td>
                              <td>
                                <span className={`cv-badge ${lifecycleConflict ? "amber" : "gray"}`}>
                                  {lifecycleLabel}
                                </span>
                              </td>
                              <td>
                                <span className="cv-badge gray">
                                  {String(row.fit || "not qualified").replace(/_/g, " ")}
                                </span>
                              </td>
                              <td>{missingBits.length ? missingBits.join("; ") : "—"}</td>
                              <td className="cv-table-action">
                                <Link
                                  href={compareHref(
                                    String(result.requested_mpn || mpn),
                                    cand,
                                    compareAnalysisId || undefined,
                                  )}
                                >
                                  Compare →
                                </Link>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="cv-small-note" style={{ marginTop: 12 }}>
                    No same-family candidates were returned. Cross-family distributor hits are listed separately below when present.
                  </p>
                )}
              </section>
              {unfilteredLeads.length ? (
                <section className="cv-card pad">
                  <h3 className="cv-card-title">Unfiltered leads</h3>
                  <p className="cv-card-subtitle">
                    Distributor keyword hits from a different component family. Not relevant replacement candidates until family and fit are verified.
                  </p>
                  <div className="cv-table-wrap" style={{ marginTop: 12 }}>
                    <table className="cv-table cv-table-actions">
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
                          return (
                            <tr key={`lead-${cand}`}>
                              <td className="cv-mpn-cell">
                                <strong>{cand}</strong>
                                <div className="cv-small-note">{String(row.rationale || "")}</div>
                              </td>
                              <td>{String(row.manufacturer || "—")}</td>
                              <td>
                                <span className="cv-badge amber">
                                  {String(row.fit || "not qualified — different component family").replace(/_/g, " ")}
                                </span>
                              </td>
                              <td className="cv-table-action">
                                <Link
                                  href={compareHref(
                                    String(result.requested_mpn || mpn),
                                    cand,
                                    compareAnalysisId || undefined,
                                  )}
                                >
                                  Compare →
                                </Link>
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
