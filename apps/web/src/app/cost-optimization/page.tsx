"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { EmptyState } from "@/components/EmptyState";
import { Shell } from "@/components/Shell";
import { EvidenceNotice, LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink } from "@/components/PageHeader";
import { fetchCostOptimization, listReports } from "@/lib/api";
import { cleanUserText, evidenceSourceLabel, userFacingLabel } from "@/lib/display";
import { PAGE_META } from "@/lib/routes";
import { readLastAnalysis, useRequireSession } from "@/lib/session";

function analysisLabel(row: Record<string, unknown>) {
  const project = userFacingLabel(row.project_name, "");
  const bom = userFacingLabel(row.bom_name || row.filename, "");
  const revision = userFacingLabel(row.revision, "");
  const title = [project, bom].filter(Boolean).join(" · ") || "Saved analysis";
  return revision ? `${title} (rev ${revision})` : title;
}

function withAnalysisId(href: string, analysisId: string) {
  if (!analysisId) return href;
  const joiner = href.includes("?") ? "&" : "?";
  return `${href}${joiner}analysis_id=${encodeURIComponent(analysisId)}`;
}

function formatEstimate(value: unknown) {
  if (value === null || value === undefined || String(value).trim() === "") return "—";
  const amount = typeof value === "number" ? value : Number(String(value).replace(/,/g, "").trim());
  if (!Number.isFinite(amount)) return String(value);
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(amount);
}

function formatSavingsRate(value: unknown) {
  if (value === null || value === undefined || String(value).trim() === "") return "—";
  const rate = typeof value === "number" ? value : Number(String(value).trim());
  if (!Number.isFinite(rate)) return String(value);
  return new Intl.NumberFormat("en-US", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(rate);
}

function CostOptimizationInner() {
  const session = useRequireSession();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [qty, setQty] = useState(100);
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [reports, setReports] = useState<Array<Record<string, unknown>>>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const [selectedAnalysisId, setSelectedAnalysisId] = useState("");

  const requestedAnalysisId = useMemo(
    () => (searchParams.get("analysis_id") || "").trim(),
    [searchParams],
  );

  function load(buildQuantity = qty, analysisId = selectedAnalysisId || requestedAnalysisId) {
    if (!session) return;
    setBusy(true);
    setError("");
    Promise.all([
      listReports(session.access_token).catch(() => ({ reports: [] as Array<Record<string, unknown>> })),
      fetchCostOptimization(session.access_token, {
        analysisId: analysisId || undefined,
        buildQuantity,
      }),
    ])
      .then(([reportPayload, optimization]) => {
        setReports((reportPayload.reports || []) as Array<Record<string, unknown>>);
        setData(optimization);
        const resolved = String(optimization.analysis_id || analysisId || "").trim();
        if (resolved) setSelectedAnalysisId(resolved);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed"))
      .finally(() => setBusy(false));
  }

  useEffect(() => {
    if (!session) return;
    const last = readLastAnalysis(session);
    const analysisId = requestedAnalysisId || last?.analysis_id || "";
    setSelectedAnalysisId(analysisId);
    load(100, analysisId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, requestedAnalysisId]);

  if (!session) return null;
  const opt = (data?.optimization || {}) as Record<string, unknown>;
  const opportunities = (opt.opportunities || opt.rows || []) as Array<Record<string, unknown>>;
  const pricedRows = (opt.priced_rows || []) as Array<Record<string, unknown>>;
  const evidenceSummary = (data?.evidence_summary || {}) as Record<string, unknown>;
  const missingPrices = Number(evidenceSummary.missing_price_count || 0);
  const activeAnalysisId = String(data?.analysis_id || selectedAnalysisId || "").trim();
  const contextLabel = [
    userFacingLabel(data?.project_name, ""),
    userFacingLabel(data?.bom_name || data?.filename, ""),
    data?.revision ? `rev ${userFacingLabel(data.revision, "—")}` : "",
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.cost}
        actions={<PrimaryLink href={withAnalysisId("/procurement", activeAnalysisId)}>Review sourcing</PrimaryLink>}
      />
      {<EvidenceNotice gap={data?.gap} />}
      <div className="cv-card pad" style={{ marginBottom: 14, display: "flex", gap: 12, alignItems: "end", flexWrap: "wrap" }}>
        <div className="cv-field" style={{ minWidth: 240 }}>
          <label htmlFor="cost-analysis">Analysis context</label>
          <select
            id="cost-analysis"
            aria-label="Cost optimization BOM context"
            value={selectedAnalysisId}
            onChange={(event) => {
              const nextId = event.target.value;
              setSelectedAnalysisId(nextId);
              router.replace(
                nextId
                  ? `/cost-optimization?analysis_id=${encodeURIComponent(nextId)}`
                  : "/cost-optimization",
              );
            }}
          >
            <option value="">Select a saved analysis</option>
            {reports.map((row) => {
              const id = String(row.id || "").trim();
              if (!id) return null;
              return (
                <option key={id} value={id}>
                  {analysisLabel(row)}
                </option>
              );
            })}
          </select>
        </div>
        <div className="cv-field" style={{ minWidth: 160 }}>
          <label htmlFor="qty">Build quantity</label>
          <input id="qty" type="number" min={1} value={qty} onChange={(e) => setQty(Number(e.target.value) || 1)} />
        </div>
        <button type="button" className="cv-button primary" disabled={busy} onClick={() => load(qty)}>
          {busy ? "Calculating…" : "Recalculate"}
        </button>
      </div>
      <p className="cv-small-note" style={{ marginBottom: 14 }} data-testid="cost-optimization-context">
        {contextLabel
          ? `Showing ${contextLabel}`
          : activeAnalysisId
            ? "Showing the selected saved analysis"
            : "No analysis selected — choose the same saved BOM used in Procurement."}
        {missingPrices > 0 ? ` · ${missingPrices} part(s) have no recorded unit price.` : ""}
      </p>
      {busy ? <LoadingCard label="Modeling cost opportunities from available price evidence…" /> : null}
      {error ? <div className="cv-error" role="alert">Cost analysis could not load. {error}</div> : null}
      {!busy && data ? (
        <>
          <section className="cv-card pad">
            <div className="cv-section-heading cv-section-heading--card">
              <div>
                <h2>Cost opportunities</h2>
                <p>Scenario quantity: {String(data.build_quantity ?? qty)} units. Target prices and savings are illustrative model outputs using the listed 5%, 6%, or 8% assumption, not supplier quotes or guaranteed discounts. Review each recorded source and price type; absent prices stay blank.</p>
              </div>
              <span className="cv-data-note">{opportunities.length === 1 ? "1 opportunity" : opportunities.length + " opportunities"}</span>
            </div>
            {opportunities.length ? <div className="cv-table-wrap" style={{ marginTop: 12 }}>
              <table className="cv-table">
                <thead>
                  <tr>
                    <th>Part</th>
                    <th className="cv-num">Qty</th>
                    <th className="cv-num">Recorded unit price</th>
                    <th className="cv-num">Modeled target unit price</th>
                    <th className="cv-num">Modeled run savings</th>
                    <th className="cv-num">Rate assumption</th>
                    <th>Evidence and rationale</th>
                  </tr>
                </thead>
                <tbody>
                  {opportunities.slice(0, 40).map((row, i) => {
                    const unitPrice = row["Current Unit Price"] ?? row["Unit Price"] ?? row.unit_price;
                    const priceMissing = unitPrice === null || unitPrice === undefined || String(unitPrice).trim() === "";
                    const estimatedSavings = row["Estimated Run Savings"];
                    return (
                      <tr key={i}>
                        <td><strong>{String(row["Part Number"] || row.mpn || row.Part || "")}</strong></td>
                        <td className="cv-num">{String(row["Units per Build"] ?? row.Quantity ?? row.quantity ?? row.Qty ?? "—")}</td>
                        <td className="cv-num">
                          {priceMissing ? "Price absent" : formatEstimate(unitPrice)}
                          {!priceMissing ? (
                            <div className="cv-estimate-tag">
                              {evidenceSourceLabel(row.price_source || data.mode || "Synthetic estimate", "Synthetic estimate")}
                            </div>
                          ) : null}
                        </td>
                        <td className="cv-num">{priceMissing ? "—" : formatEstimate(row["Estimated Target Price"])}</td>
                        <td className="cv-num">{formatEstimate(estimatedSavings)}</td>
                        <td className="cv-num">{formatSavingsRate(row["Savings Rate"])}</td>
                        <td className="cv-cell-wrap">
                          <span className="cv-badge gray">{evidenceSourceLabel(data.mode || "Synthetic estimate", "Synthetic estimate")}</span>
                          <div className="cv-small-note">{cleanUserText(row.Reason ?? row.Opportunity ?? row.note ?? row.Notes) || "Modeled from saved price and quantity data."}</div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div> : <EmptyState
              icon="cost"
              title={pricedRows.length ? "No eligible savings opportunities" : "Pricing data needed"}
              body={pricedRows.length
                ? `Pricing is recorded for ${pricedRows.length} component(s), but none meet the current shared-project, multi-source, or per-build quantity criteria. Review each price source before treating figures as quotes.`
                : "No component prices are saved in this analysis. Absent prices stay blank — open Procurement Advisor to check authorized sources."}
              action={<PrimaryLink href={withAnalysisId("/procurement", activeAnalysisId)}>Open Procurement Advisor</PrimaryLink>}
            />}
          </section>
        </>
      ) : null}
    </Shell>
  );
}

export default function CostOptimizationPage() {
  return (
    <Suspense fallback={null}>
      <CostOptimizationInner />
    </Suspense>
  );
}
