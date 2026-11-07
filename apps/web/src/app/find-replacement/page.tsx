"use client";

import Link from "next/link";
import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Shell } from "@/components/Shell";
import { GapBanner, LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import { findReplacement } from "@/lib/api";
import {
  buildFindReplacementViewModel,
  type ProviderChannelStatus,
} from "@/lib/findReplacementPresentation";
import { PAGE_META } from "@/lib/routes";
import { useRequireSession } from "@/lib/session";

function compareHref(partA: string, partB?: string, analysisId?: string) {
  const query = new URLSearchParams({ part_a: partA });
  if (partB) query.set("part_b", partB);
  // Only attach BOM context when this search was opened from a valid BOM row.
  if (analysisId) query.set("analysis_id", analysisId);
  return `/compare-parts?${query.toString()}`;
}

function providerBadgeClass(status: ProviderChannelStatus): string {
  switch (status) {
    case "returned_results":
      return "cv-badge green";
    case "searched_no_results":
      return "cv-badge gray";
    case "not_configured":
      return "cv-badge amber";
    case "failed":
    case "timeout":
      return "cv-badge red";
    default:
      return "cv-badge gray";
  }
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

  const view = useMemo(() => buildFindReplacementViewModel(result), [result]);

  if (!session) return null;
  const candidates = (result?.candidates || []) as Array<Record<string, unknown>>;
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

          {view.providerRows.length ? (
            <section
              className="cv-card pad"
              style={{ marginBottom: 14 }}
              data-testid="replacement-provider-status"
            >
              <h3 className="cv-card-title">Supplier source status</h3>
              <p className="cv-card-subtitle">
                Coverage from the search response. Credential values are never shown.
              </p>
              <ul className="cv-missing-list" style={{ marginTop: 10 }}>
                {view.providerRows.map((row) => (
                  <li key={`${row.name}-${row.channel}-${row.status}`}>
                    <strong>{row.name}</strong>{" "}
                    <span className={providerBadgeClass(row.status)}>{row.label}</span>
                    {row.message ? (
                      <div className="cv-small-note">{row.message}</div>
                    ) : null}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {view.gap ? <GapBanner>{view.gap}</GapBanner> : null}

          {view.missingEvidence.length ? (
            <section
              className="cv-card pad"
              style={{ marginBottom: 14 }}
              data-testid="replacement-missing-evidence"
            >
              <h3 className="cv-card-title">Missing evidence</h3>
              <ul className="cv-missing-list">
                {view.missingEvidence.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </section>
          ) : null}

          {candidates.length ? (
            <section className="cv-card pad" data-testid="replacement-candidates">
              <h3 className="cv-card-title">Candidate results</h3>
              <p className="cv-card-subtitle">{view.candidatesUnverifiedNote}</p>
              <div className="cv-table-wrap" style={{ marginTop: 12 }}>
                <table className="cv-table cv-table-actions">
                  <thead>
                    <tr>
                      <th>Candidate</th>
                      <th>Manufacturer</th>
                      <th>Fit status</th>
                      <th>Evidence to verify</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {candidates.map((row) => {
                      const cand = String(row.mpn || "");
                      const missingBits = ((row.missing_evidence || []) as string[]).map((item) =>
                        String(item || ""),
                      );
                      return (
                        <tr key={cand} data-testid="replacement-candidate-row">
                          <td>
                            <strong>{cand}</strong>
                            <div className="cv-small-note">{String(row.rationale || "")}</div>
                            <div className="cv-small-note">Unverified until engineering review</div>
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
          ) : (
            <section className="cv-card pad" data-testid="replacement-empty-state">
              <h3 className="cv-card-title">{view.emptyHeadline}</h3>
              <p className="cv-card-subtitle">{view.emptyDetail}</p>
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
