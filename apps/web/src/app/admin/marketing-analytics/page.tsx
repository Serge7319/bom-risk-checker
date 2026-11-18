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
  traffic_source: string;
  events: number;
  sessions: number;
  origins: string[];
  visit_sessions: number;
  conversion_from_visit_pct: number | null;
};

const EVENT_LABELS: Record<string, string> = {
  page_view: "Visits",
  cta_click: "CTA clicks",
  free_audit_started: "Free audits started",
  free_audit_completed: "Free audits completed",
  signup_started: "Signups started",
  signup_completed: "Accounts verified",
  bom_uploaded: "BOM analyses saved",
  first_analysis_completed: "First analyses completed",
  trial_started: "Trials started",
  upgrade_clicked: "Upgrade interest",
  checkout_started: "Checkouts started",
  subscription_created: "Subscriptions created",
  one_time_report_purchased: "One-time reports purchased",
  demo_requested: "Demo requests",
};

const EVENT_ORDER = Object.keys(EVENT_LABELS);

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
  const orderedRows = useMemo(() => {
    const rank = new Map(EVENT_ORDER.map((event, index) => [event, index]));
    return [...rows].sort((a, b) =>
      a.traffic_source.localeCompare(b.traffic_source) ||
      (rank.get(a.event) ?? Number.MAX_SAFE_INTEGER) - (rank.get(b.event) ?? Number.MAX_SAFE_INTEGER),
    );
  }, [rows]);
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
          Opted-in sessions by traffic source for the last {days} days. Each rate is the share of page-view sessions from that same source that reached the event. Demo requests and one-time reports are separate outcomes. Events contain no email, IP address, BOM content, or part number; data is retained for up to 180 days.
        </p>
        {busy ? <p className="cv-small-note" role="status">Loading funnel…</p> : null}
        {error ? <div className="cv-error" role="alert">{error}</div> : null}
        {!busy && !error && loaded && rows.length === 0 ? (
          <EmptyState icon="spark" title="No opted-in activity yet" body="This dashboard records activity only after a visitor allows optional analytics. Page views and funnel events will appear here as opted-in visitors use Cadivor." />
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
                <thead><tr><th>Stage</th><th>Traffic source</th><th>Unique sessions</th><th>Share of visits</th><th>Events</th><th>Recorded in</th></tr></thead>
                <tbody>
                  {orderedRows.map((row) => (
                    <tr key={`${row.event}:${row.traffic_source}`}>
                      <td><strong>{EVENT_LABELS[row.event] || row.event}</strong></td>
                      <td>{row.traffic_source}</td>
                      <td>{Number(row.sessions).toLocaleString()}</td>
                      <td>
                        {row.conversion_from_visit_pct === null ? (
                          <span className="cv-small-note">{row.event === "page_view" ? "Visit baseline" : "No visit baseline"}</span>
                        ) : (
                          <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 150 }}>
                            <progress
                              aria-label={`${EVENT_LABELS[row.event] || row.event}: ${row.conversion_from_visit_pct}% of visits`}
                              max={100}
                              value={Math.max(0, Math.min(100, row.conversion_from_visit_pct))}
                              style={{ width: 96, accentColor: "#2563eb" }}
                            />
                            <strong>{Number(row.conversion_from_visit_pct).toFixed(1)}%</strong>
                          </div>
                        )}
                      </td>
                      <td>{Number(row.events).toLocaleString()}</td>
                      <td>{row.origins.map((origin) => origin === "marketing" ? "Marketing site" : "Cadivor app").join(" + ") || "Unknown"}</td>
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
