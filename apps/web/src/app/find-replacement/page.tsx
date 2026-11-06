"use client";

import Link from "next/link";
import { FormEvent, Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Shell } from "@/components/Shell";
import { GapBanner, LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import { findReplacement } from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { readLastAnalysis, useRequireSession } from "@/lib/session";

function compareHref(partA: string, partB?: string, analysisId?: string) {
  const query = new URLSearchParams({ part_a: partA });
  if (partB) query.set("part_b", partB);
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
      const last = readLastAnalysis();
      const analysisFromQuery = (search.get("analysis_id") || "").trim();
      const data = await findReplacement(session.access_token, {
        mpn,
        manufacturer: manufacturer || undefined,
        analysis_id: analysisFromQuery || last?.analysis_id || null,
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
  const missing = (result?.missing_evidence || []) as string[];
  const original = (result?.original || {}) as Record<string, unknown>;
  const analysisId = String(
    result?.analysis_id || search.get("analysis_id") || readLastAnalysis(session)?.analysis_id || "",
  );

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

      {busy ? <LoadingCard label="Searching offline catalog and supplier path…" /> : null}
      {error ? <div className="cv-error">{error}</div> : null}

      {result ? (
        <>
          {typeof result.gap === "string" ? <GapBanner>{String(result.gap)}</GapBanner> : null}

          <section className="cv-card pad" style={{ marginBottom: 14 }}>
            <h3 className="cv-card-title">Original part</h3>
            <p className="cv-card-subtitle">
              {String(original.mpn || result.requested_mpn || mpn)}
              {original.manufacturer ? ` · ${String(original.manufacturer)}` : ""}
              {original.description ? ` · ${String(original.description)}` : ""}
            </p>
            {result.bom_context ? (
              <p className="cv-small-note" style={{ marginTop: 8 }}>
                Prefill linked to a saved BOM analysis in this workspace.
              </p>
            ) : (
              <p className="cv-small-note" style={{ marginTop: 8 }}>
                Standalone search — no BOM required.
              </p>
            )}
          </section>

          {candidates.length ? (
            <section className="cv-card pad">
              <h3 className="cv-card-title">Candidate results</h3>
              <p className="cv-card-subtitle">
                Candidates are reference suggestions. Fit is not confirmed until
                datasheet evidence is reviewed.
              </p>
              <div className="cv-table-wrap" style={{ marginTop: 12 }}>
                <table className="cv-table cv-table-actions">
                  <thead>
                    <tr>
                      <th>Candidate</th>
                      <th>Manufacturer</th>
                      <th>Fit status</th>
                      <th>Missing evidence</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {candidates.map((row) => {
                      const cand = String(row.mpn || "");
                      const missingBits = (row.missing_evidence || []) as string[];
                      return (
                        <tr key={cand}>
                          <td>
                            <strong>{cand}</strong>
                            <div className="cv-small-note">{String(row.rationale || "")}</div>
                          </td>
                          <td>{String(row.manufacturer || "—")}</td>
                          <td>
                            <span className="cv-badge gray">
                              {String(row.fit || "unable_to_confirm").replace(/_/g, " ")}
                            </span>
                          </td>
                          <td>{missingBits.length ? missingBits.join("; ") : "—"}</td>
                          <td className="cv-table-action">
                            <Link
                              href={compareHref(String(result.requested_mpn || mpn), cand, analysisId)}
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
          ) : (
            <section className="cv-card pad">
              <h3 className="cv-card-title">Unable to confirm</h3>
              <p className="cv-card-subtitle">
                No replacement candidates can be confirmed for this part with the
                connected sources.
              </p>
              {missing.length ? (
                <ul className="cv-missing-list">
                  {missing.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : null}
              <div style={{ marginTop: 12 }}>
                <SecondaryLink
                  href={compareHref(mpn, undefined, analysisId)}
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
