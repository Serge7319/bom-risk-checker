"use client";

import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { EmptyState } from "@/components/EmptyState";
import { GapBanner, LoadingCard } from "@/components/GapBanner";
import { KpiCard } from "@/components/KpiCard";
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
    const last = readLastAnalysis(session);
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
        actions={<PrimaryLink href="/reports">View saved reports</PrimaryLink>}
      />
      {typeof data?.gap === "string" ? <GapBanner>{data.gap}</GapBanner> : null}
      {busy ? <LoadingCard label="Loading monitoring signals from saved analyses…" /> : null}
      {error ? <div className="cv-error" role="alert">Monitoring could not load. {error}</div> : null}
      {!busy && data ? (
        <>
          <div className="cv-kpis">
            <KpiCard icon="monitor" tone="blue" label="Tracked components" value={metrics.monitored_parts ?? 0} detail="Parts in the selected analysis" />
            <KpiCard icon="bell" tone="amber" label="Alerts to review" value={metrics.active_alerts ?? 0} detail="Signals derived from saved evidence" />
            <KpiCard icon="clock" label="Lifecycle flags" value={metrics.lifecycle_changes ?? 0} detail="NRND or lifecycle change signals" />
          </div>
          <section className="cv-card pad">
            <h3 className="cv-card-title">Alerts and changes</h3>
            <p className="cv-card-subtitle">Review signals derived from saved analyses. Scheduled refresh and email delivery are currently disabled.</p>
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
              <EmptyState
                icon="monitor"
                title={Number(metrics.monitored_parts || 0) > 0 ? "No alerts need review" : "No components are being tracked yet"}
                body={Number(metrics.monitored_parts || 0) > 0 ? "The selected analysis has no derived lifecycle or risk alerts." : "Analyze a BOM to create a component list that can be reviewed here."}
                action={Number(metrics.monitored_parts || 0) > 0 ? undefined : <PrimaryLink href="/bom-analyzer">Open BOM Analyzer</PrimaryLink>}
              />
            )}
          </section>
        </>
      ) : null}
    </Shell>
  );
}

