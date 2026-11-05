"use client";

import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { GapBanner, LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink } from "@/components/PageHeader";
import { fetchCostOptimization } from "@/lib/api";
import { evidenceSourceLabel } from "@/lib/display";
import { PAGE_META } from "@/lib/routes";
import { readLastAnalysis, useRequireSession } from "@/lib/session";

export default function CostOptimizationPage() {
  const session = useRequireSession();
  const [qty, setQty] = useState(100);
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);

  function load(buildQuantity = qty) {
    if (!session) return;
    setBusy(true);
    const last = readLastAnalysis();
    fetchCostOptimization(session.access_token, {
      analysisId: last?.analysis_id,
      buildQuantity,
    })
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed"))
      .finally(() => setBusy(false));
  }

  useEffect(() => {
    load(100);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  if (!session) return null;
  const opt = (data?.optimization || {}) as Record<string, unknown>;
  const opportunities = (opt.opportunities || opt.rows || []) as Array<Record<string, unknown>>;
  const summary = {
    current_cost_per_build: opt.current_cost_per_build,
    production_run_cost: opt.production_run_cost,
    priced_rows: opt.priced_rows,
    missing_price_rows: opt.missing_price_rows,
  } as Record<string, unknown>;

  return (
    <Shell session={session}>
      <PageHeader meta={PAGE_META.cost} actions={<PrimaryLink href="/bom-analyzer">Analyze BOM</PrimaryLink>} />
      {typeof data?.gap === "string" ? <GapBanner>{String(data.gap)}</GapBanner> : null}
      <div className="cv-card pad" style={{ marginBottom: 14, display: "flex", gap: 12, alignItems: "end" }}>
        <div className="cv-field" style={{ minWidth: 160 }}>
          <label htmlFor="qty">Build quantity</label>
          <input id="qty" type="number" min={1} value={qty} onChange={(e) => setQty(Number(e.target.value) || 1)} />
        </div>
        <button type="button" className="cv-button primary" disabled={busy} onClick={() => load(qty)}>
          {busy ? "Calculating…" : "Recalculate"}
        </button>
      </div>
      {busy ? <LoadingCard label="Modeling cost opportunities from synthetic unit prices…" /> : null}
      {error ? <div className="cv-error">{error}</div> : null}
      {!busy && data ? (
        <>
          <div className="cv-kpis">
            <div className="cv-kpi tone-blue"><span>Build qty</span><strong>{String(data.build_quantity)}</strong><em>Scenario input</em></div>
            <div className="cv-kpi"><span>Summary fields</span><strong>{Object.keys(summary).length}</strong><em>From Cadivor builder</em></div>
            <div className="cv-kpi tone-amber"><span>Opportunities</span><strong>{opportunities.length}</strong><em>Labeled synthetic prices</em></div>
            <div className="cv-kpi"><span>Mode</span><strong style={{ fontSize: 14 }}>synthetic</strong><em>Not live quotes</em></div>
          </div>
          <section className="cv-card pad">
            <h3 className="cv-card-title">Opportunity table</h3>
            <div className="cv-table-wrap" style={{ marginTop: 12 }}>
              <table className="cv-table">
                <thead>
                  <tr>
                    <th>Part</th>
                    <th>Qty</th>
                    <th>Unit price</th>
                    <th>Extended</th>
                    <th>Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {opportunities.slice(0, 40).map((row, i) => (
                    <tr key={i}>
                      <td><strong>{String(row["Part Number"] || row.mpn || row.Part || "")}</strong></td>
                      <td>{String(row.Quantity || row.quantity || row.Qty || "")}</td>
                      <td>{String(row["Unit Price"] || row.unit_price || "—")}</td>
                      <td>{String(row["Extended Cost"] || row.extended || row.Extended || "—")}</td>
                      <td>{evidenceSourceLabel(row.Opportunity || row.note || row.Notes, "Synthetic estimate")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!opportunities.length ? (
              <p className="cv-small-note" style={{ marginTop: 10 }}>
                Builder returned no tabular opportunities. Summary keys: {Object.keys(summary).slice(0, 8).join(", ") || "none"}.
              </p>
            ) : null}
          </section>
        </>
      ) : null}
    </Shell>
  );
}
