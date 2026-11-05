"use client";

import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { GapBanner, LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink } from "@/components/PageHeader";
import { fetchDetailedRisk } from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { readLastAnalysis, useRequireSession } from "@/lib/session";

export default function DetailedRiskPage() {
  const session = useRequireSession();
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    if (!session) return;
    const last = readLastAnalysis();
    fetchDetailedRisk(session.access_token, last?.analysis_id)
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed"))
      .finally(() => setBusy(false));
  }, [session]);

  if (!session) return null;
  const rows = (data?.rows || []) as Array<Record<string, unknown>>;
  const summary = (data?.summary || {}) as Record<string, unknown>;

  return (
    <Shell session={session}>
      <PageHeader
        meta={{
          ...PAGE_META.risk,
          title: data?.filename ? `Detailed risk · ${String(data.filename)}` : PAGE_META.risk.title,
        }}
        record
        actions={<PrimaryLink href="/bom-analyzer">Analyze BOM</PrimaryLink>}
      />
      {typeof data?.gap === "string" ? <GapBanner>{String(data.gap)}</GapBanner> : null}
      {busy ? <LoadingCard label="Loading detailed risk rows…" /> : null}
      {error ? <div className="cv-error">{error}</div> : null}
      {!busy && data ? (
        <>
          <div className="cv-kpis">
            <div className="cv-kpi tone-blue"><span>Health</span><strong>{data.health_score == null ? "—" : String(data.health_score)}</strong><em>{String(data.health_status || "")}</em></div>
            <div className="cv-kpi"><span>Components</span><strong>{rows.length}</strong><em>Whitelisted export schema</em></div>
            <div className="cv-kpi tone-amber"><span>Open high risk</span><strong>{String(summary.open_high_risk_component_count ?? "—")}</strong><em>From exposure summary</em></div>
            <div className="cv-kpi"><span>Priced rows</span><strong>{String(summary.priced_component_count ?? "—")}</strong><em>Synthetic prices when present</em></div>
          </div>
          <section className="cv-card pad">
            <h3 className="cv-card-title">Component risk detail</h3>
            <div className="cv-table-wrap" style={{ marginTop: 12 }}>
              <table className="cv-table">
                <thead>
                  <tr>
                    <th>MPN</th>
                    <th>Manufacturer</th>
                    <th>Lifecycle</th>
                    <th>Risk</th>
                    <th>Stock</th>
                    <th>Unit price</th>
                    <th>Reasons</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, 50).map((row, i) => (
                    <tr key={i}>
                      <td><strong>{String(row.MPN || row.mpn || row["Part number"] || "")}</strong></td>
                      <td>{String(row.Manufacturer || row.manufacturer || "")}</td>
                      <td>{String(row.Lifecycle || row.lifecycle || row["Lifecycle status"] || "")}</td>
                      <td>{String(row["Risk level"] || row["Risk Level"] || row.risk_level || "")}</td>
                      <td>{String(row.Stock || row.stock || "—")}</td>
                      <td>{String(row["Unit price"] || row.unit_price || "—")}</td>
                      <td className="cv-small-note">{String(row["Risk reasons"] || row.reasons || "").slice(0, 120)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}
    </Shell>
  );
}
