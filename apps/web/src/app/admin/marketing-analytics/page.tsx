"use client";

import { useEffect, useMemo, useState } from "react";
import { Shell } from "@/components/Shell";
import { PageHeader } from "@/components/PageHeader";
import { KpiCard } from "@/components/KpiCard";
import { EmptyState } from "@/components/EmptyState";
import { useRequireSession } from "@/lib/session";
import { PAGE_META } from "@/lib/routes";

type FunnelRow = {
  event: string;
  source: string;
  traffic_source: string;
  events: number;
  sessions: number;
};

const EVENT_LABELS: Record<string, string> = {
  page_view: "Page views",
  cta_click: "CTA clicks",
  free_audit_started: "Free audits started",
  free_audit_completed: "Free audits completed",
  signup_started: "Signups started",
  signup_completed: "Email verified / signup completed",
  bom_uploaded: "BOM analyses saved",
  first_analysis_completed: "First analyses completed",
  trial_started: "Trials started",
  upgrade_clicked: "Upgrade clicks",
  checkout_started: "Checkouts started",
  subscription_created: "Subscriptions created",
  demo_requested: "Demo requests",
  one_time_report_purchased: "One-time reports purchased",
};

export default function MarketingAnalyticsPage() {
  const session = useRequireSession();
  const [days, setDays] = useState(30);
  const [rows, setRows] = useState<FunnelRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    setBusy(true);
    setError("");
    fetch(`/api/admin/marketing-analytics?days=${days}`, {
      headers: { Authorization: `Bearer ${session.access_token}` },
      cache: "no-store",
    }).then(async (response) => {
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(String(payload.detail || "Analytics could not be loaded."));
      if (!cancelled) setRows(Array.isArray(payload.rows) ? payload.rows as FunnelRow[] : []);
    }).catch((err) => {
      if (!cancelled) setError(err instanceof Error ? err.message : "Analytics could not be loaded.");
    }).finally(() => {
      if (!cancelled) { setBusy(false); setLoaded(true); }
    });
    return () => { cancelled = true; };
  }, [session, days]);

  const totals = useMemo(() => rows.reduce((sum, row) => sum + Number(row.events || 0), 0), [rows]);
  if (!session) return null;

  return (
    <Shell session={session}>
      <PageHeader
        meta={{ ...PAGE_META.settings, title: "Growth analytics", eyebrow: "Platform", description: "Measure how visitors move from discovery to first value and paid conversion." }}
        actions={
          <select aria-label="Analytics time range" value={days} onChange={(event) => setDays(Number(event.target.value))}>
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
        }
      />
      <section className="cv-card pad" style={{ marginBottom: 16 }}>
        <h2 className="cv-card-title">Visit-to-paid funnel</h2>
        <p className="cv-card-subtitle">
          First-party event totals by traffic source for the last {days} days. Events contain no email, IP address, BOM content, or part number. Data is retained for up to 180 days.
        </p>
        {busy ? <p className="cv-small-note" role="status">Loading funnel…</p> : null}
        {error ? <div className="cv-error" role="alert">{error}</div> : null}
        {!busy && !error && loaded && rows.length === 0 ? (
          <EmptyState icon="spark" title="No tracked activity yet" body="Page views and funnel events will appear here after the tracking release is deployed." />
        ) : null}
        {!busy && !error && rows.length ? (
          <>
            <div className="cv-kpis" style={{ margin: "16px 0" }}>
              <KpiCard icon="spark" tone="blue" label="Total events" value={totals.toLocaleString()} detail={`Last ${days} days`} />
              <KpiCard icon="search" label="Traffic sources" value={new Set(rows.map((row) => row.traffic_source)).size} detail="UTM source or direct" />
              <KpiCard icon="report" tone="amber" label="Funnel stages" value={new Set(rows.map((row) => row.event)).size} detail="Tracked milestones" />
            </div>
            <div className="cv-table-wrap">
              <table className="cv-table">
                <thead><tr><th>Stage</th><th>Traffic source</th><th>Entry</th><th>Events</th><th>Sessions</th></tr></thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={`${row.event}:${row.traffic_source}:${row.source}`}>
                      <td><strong>{EVENT_LABELS[row.event] || row.event}</strong></td>
                      <td>{row.traffic_source}</td>
                      <td>{row.source === "marketing" ? "Marketing site" : "Cadivor app"}</td>
                      <td>{Number(row.events).toLocaleString()}</td>
                      <td>{Number(row.sessions).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
      </section>
    </Shell>
  );
}
