"use client";

import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { GapBanner, LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink } from "@/components/PageHeader";
import { fetchMonitoring } from "@/lib/api";
import { evidenceSourceLabel } from "@/lib/display";
import { PAGE_META } from "@/lib/routes";
import { readLastAnalysis, useRequireSession } from "@/lib/session";

export default function MonitoringPage() {
  const session = useRequireSession();
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    if (!session) return;
    const last = readLastAnalysis();
    setBusy(true);
    fetchMonitoring(session.access_token, last?.analysis_id)
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed"))
      .finally(() => setBusy(false));
  }, [session]);

  if (!session) return null;
  const metrics = (data?.metrics || {}) as Record<string, number>;
  const alerts = (data?.alerts || []) as Array<Record<string, unknown>>;

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.monitoring}
        actions={<PrimaryLink href="/bom-analyzer">Analyze BOM</PrimaryLink>}
      />
      {typeof data?.gap === "string" ? <GapBanner>{data.gap}</GapBanner> : null}
      {busy ? <LoadingCard label="Loading monitoring signals from saved analyses…" /> : null}
      {error ? <div className="cv-error">{error}</div> : null}
      {!busy && data ? (
        <>
          <div className="cv-kpis">
            <div className="cv-kpi tone-blue"><span>Monitored parts</span><strong>{metrics.monitored_parts ?? 0}</strong><em>From latest analysis</em></div>
            <div className="cv-kpi tone-amber"><span>Active alerts</span><strong>{metrics.active_alerts ?? 0}</strong><em>Derived signals</em></div>
            <div className="cv-kpi"><span>High priority</span><strong>{metrics.high_priority ?? 0}</strong><em>Needs review</em></div>
            <div className="cv-kpi"><span>Lifecycle signals</span><strong>{metrics.lifecycle_changes ?? 0}</strong><em>NRND / change flags</em></div>
          </div>
          <section className="cv-card pad">
            <h3 className="cv-card-title">Alert queue</h3>
            <p className="cv-card-subtitle">Review prompts derived from saved analyses; live monitoring is not enabled.</p>
            {alerts.length ? (
              <div className="cv-table-wrap" style={{ marginTop: 12 }}>
                <table className="cv-table">
                  <thead>
                    <tr>
                      <th>Severity</th>
                      <th>Part</th>
                      <th>Type</th>
                      <th>Message</th>
                      <th>Evidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {alerts.map((a, i) => (
                      <tr key={i}>
                        <td><span className={`cv-badge ${String(a.severity).toLowerCase() === "high" ? "red" : "amber"}`}>{String(a.severity)}</span></td>
                        <td><strong>{String(a.part_number || "")}</strong></td>
                        <td>{String(a.alert_type || "")}</td>
                        <td>{String(a.alert_message || "")}</td>
                        <td>{evidenceSourceLabel(a.evidence_source)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="cv-small-note" style={{ marginTop: 12 }}>No derived alerts. Analyze a BOM with NRND or elevated risk parts to populate this queue.</p>
            )}
          </section>
        </>
      ) : null}
    </Shell>
  );
}
