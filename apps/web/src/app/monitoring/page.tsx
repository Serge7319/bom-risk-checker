"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AnalysisStageNavigation } from "@/components/AnalysisStageNavigation";
import { Shell } from "@/components/Shell";
import { EmptyState } from "@/components/EmptyState";
import { EvidenceNotice, LoadingCard } from "@/components/GapBanner";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader, PrimaryLink } from "@/components/PageHeader";
import { fetchMonitoring, refreshMonitoring } from "@/lib/api";
import { markReviewProgress, readReviewProgress } from "@/lib/bomDraft";
import { evidenceSourceLabel } from "@/lib/display";
import { PAGE_META } from "@/lib/routes";
import { readLastAnalysis, useRequireSession } from "@/lib/session";

function MonitoringPageInner() {
  const session = useRequireSession();
  const searchParams = useSearchParams();
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const [activeAnalysisId, setActiveAnalysisId] = useState<string>("");
  const [refreshing, setRefreshing] = useState<string>("");
  const [refreshNote, setRefreshNote] = useState("");
  const [reloadTick, setReloadTick] = useState(0);

  const requestedAnalysisId = useMemo(() => {
    const fromQuery = (searchParams.get("analysis_id") || "").trim();
    if (fromQuery) return fromQuery;
    return "";
  }, [searchParams]);

  useEffect(() => {
    if (!session) return;
    let active = true;
    const last = readLastAnalysis(session);
    const analysisId = requestedAnalysisId || last?.analysis_id || "";
    setActiveAnalysisId(analysisId);
    setBusy(true);
    setError("");
    setData(null);
    fetchMonitoring(session.access_token, analysisId || undefined)
      .then((payload) => {
        if (!active) return;
        setData(payload);
        if (analysisId) {
          markReviewProgress(
            analysisId,
            { monitorOpenedAt: new Date().toISOString() },
            session,
          );
        }
      })
      .catch((err) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed");
        // Failed loads must not advance Monitor progress.
        if (analysisId) {
          const existing = readReviewProgress(analysisId, session);
          if (existing.monitorOpenedAt) {
            // leave existing progress from a prior successful visit
          }
        }
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [session, requestedAnalysisId, reloadTick]);

  if (!session) return null;
  const metrics = (data?.metrics || {}) as Record<string, number>;
  const alerts = (data?.alerts || []) as Array<Record<string, unknown>>;
  const freshness = (data?.freshness || {}) as Record<string, unknown>;
  const partStatus = (data?.part_status || []) as Array<Record<string, unknown>>;
  const failedParts = partStatus.filter((row) => row.provider_failure === true);
  const lastRefreshAt = typeof freshness.last_refresh_at === "string" ? freshness.last_refresh_at : "";
  const staleReasons: Record<string, string> = {
    never_refreshed: "Monitoring has never been refreshed for this analysis.",
    refresh_older_than_threshold: `The last refresh is older than ${String(freshness.stale_after_hours ?? 24)} hours.`,
    analysis_newer_than_refresh: "The analysis was saved after the last refresh.",
  };

  async function runRefresh(partNumber?: string) {
    if (!session || !activeAnalysisId || refreshing) return;
    setRefreshing(partNumber || "__analysis__");
    setRefreshNote("");
    setError("");
    try {
      const result = await refreshMonitoring(session.access_token, {
        analysisId: activeAnalysisId,
        partNumber,
      });
      setRefreshNote(
        `Refreshed ${String(result.scope_label || "selected scope")}. Saved ${String(result.alert_count ?? 0)} alert(s) from the saved analysis; suppliers were not re-queried.`,
      );
      setReloadTick((n) => n + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Refresh failed");
    } finally {
      setRefreshing("");
    }
  }

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.monitoring}
        actions={<PrimaryLink href="/reports">View saved reports</PrimaryLink>}
      />
      <AnalysisStageNavigation analysisId={activeAnalysisId} current="monitor" />
      {activeAnalysisId ? (
        <p className="cv-evidence-context" role="note">
          Monitoring signals for analysis <strong>{activeAnalysisId}</strong>
          {requestedAnalysisId ? " (selected from report)" : " (last remembered analysis)"}.
        </p>
      ) : null}
      {<EvidenceNotice gap={data?.gap} />}
      {busy ? <LoadingCard label="Loading monitoring signals from saved analyses…" /> : null}
      {refreshNote ? <div className="cv-evidence-context" role="status">{refreshNote}</div> : null}
      {error ? <div className="cv-error" role="alert">Monitoring could not load. {error}</div> : null}
      {!busy && data ? (
        <>
          <div className="cv-kpis">
            <KpiCard icon="monitor" tone="blue" label="Tracked components" value={metrics.monitored_parts ?? 0} detail="Parts in the selected analysis" />
            <KpiCard icon="bell" tone="amber" label="Alerts to review" value={metrics.active_alerts ?? 0} detail="Signals derived from saved evidence" />
            <KpiCard icon="clock" label="Lifecycle flags" value={metrics.lifecycle_changes ?? 0} detail="NRND or lifecycle change signals" />
          </div>
          <section className="cv-card pad" aria-label="Monitoring freshness">
            <h3 className="cv-card-title">Data freshness</h3>
            <p className="cv-card-subtitle">
              {lastRefreshAt
                ? `Last refresh: ${new Date(lastRefreshAt).toLocaleString()}.`
                : "Never refreshed."}{" "}
              Opening this page does not refresh or save anything. Refresh re-derives alerts from the saved analysis; it does not query suppliers for live data.
            </p>
            {freshness.stale === true ? (
              <div className="cv-error" role="status">
                Stale data. {staleReasons[String(freshness.stale_reason)] || "Refresh to update saved alerts."}
              </div>
            ) : null}
            {failedParts.length ? (
              <div className="cv-error" role="alert" style={{ marginTop: 8 }}>
                Supplier data could not be verified for {failedParts.length} part(s):{" "}
                {failedParts
                  .map((row) => `${String(row.part_number)}${Array.isArray(row.failed_sources) && row.failed_sources.length ? ` (${(row.failed_sources as string[]).join(", ")})` : ""}`)
                  .join(", ")}
                . A provider failure is not the same as &ldquo;no supplier data found&rdquo;.
              </div>
            ) : null}
            <div style={{ marginTop: 12 }}>
              <button
                type="button"
                className="cv-button primary"
                disabled={!activeAnalysisId || Boolean(refreshing)}
                onClick={() => void runRefresh()}
              >
                {refreshing === "__analysis__" ? "Refreshing…" : "Refresh this analysis"}
              </button>
              {!activeAnalysisId ? <span className="cv-card-subtitle"> Select an analysis to refresh it.</span> : null}
            </div>
          </section>
          <section className="cv-card pad">
            <h3 className="cv-card-title">Alerts and changes</h3>
            <p className="cv-card-subtitle">Signals derived from the saved analysis for this selection only. Scheduled refresh and email delivery are currently disabled.</p>
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
                      <th>Saved</th>
                      <th>Refresh</th>
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
                        <td>{a.persisted === false ? <span className="cv-badge amber">Not saved — refresh</span> : <span className="cv-badge green">Saved</span>}</td>
                        <td>
                          <button
                            type="button"
                            className="cv-button small"
                            disabled={!activeAnalysisId || Boolean(refreshing)}
                            onClick={() => void runRefresh(String(a.part_number || ""))}
                          >
                            {refreshing === String(a.part_number || "") ? "Refreshing…" : "Refresh part"}
                          </button>
                        </td>
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


export default function MonitoringPage() {
  return (
    <Suspense fallback={null}>
      <MonitoringPageInner />
    </Suspense>
  );
}
