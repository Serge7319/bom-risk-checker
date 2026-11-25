"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AnalysisStageNavigation } from "@/components/AnalysisStageNavigation";
import { Shell } from "@/components/Shell";
import { EmptyState } from "@/components/EmptyState";
import { EvidenceNotice, LoadingCard } from "@/components/GapBanner";
import { KpiCard } from "@/components/KpiCard";
import { StatusPill } from "@/components/StatusPill";
import { PageHeader, PrimaryLink } from "@/components/PageHeader";
import {
  fetchMonitoring,
  fetchMonitoringSlack,
  notifyMonitoringAlert,
  refreshLiveMonitoring,
  refreshMonitoring,
  updateMonitoringPreferences,
  updateMonitoringSlack,
} from "@/lib/api";
import { markReviewProgress, readReviewProgress } from "@/lib/bomDraft";
import { cleanUserText, evidenceSourceLabel } from "@/lib/display";
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
  const [notifying, setNotifying] = useState<string>("");
  const [savingPreferences, setSavingPreferences] = useState<string>("");
  const [slackIntegration, setSlackIntegration] = useState<{
    enabled: boolean; configured: boolean; encryption_ready: boolean; can_manage: boolean;
  } | null>(null);
  const [slackEnabled, setSlackEnabled] = useState(false);
  const [slackWebhookUrl, setSlackWebhookUrl] = useState("");
  const [savingSlack, setSavingSlack] = useState(false);
  const [refreshNote, setRefreshNote] = useState("");
  const [monitoringActionNote, setMonitoringActionNote] = useState("");
  const [liveRefreshOutcome, setLiveRefreshOutcome] = useState<{
    result?: Record<string, unknown>;
    error?: string;
    partNumber?: string;
  } | null>(null);
  const [reloadTick, setReloadTick] = useState(0);

  const requestedAnalysisId = useMemo(() => {
    const fromQuery = (searchParams.get("analysis_id") || "").trim();
    if (fromQuery) return fromQuery;
    return "";
  }, [searchParams]);
  const requestedPartNumber = useMemo(
    () => (searchParams.get("part_number") || "").trim(),
    [searchParams],
  );

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
        const visibleAnalysisId = String(payload.analysis_id || "").trim();
        setActiveAnalysisId(visibleAnalysisId);
        if (visibleAnalysisId) {
          markReviewProgress(
            visibleAnalysisId,
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
    fetchMonitoringSlack(session.access_token)
      .then((result) => {
        if (!active) return;
        setSlackIntegration(result.integration);
        setSlackEnabled(Boolean(result.integration.enabled));
      })
      .catch(() => {
        if (active) setSlackIntegration(null);
      });
    return () => {
      active = false;
    };
  }, [session, requestedAnalysisId, reloadTick]);

  useEffect(() => {
    if (!requestedPartNumber || !data || busy) return;
    document.getElementById("supplier-refresh")?.scrollIntoView({
      block: "start",
      behavior: "smooth",
    });
  }, [requestedPartNumber, data, busy]);

  if (!session) return null;
  const metrics = (data?.metrics || {}) as Record<string, number>;
  const alerts = (data?.alerts || []) as Array<Record<string, unknown>>;
  const freshness = (data?.freshness || {}) as Record<string, unknown>;
  const partStatus = (data?.part_status || []) as Array<Record<string, unknown>>;
  const liveEvidence = (data?.live_evidence || []) as Array<Record<string, unknown>>;
  const requestedPartStatus = requestedPartNumber
    ? partStatus.find(
        (row) => String(row.part_number || "").trim().toLocaleLowerCase()
          === requestedPartNumber.toLocaleLowerCase(),
      )
    : undefined;
  const requestedPartIsInAnalysis = !requestedPartNumber || Boolean(requestedPartStatus);
  const preferences = (data?.preferences || {}) as Record<string, unknown>;
  const liveRefresh = (data?.live_refresh || {}) as Record<string, unknown>;
  const scheduler = (data?.scheduler || {}) as Record<string, unknown>;
  const schedulerReady = scheduler.status === "ready";
  const emailReady = preferences.email_delivery_enabled === true
    && preferences.email_transport_ready === true;
  const failedParts = partStatus.filter((row) => row.provider_failure === true);
  const lastRefreshAt = typeof freshness.last_refresh_at === "string" ? freshness.last_refresh_at : "";
  const visibleLiveEvidence = requestedPartNumber
    ? liveEvidence.filter(
        (row) => String(row.part_number || "").trim().toLocaleLowerCase()
          === requestedPartNumber.toLocaleLowerCase(),
      )
    : liveEvidence;
  const failedRefreshParts = (Array.isArray(liveRefreshOutcome?.result?.failed_parts)
    ? liveRefreshOutcome?.result?.failed_parts
    : []) as Array<Record<string, unknown>>;
  const staleReasons: Record<string, string> = {
    never_refreshed: "Monitoring has never been refreshed for this analysis.",
    refresh_older_than_threshold: `The last refresh is older than ${String(freshness.stale_after_hours ?? 24)} hours.`,
    analysis_newer_than_refresh: "The analysis was saved after the last refresh.",
  };

  async function runRefresh(partNumber?: string) {
    if (!session || !activeAnalysisId || refreshing) return;
    setRefreshing(partNumber || "__analysis__");
    setRefreshNote("");
    setMonitoringActionNote("");
    setLiveRefreshOutcome(null);
    setError("");
    try {
      const result = await refreshMonitoring(session.access_token, {
        analysisId: activeAnalysisId,
        partNumber,
      });
      setMonitoringActionNote(
        `Recalculated ${String(result.scope_label || "selected scope")}. Saved ${String(result.alert_count ?? 0)} alert(s) using saved evidence; suppliers were not queried and Procurement offers were not changed.`,
      );
      setReloadTick((n) => n + 1);
    } catch (err) {
      setMonitoringActionNote(
        `Could not recalculate saved alerts. ${err instanceof Error ? err.message : "Refresh failed"}`,
      );
    } finally {
      setRefreshing("");
    }
  }

  async function runLiveRefresh(partNumber?: string) {
    if (!session || !activeAnalysisId || refreshing) return;
    if (partNumber && !partStatus.some(
      (row) => String(row.part_number || "").trim().toLocaleLowerCase()
        === partNumber.trim().toLocaleLowerCase(),
    )) {
      setLiveRefreshOutcome({
        error: `Part ${partNumber} is not in this saved analysis. Open the matching analysis and try again.`,
        partNumber,
      });
      return;
    }
    setRefreshing(partNumber || "__live_analysis__");
    setRefreshNote("");
    setMonitoringActionNote("");
    setLiveRefreshOutcome(null);
    setError("");
    try {
      const result = await refreshLiveMonitoring(session.access_token, {
        analysis_id: activeAnalysisId,
        part_number: partNumber,
      });
      setLiveRefreshOutcome({ result, partNumber });
      setReloadTick((n) => n + 1);
    } catch (err) {
      setLiveRefreshOutcome({
        error: err instanceof Error ? err.message : "Live supplier refresh failed",
        partNumber,
      });
    } finally {
      setRefreshing("");
    }
  }

  async function savePreference(name: string, value: boolean) {
    if (!session || savingPreferences) return;
    setSavingPreferences(name);
    setError("");
    setRefreshNote("");
    try {
      const result = await updateMonitoringPreferences(session.access_token, { [name]: value });
      setData((current) => current ? { ...current, preferences: result.preferences } : current);
      setRefreshNote("Monitoring preference saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save monitoring preference");
    } finally {
      setSavingPreferences("");
    }
  }

  async function saveSlackIntegration(clear = false) {
    if (!session || savingSlack) return;
    setSavingSlack(true);
    setError("");
    try {
      const result = await updateMonitoringSlack(session.access_token, {
        enabled: clear ? false : slackEnabled,
        ...(clear ? { clear: true } : {}),
        ...(!clear && slackWebhookUrl.trim() ? { webhook_url: slackWebhookUrl.trim() } : {}),
      });
      setSlackIntegration(result.integration);
      setSlackEnabled(Boolean(result.integration.enabled));
      setSlackWebhookUrl("");
      setRefreshNote(clear ? "Slack connection removed." : "Slack alert settings saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save Slack alert settings.");
    } finally {
      setSavingSlack(false);
    }
  }

  async function runNotify(alertId: string) {
    if (!session || !alertId || notifying) return;
    setNotifying(alertId);
    setRefreshNote("");
    setError("");
    try {
      const result = await notifyMonitoringAlert(session.access_token, alertId);
      setRefreshNote(
        `Manual notification request: ${cleanUserText(result.status || result.detail || "requested")}. Refresh never sends email.`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Notify failed");
    } finally {
      setNotifying("");
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
          Monitoring signals for this saved analysis
          {requestedAnalysisId ? " (selected from report)" : " (last remembered analysis)"}.
        </p>
      ) : null}
      {<EvidenceNotice gap={data?.gap} />}
      {busy ? <LoadingCard label="Loading monitoring signals from saved analyses…" /> : null}
      {error ? <div className="cv-error" role="alert">Monitoring could not load. {error}</div> : null}
      {!busy && data ? (
        <>
          <div className="cv-kpis">
            <KpiCard icon="monitor" tone="blue" label="Tracked components" value={metrics.monitored_parts ?? 0} status={Number(metrics.monitored_parts ?? 0) > 0 ? { label: "In selected analysis", tone: "blue" } : { label: "No parts tracked", tone: "gray" }} detail="Parts available to monitor" />
            <KpiCard icon="bell" tone={Number(metrics.active_alerts ?? 0) > 0 ? "amber" : "green"} label="Alerts to review" value={metrics.active_alerts ?? 0} status={Number(metrics.active_alerts ?? 0) > 0 ? { label: "Needs attention", tone: "amber" } : { label: "No active alerts", tone: "green" }} detail="Signals derived from saved evidence" />
            <KpiCard icon="clock" tone={Number(metrics.lifecycle_changes ?? 0) > 0 ? "amber" : "green"} label="Lifecycle flags" value={metrics.lifecycle_changes ?? 0} status={Number(metrics.lifecycle_changes ?? 0) > 0 ? { label: "Changes detected", tone: "amber" } : { label: "No changes", tone: "green" }} detail="NRND or lifecycle change signals" />
          </div>
          <section className="cv-card pad" id="supplier-refresh" aria-label="Monitoring freshness">
            <h3 className="cv-card-title">Data freshness</h3>
            <p className="cv-card-subtitle">
              {lastRefreshAt
                ? `Last refresh: ${new Date(lastRefreshAt).toLocaleString()}.`
                : "Never refreshed."}{" "}
              Opening this page does not update data. The actions below affect Monitoring only; these buttons do not send email.
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
            <div
              className="cv-evidence-context"
              role="note"
              style={{ marginTop: 10, display: "grid", gap: 7 }}
            >
              <div>
                <strong>Refresh supplier data:</strong>{" "}
                {requestedPartNumber
                  ? <>checks configured distributors for <strong>{requestedPartNumber}</strong></>
                  : "checks configured distributors for exact MPNs in this analysis"}{" "}
                and saves verified results to Monitoring; it may update alerts.
              </div>
              <div>
                <strong>Recalculate saved alerts:</strong>{" "}
                uses saved Monitoring evidence only; no supplier lookup runs.
              </div>
              <div>
                <strong>Procurement offers:</strong>{" "}
                unchanged by either Monitoring action. Run a new BOM analysis and upload the BOM again for a new Procurement offer snapshot.
              </div>
            </div>
            {requestedPartNumber && !requestedPartIsInAnalysis ? (
              <div className="cv-error" role="alert" style={{ marginTop: 8 }}>
                The linked part <strong>{requestedPartNumber}</strong> is not in this saved analysis. No supplier lookup will run; open the matching BOM analysis and try again.
              </div>
            ) : null}
            <div style={{ marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button
                type="button"
                className="cv-button primary"
                disabled={!activeAnalysisId || Boolean(refreshing) || !requestedPartIsInAnalysis}
                onClick={() => void runLiveRefresh(requestedPartNumber || undefined)}
              >
                {refreshing === (requestedPartNumber || "__live_analysis__")
                  ? "Checking suppliers…"
                  : requestedPartNumber
                    ? "Refresh supplier data for " + requestedPartNumber
                    : "Refresh supplier data"}
              </button>
              <button
                type="button"
                className="cv-button"
                disabled={!activeAnalysisId || Boolean(refreshing)}
                onClick={() => void runRefresh()}
              >
                {refreshing === "__analysis__" ? "Recalculating…" : "Recalculate saved alerts"}
              </button>
              {!activeAnalysisId ? <span className="cv-card-subtitle"> Select an analysis to refresh it.</span> : null}
            </div>
            {refreshNote ? <div className="cv-evidence-context" role="status" style={{ marginTop: 10 }}>{refreshNote}</div> : null}
            {monitoringActionNote ? <div className="cv-evidence-context" role="status" style={{ marginTop: 10 }}>{monitoringActionNote}</div> : null}
            {liveRefreshOutcome ? (
              <div
                className={liveRefreshOutcome.error ? "cv-error" : "cv-evidence-context"}
                role={liveRefreshOutcome.error ? "alert" : "status"}
                style={{ marginTop: 10, display: "grid", gap: 8 }}
              >
                <strong>{liveRefreshOutcome.error ? "Supplier refresh did not complete" : "Supplier refresh finished"}</strong>
                {liveRefreshOutcome.error ? (
                  <p style={{ margin: 0 }}>{cleanUserText(liveRefreshOutcome.error)}</p>
                ) : (
                  <>
                    <p style={{ margin: 0 }}>
                      Checked {String(liveRefreshOutcome.result?.supplier_calls ?? 0)} part check(s).
                      {" "}Saved verified Monitoring evidence for {String(liveRefreshOutcome.result?.updated_parts ?? 0)} part(s)
                      {" "}and detected {String(liveRefreshOutcome.result?.alert_count ?? 0)} change alert(s).
                    </p>
                    {failedRefreshParts.length ? (
                      <ul style={{ margin: 0, paddingLeft: 20 }}>
                        {failedRefreshParts.map((row, index) => {
                          const status = String(row.status || "");
                          const reason: Record<string, string> = {
                            supplier_unavailable: "Configured supplier lookup failed.",
                            exact_supplier_match_unavailable: "No exact part-number match was returned.",
                            manufacturer_identity_mismatch: "The returned listing did not verify the requested manufacturer.",
                            no_usable_measurements: "An exact match was found, but no usable stock, price, lead-time, or lifecycle value was returned.",
                          };
                          return (
                            <li key={index}>
                              {cleanUserText(String(row.part_number || "Part"))}:{" "}
                              {reason[status] || cleanUserText(status.replaceAll("_", " "))}.
                            </li>
                          );
                        })}
                      </ul>
                    ) : null}
                  </>
                )}
                <p style={{ margin: 0 }}>
                  This refresh updates Monitoring evidence and alerts. It does not replace the saved Procurement offers.
                  To get new offers, run a new BOM analysis with the same BOM, then select that new report in Procurement.
                </p>
                <div><PrimaryLink href="/bom-analyzer">Run a new BOM analysis</PrimaryLink></div>
              </div>
            ) : null}
            <div style={{ marginTop: 12 }}>
              <h4 style={{ margin: "0 0 4px" }}>Latest verified supplier evidence</h4>
              <p className="cv-small-note" style={{ margin: 0 }}>
                Exact-MPN-matched values saved for Monitoring. Each field shows when the supplier last returned it.
              </p>
              {visibleLiveEvidence.length ? (
                visibleLiveEvidence.map((row, index) => {
                  const fieldTimes = (row.field_retrieved_at || {}) as Record<string, unknown>;
                  const observed = new Set(
                    Array.isArray(row.observed_fields) ? row.observed_fields.map(String) : [],
                  );
                  const fields = [
                    { key: "stock", label: "Stock", value: row.stock },
                    {
                      key: "unit_price",
                      label: "Unit price",
                      value: row.unit_price == null
                        ? row.unit_price
                        : `${row.currency ? String(row.currency) + " " : ""}${String(row.unit_price)}`,
                    },
                    {
                      key: "lead_time_weeks",
                      label: "Lead time",
                      value: row.lead_time_weeks == null ? row.lead_time_weeks : `${String(row.lead_time_weeks)} weeks`,
                    },
                    { key: "lifecycle_status", label: "Lifecycle", value: row.lifecycle_status },
                    { key: "risk_level", label: "Risk", value: row.risk_level },
                  ];
                  const productUrl = String(row.product_url || "");
                  return (
                    <div className="cv-card" key={`${String(row.part_number)}-${index}`} style={{ padding: 12, marginTop: 10 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                        <strong>{cleanUserText(String(row.supplier || "Configured distributor"))} · {cleanUserText(String(row.part_number || ""))}</strong>
                        <span className="cv-badge green">Exact MPN matched</span>
                      </div>
                      <p className="cv-small-note" style={{ margin: "4px 0 0" }}>
                        Requested MPN matched {cleanUserText(String(row.manufacturer || "the supplier listing"))}
                        {row.manufacturer_part_number ? ` (${cleanUserText(String(row.manufacturer_part_number))})` : ""}.
                      </p>
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 8, marginTop: 10 }}>
                        {fields.map((field) => {
                          const observedAt = fieldTimes[field.key];
                          const freshnessLabel = observed.has(field.key)
                            ? "Returned in this refresh"
                            : observedAt
                              ? `Last returned ${new Date(String(observedAt)).toLocaleString()}`
                              : "Not returned in this refresh";
                          return (
                            <div key={field.key} style={{ border: "1px solid var(--cv-border, #d7e1ed)", borderRadius: 8, padding: 8 }}>
                              <small>{field.label}</small>
                              <div><strong>{field.value == null || String(field.value).trim() === "" ? "Not reported" : cleanUserText(String(field.value))}</strong></div>
                              <small className="cv-small-note">{freshnessLabel}</small>
                            </div>
                          );
                        })}
                      </div>
                      <p className="cv-small-note" style={{ margin: "8px 0 0" }}>
                        Supplier check completed {row.retrieved_at ? new Date(String(row.retrieved_at)).toLocaleString() : "at an unknown time"}.
                        {productUrl.startsWith("https://") ? <>{" "}<a href={productUrl} target="_blank" rel="noreferrer">Open supplier listing</a></> : null}
                      </p>
                    </div>
                  );
                })
              ) : (
                <p className="cv-small-note" style={{ margin: "8px 0 0" }}>
                  {requestedPartNumber
                    ? `No verified live supplier snapshot is saved for ${requestedPartNumber} in this analysis yet.`
                    : "No verified live supplier snapshots are saved for this analysis yet."}
                </p>
              )}
            </div>
            {liveRefresh.status !== "ready" ? (
              <p className="cv-small-note" style={{ marginTop: 8 }}>
                Live supplier refresh is {cleanUserText(String(liveRefresh.status || "not connected").replaceAll("_", " "))}. {cleanUserText(liveRefresh.detail) || "Provider credentials and the live refresh gate are required."}
              </p>
            ) : null}
          </section>
          <section className="cv-card pad" aria-label="Monitoring preferences">
            <h3 className="cv-card-title">Scheduled monitoring and email</h3>
            <p className="cv-card-subtitle">
              {schedulerReady
                ? "Automatic supplier checks run every six hours for saved analyses in this workspace after you opt in."
                : "Automatic supplier checks are not running yet. Your preference will take effect when scheduled monitoring is enabled."}{" "}
              Email alerts go only to your verified Cadivor account address: <strong>{String(preferences.email || session.email)}</strong>.
            </p>
            <div style={{ display: "grid", gap: 10, marginTop: 12 }}>
              <label style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                <input
                  type="checkbox"
                  checked={Boolean(preferences.supplier_checks)}
                  disabled={Boolean(savingPreferences)}
                  onChange={(event) => void savePreference("supplier_checks", event.target.checked)}
                />
                <span><strong>{schedulerReady ? "Automatically check supplier data" : "Enable automatic supplier checks when available"}</strong><br /><small className="cv-small-note">Only exact, identity-matched results update the monitoring snapshot.</small></span>
              </label>
              <label style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                <input
                  type="checkbox"
                  checked={Boolean(preferences.email_alerts)}
                  disabled={Boolean(savingPreferences)}
                  onChange={(event) => void savePreference("email_alerts", event.target.checked)}
                />
                <span><strong>Email me when a new monitoring alert is found</strong><br /><small className="cv-small-note">{emailReady ? "Email delivery is on. You can turn this off at any time." : "Your preference is saved, but email alerts are not being sent yet."}</small></span>
              </label>
              <label style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                <input
                  type="checkbox"
                  checked={Boolean(preferences.weekly_digest)}
                  disabled={Boolean(savingPreferences) || !Boolean(preferences.email_alerts)}
                  onChange={(event) => void savePreference("weekly_digest", event.target.checked)}
                />
                <span><strong>Send me a weekly monitoring digest</strong><br /><small className="cv-small-note">Sent at most once every seven days to your verified account email. Turn on alert emails first; the digest includes active changes from the prior week.</small></span>
              </label>
            </div>
          </section>
          <section className="cv-card pad" aria-label="Slack alerts">
            <h3 className="cv-card-title">Slack alerts</h3>
            <p className="cv-card-subtitle">
              Send one channel message when a scheduled supplier check finds new alerts. Messages include alert counts and a Cadivor link; part numbers, BOM names, and supplier values stay in Cadivor.
            </p>
            {!slackIntegration ? (
              <p className="cv-small-note" role="status">Slack connection status is unavailable. Reload to try again.</p>
            ) : slackIntegration.can_manage ? (
              <div style={{ display: "grid", gap: 10, maxWidth: 620, marginTop: 12 }}>
                <label style={{ display: "flex", gap: 10, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={slackEnabled}
                    disabled={savingSlack || !slackIntegration.encryption_ready}
                    onChange={(event) => setSlackEnabled(event.target.checked)}
                  />
                  <span><strong>Enable Slack alert delivery</strong><br /><small className="cv-small-note">{slackIntegration.configured ? "A workspace webhook is saved." : "No Slack channel is connected."}</small></span>
                </label>
                <label className="cv-field" htmlFor="monitoring-slack-webhook">
                  <span>Slack incoming webhook URL</span>
                  <input
                    id="monitoring-slack-webhook"
                    type="password"
                    autoComplete="new-password"
                    value={slackWebhookUrl}
                    placeholder={slackIntegration.configured ? "Saved securely · enter a new URL to replace" : "https://hooks.slack.com/services/…"}
                    onChange={(event) => setSlackWebhookUrl(event.target.value)}
                  />
                </label>
                {!slackIntegration.encryption_ready ? <p className="cv-small-note">Cadivor’s Slack webhook encryption key is not configured yet.</p> : null}
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <button className="cv-button primary" type="button" disabled={savingSlack || !slackIntegration.encryption_ready} onClick={() => void saveSlackIntegration()}>
                    {savingSlack ? "Saving…" : "Save Slack settings"}
                  </button>
                  {slackIntegration.configured ? (
                    <button className="cv-button" type="button" disabled={savingSlack} onClick={() => void saveSlackIntegration(true)}>Disconnect Slack</button>
                  ) : null}
                </div>
              </div>
            ) : (
              <p className="cv-small-note" style={{ marginTop: 10 }}>
                {slackIntegration.enabled ? "Slack alerts are enabled for this workspace." : "Ask a workspace owner or admin to connect Slack."}
              </p>
            )}
          </section>
          <section className="cv-card pad">
            <h3 className="cv-card-title">Alerts and changes</h3>
            <p className="cv-card-subtitle">
              Active signals for this selection only. Inactive/reconciled alerts are hidden.
              Supplier checks use live provider data only when configured. Email alerts require your opt-in and the delivery service to be enabled.
            </p>
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
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {alerts.map((a, i) => (
                      <tr key={i}>
                        <td><StatusPill kind="risk" value={a.severity || "Unknown"} /></td>
                        <td><strong>{String(a.part_number || "")}</strong></td>
                        <td>{String(a.alert_type || "")}</td>
                        <td>{cleanUserText(a.alert_message)}</td>
                        <td>{evidenceSourceLabel(a.evidence_source)}</td>
                        <td>{a.persisted === false ? <span className="cv-badge amber" title="This alert has not been saved as an alert record. Recalculate saved alerts saves derived alerts without contacting suppliers.">Alert not saved</span> : <span className="cv-badge green">Saved</span>}</td>
                        <td style={{ whiteSpace: "nowrap" }}>
                          <button
                            type="button"
                            className="cv-button small"
                            disabled={!activeAnalysisId || Boolean(refreshing)}
                            onClick={() => void runLiveRefresh(String(a.part_number || ""))}
                          >
                            {refreshing === String(a.part_number || "") ? "Checking…" : "Refresh supplier"}
                          </button>{" "}
                          <button
                            type="button"
                            className="cv-button small"
                            disabled={!a.id || Boolean(notifying)}
                            title="Explicit email action — not run by Refresh"
                            onClick={() => void runNotify(String(a.id || ""))}
                          >
                            {a.id && notifying === String(a.id)
                              ? "Notifying…"
                              : "Notify"}
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
