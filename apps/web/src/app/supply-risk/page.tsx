"use client";

import { FormEvent, useEffect, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { Shell } from "@/components/Shell";
import { EvidenceNotice, LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink } from "@/components/PageHeader";
import { runSupplyRisk } from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { readLastAnalysis, useRequireSession } from "@/lib/session";

function cell(value: unknown, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

export default function SupplyRiskPage() {
  const session = useRequireSession();
  const [stockReduction, setStockReduction] = useState(25);
  const [buildQty, setBuildQty] = useState(100);
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);

  async function run(event?: FormEvent) {
    event?.preventDefault();
    if (!session) return;
    setBusy(true);
    setError("");
    const last = readLastAnalysis(session);
    try {
      setData(
        await runSupplyRisk(session.access_token, {
          analysis_id: last?.analysis_id || null,
          build_quantity: buildQty,
          stock_reduction_percent: stockReduction,
          supplier_loss: 0,
          demand_growth_percent: 0,
          include_lifecycle_event: false,
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  if (!session) return null;
  const scenario = (data?.scenario || {}) as Record<string, unknown>;
  const rows = (scenario.impacted || scenario.rows || []) as Array<Record<string, unknown>>;
  return (
    <Shell session={session}>
      <PageHeader meta={PAGE_META.supply} actions={<PrimaryLink href="/reports">Choose a saved analysis</PrimaryLink>} />
      {<EvidenceNotice gap={data?.gap} />}
      <form className="cv-card pad" style={{ marginBottom: 14 }} onSubmit={run}>
        <div className="cv-form-grid">
          <div className="cv-field">
            <label htmlFor="build">Build quantity</label>
            <input id="build" type="number" min={1} value={buildQty} onChange={(e) => setBuildQty(Number(e.target.value) || 1)} />
          </div>
          <div className="cv-field">
            <label htmlFor="stock">Stock reduction %</label>
            <input id="stock" type="number" min={0} max={100} value={stockReduction} onChange={(e) => setStockReduction(Number(e.target.value) || 0)} />
          </div>
        </div>
        <button className="cv-button primary" style={{ marginTop: 12 }} type="submit" disabled={busy}>
          {busy ? "Modeling…" : "Run scenario"}
        </button>
      </form>
      {busy ? <LoadingCard label="Modeling supply scenario…" /> : null}
      {error ? <div className="cv-error" role="alert">The supply scenario could not run. {error}</div> : null}
      {!busy && data ? (
        <>
          <section className="cv-card pad">
            <div className="cv-section-heading cv-section-heading--card">
              <div>
                <h2>Affected components</h2>
                <p>Scenario: {String(scenario.build_quantity ?? buildQty)} units with a {String(scenario.stock_reduction_percent ?? stockReduction)}% stock reduction.</p>
              </div>
              <span className="cv-data-note">{rows.length} component{rows.length === 1 ? "" : "s"}</span>
            </div>
            {rows.length ? <div className="cv-table-wrap" style={{ marginTop: 12 }}>
              <table className="cv-table">
                <thead>
                  <tr>
                    <th>Part</th>
                    <th>Stock</th>
                    <th>Adjusted</th>
                    <th>Lifecycle</th>
                    <th>Risk</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, 40).map((row, i) => (
                    <tr key={i}>
                      <td><strong>{cell(row["Part Number"] ?? row.mpn)}</strong></td>
                      <td>{cell(row["Original Stock"] ?? row["Available Stock"] ?? row.stock ?? row.Stock)}</td>
                      <td>{cell(row["Scenario Stock"] ?? row["Adjusted Stock"] ?? row.adjusted_stock)}</td>
                      <td>{cell(row.Lifecycle ?? row.lifecycle)}</td>
                      <td>{cell(row["Scenario Risk"] ?? row["Risk Level"] ?? row.risk_level)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div> : <EmptyState icon="risk" title="No affected components found" body="The selected BOM has no inventory rows matching this scenario. Try another stock reduction or review the saved analysis." action={<PrimaryLink href="/reports">Choose a saved analysis</PrimaryLink>} />}
          </section>
        </>
      ) : null}
    </Shell>
  );
}

