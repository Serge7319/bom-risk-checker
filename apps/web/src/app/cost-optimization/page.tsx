"use client";

import { useEffect, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
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
    const last = readLastAnalysis(session);
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
  const pricedRows = (opt.priced_rows || []) as Array<Record<string, unknown>>;
  return (
    <Shell session={session}>
      <PageHeader meta={PAGE_META.cost} actions={<PrimaryLink href="/procurement">Review sourcing</PrimaryLink>} />
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
      {busy ? <LoadingCard label="Modeling cost opportunities from available price evidence…" /> : null}
      {error ? <div className="cv-error" role="alert">Cost analysis could not load. {error}</div> : null}
      {!busy && data ? (
        <>
          <section className="cv-card pad">
            <div className="cv-section-heading cv-section-heading--card">
              <div>
                <h2>Cost opportunities</h2>
                <p>Scenario quantity: {String(data.build_quantity ?? qty)} units. Review the source shown on every price row.</p>
              </div>
              <span className="cv-data-note">{opportunities.length === 1 ? "1 opportunity" : opportunities.length + " opportunities"}</span>
            </div>
            {opportunities.length ? <div className="cv-table-wrap" style={{ marginTop: 12 }}>
              <table className="cv-table">
                <thead>
                  <tr>
                    <th>Part</th>
                    <th>Qty</th>
                    <th>Unit price</th>
                    <th>Estimated savings</th>
                    <th>Evidence and rationale</th>
                  </tr>
                </thead>
                <tbody>
                  {opportunities.slice(0, 40).map((row, i) => (
                    <tr key={i}>
                      <td><strong>{String(row["Part Number"] || row.mpn || row.Part || "")}</strong></td>
                      <td>{String(row["Units per Build"] ?? row.Quantity ?? row.quantity ?? row.Qty ?? "—")}</td>
                      <td>{String(row["Current Unit Price"] ?? row["Unit Price"] ?? row.unit_price ?? "—")}</td>
                      <td>{String(row["Estimated Run Savings"] ?? row["Extended Cost"] ?? row.extended ?? row.Extended ?? "—")}</td>
                      <td>
                        {evidenceSourceLabel(data.mode || "Synthetic estimate", "Synthetic estimate")}
                        <div className="cv-small-note">{String(row.Reason ?? row.Opportunity ?? row.note ?? row.Notes ?? "Modeled from saved price and quantity data.")}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div> : <EmptyState
              icon="cost"
              title={pricedRows.length ? "No eligible savings opportunities" : "Pricing data needed"}
              body={pricedRows.length
                ? `Pricing is recorded for ${pricedRows.length} component(s), but none meet the current shared-project, multi-source, or per-build quantity criteria. Prices are synthetic estimates, not supplier quotes.`
                : "No component prices are saved in this analysis. Supplier quotes are not connected yet; review Procurement Advisor for current coverage."}
              action={<PrimaryLink href="/procurement">Open Procurement Advisor</PrimaryLink>}
            />}
          </section>
        </>
      ) : null}
    </Shell>
  );
}

