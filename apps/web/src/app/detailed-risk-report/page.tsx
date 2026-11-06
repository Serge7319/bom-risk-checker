"use client";

import { useEffect, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { Shell } from "@/components/Shell";
import { GapBanner, LoadingCard } from "@/components/GapBanner";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader, PrimaryLink } from "@/components/PageHeader";
import { fetchDetailedRisk } from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { readLastAnalysis, useRequireSession } from "@/lib/session";

function cell(value: unknown, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

export default function DetailedRiskPage() {
  const session = useRequireSession();
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    if (!session) return;
    const last = readLastAnalysis(session);
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
        actions={<PrimaryLink href="/reports">Open saved reports</PrimaryLink>}
      />
      {typeof data?.gap === "string" ? <GapBanner>{String(data.gap)}</GapBanner> : null}
      {busy ? <LoadingCard label="Loading detailed risk rows…" /> : null}
      {error ? <div className="cv-error" role="alert">Risk details could not load. {error}</div> : null}
      {!busy && data ? (
        rows.length ? <>
          <div className="cv-kpis">
            <KpiCard icon="shield" tone="blue" label="Health score" value={data.health_score == null ? "Not scored" : `${String(data.health_score)}/100`} detail={String(data.health_status || "Overall report rating")} />
            <KpiCard icon="box" label="Components assessed" value={rows.length} detail="Rows in this report" />
            <KpiCard icon="risk" tone="amber" label="High-risk components" value={String(summary.open_high_risk_component_count ?? "Not reported")} detail="Review the evidence before release" />
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
                      <td><strong>{cell(row.MPN ?? row.mpn ?? row["Part number"])}</strong></td>
                      <td>{cell(row.Manufacturer ?? row.manufacturer)}</td>
                      <td>{cell(row.Lifecycle ?? row.lifecycle ?? row["Lifecycle status"])}</td>
                      <td>{cell(row.Risk ?? row["Risk level"] ?? row["Risk Level"] ?? row.risk_level)}</td>
                      <td>{cell(row.Stock ?? row.stock)}</td>
                      <td>{cell(row["Unit price"] ?? row.unit_price)}</td>
                      <td className="cv-small-note">{cell(row.Why ?? row["Risk reasons"] ?? row.reasons).slice(0, 120)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </> : <EmptyState icon="risk" title="No component risk rows found" body="Open a saved analysis with component data to view the detailed risk breakdown." action={<PrimaryLink href="/reports">Choose a saved report</PrimaryLink>} />
      ) : null}
    </Shell>
  );
}

