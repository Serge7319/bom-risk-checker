"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import { Shell } from "@/components/Shell";
import { fetchWorkspacePriorityQueue } from "@/lib/api";
import { cleanUserText, evidenceSourceLabel, userFacingLabel } from "@/lib/display";
import { PAGE_META } from "@/lib/routes";
import { useRequireSession } from "@/lib/session";

function prioritySeverityClass(value: unknown) {
  const level = String(value || "").toLowerCase();
  if (level.includes("critical")) return "critical";
  if (level.includes("high")) return "high";
  if (level.includes("medium")) return "medium";
  if (level.includes("low")) return "low";
  return "needs_verification";
}

export default function PriorityQueuePage() {
  const session = useRequireSession();
  const [items, setItems] = useState<Array<Record<string, unknown>>>([]);
  const [reportsTotal, setReportsTotal] = useState(0);
  const [reportsLoaded, setReportsLoaded] = useState(0);
  const [nextOffset, setNextOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [busy, setBusy] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    let active = true;
    setBusy(true);
    setError("");
    setItems([]);
    fetchWorkspacePriorityQueue(session.access_token)
      .then((page) => {
        if (!active) return;
        setItems(page.items || []);
        setReportsTotal(Number(page.reports_total || 0));
        setReportsLoaded(Number(page.reports_loaded || 0));
        setNextOffset(Number(page.next_offset || 0));
        setHasMore(page.has_more === true);
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : "Priority queue could not load.");
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => { active = false; };
  }, [session]);

  if (!session) return null;

  async function loadOlderAnalyses() {
    if (!session || !hasMore || loadingMore) return;
    setLoadingMore(true);
    setError("");
    try {
      const page = await fetchWorkspacePriorityQueue(session.access_token, nextOffset);
      setItems((current) => [...current, ...(page.items || [])]);
      setReportsTotal(Number(page.reports_total || 0));
      setReportsLoaded(Number(page.reports_loaded || 0));
      setNextOffset(Number(page.next_offset || nextOffset));
      setHasMore(page.has_more === true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "More priority findings could not load.");
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.priorityQueue}
        actions={
          <>
            <PrimaryLink href="/bom-analyzer">New BOM analysis</PrimaryLink>
            <SecondaryLink href="/reports">Saved reports</SecondaryLink>
          </>
        }
      />

      {busy ? <LoadingCard label="Loading priority findings from saved analyses…" /> : null}
      {error ? <div className="cv-error" role="alert">Priority findings could not load. {error}</div> : null}

      {!busy ? (
        <section className="cv-card pad">
          <div className="cv-section-heading cv-section-heading--card">
            <div>
              <h2>Current priority findings</h2>
              <p>
                High and medium risks appear before findings that need verification within each saved analysis. Newer analyses load first.
              </p>
            </div>
            <span className="cv-priority-count">
              {items.length} {items.length === 1 ? "finding" : "findings"} loaded
            </span>
          </div>

          {items.length ? (
            <div className="cv-table-wrap" style={{ marginTop: 12 }}>
              <table className="cv-table cv-priority-full-table">
                <thead>
                  <tr>
                    <th>Priority</th>
                    <th>Component</th>
                    <th>Finding</th>
                    <th>Project / BOM</th>
                    <th>Evidence</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item, index) => {
                    const level = String(item.risk_level || "Needs verification");
                    const analysisId = String(item.analysis_id || "");
                    const part = userFacingLabel(item.mpn, "Component");
                    const project = userFacingLabel(item.project_name, "Project");
                    const bom = userFacingLabel(item.bom_name || item.filename, "Saved BOM");
                    return (
                      <tr key={`${analysisId}-${part}-${index}`}>
                        <td>
                          <span className={`cv-priority-severity ${prioritySeverityClass(level)}`}>
                            {level}
                          </span>
                        </td>
                        <td><strong>{part}</strong></td>
                        <td className="cv-priority-full-finding">{cleanUserText(item.why || "Evidence needs review.")}</td>
                        <td>
                          <strong>{project}</strong>
                          <div className="cv-priority-full-meta">
                            {bom}
                            {item.revision ? ` · Rev ${cleanUserText(item.revision)}` : ""}
                            {item.bom_path ? ` · ${cleanUserText(item.bom_path)}` : ""}
                          </div>
                        </td>
                        <td>
                          <span className="cv-evidence-chip">
                            {evidenceSourceLabel(item.evidence_source)}
                          </span>
                        </td>
                        <td>
                          {analysisId ? (
                            <Link className="cv-table-open" href={`/reports/${encodeURIComponent(analysisId)}`}>
                              Review evidence
                            </Link>
                          ) : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              icon="risk"
              title={reportsTotal ? "No priority findings in the latest analyses" : "No saved analyses yet"}
              body={reportsTotal
                ? "Load older analyses to continue checking the workspace queue."
                : "Save a BOM analysis to see evidence-linked risks here."}
              action={!reportsTotal ? <PrimaryLink href="/bom-analyzer">Analyze a BOM</PrimaryLink> : undefined}
            />
          )}

          <div className="cv-priority-full-footer">
            <p className="cv-home-list-summary" aria-live="polite">
              Loaded findings from {reportsLoaded} of {reportsTotal} saved analyses.
            </p>
            {hasMore ? (
              <button className="cv-button" type="button" onClick={() => void loadOlderAnalyses()} disabled={loadingMore}>
                {loadingMore ? "Loading…" : "Load older analyses"}
              </button>
            ) : null}
          </div>
        </section>
      ) : null}
    </Shell>
  );
}
