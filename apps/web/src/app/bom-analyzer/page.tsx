"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Icon } from "@/components/Icons";
import { Shell } from "@/components/Shell";
import { PageHeader, SecondaryLink } from "@/components/PageHeader";
import { analyzeBom, listReports, type AnalyzeSummary } from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { rememberAnalysis, useRequireSession } from "@/lib/session";

const STAGES = [
  "Received",
  "Validating",
  "Analyzing",
  "Risks",
  "Evidence",
  "Decision",
  "Monitor",
] as const;

function formatReportDate(value: unknown): string {
  if (!value) return "recently";
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return "recently";
  const now = new Date();
  const isSameDay = (left: Date, right: Date) =>
    left.getFullYear() === right.getFullYear() &&
    left.getMonth() === right.getMonth() &&
    left.getDate() === right.getDate();
  if (isSameDay(date, now)) return "today";
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (isSameDay(date, yesterday)) return "yesterday";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function BomAnalyzerPage() {
  const router = useRouter();
  const session = useRequireSession();
  const [recentReports, setRecentReports] = useState<Array<Record<string, unknown>>>([]);
  const [reportsBusy, setReportsBusy] = useState(true);
  const [reportsError, setReportsError] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [projectName, setProjectName] = useState("");
  const [bomName, setBomName] = useState("");
  const [revision, setRevision] = useState("A");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [summary, setSummary] = useState<AnalyzeSummary | null>(null);

  useEffect(() => {
    if (!session) return;
    let active = true;
    listReports(session.access_token)
      .then((payload) => {
        if (active) setRecentReports(payload.reports || []);
      })
      .catch((err) => {
        if (active) {
          setReportsError(err instanceof Error ? err.message : "Reports could not load.");
        }
      })
      .finally(() => {
        if (active) setReportsBusy(false);
      });
    return () => {
      active = false;
    };
  }, [session]);

  async function onAnalyze() {
    if (!session || !file) return;
    setBusy(true);
    setError("");
    setSummary(null);
    try {
      const result = await analyzeBom(file, session.access_token, {
        projectName: projectName.trim() || undefined,
        bomName: bomName.trim() || file.name.replace(/\.(csv|xlsx)$/i, ""),
        revision: revision.trim() || "A",
      });
      rememberAnalysis({ ...result, filename: file.name }, session);
      setSummary(result);
      router.push(`/reports/${result.analysis_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analyze failed");
      setBusy(false);
    }
  }

  if (!session) return null;

  const activeStage = busy
    ? "Analyzing"
    : summary
      ? "Decision"
      : file
        ? "Validating"
        : "Received";
  const visibleReports = recentReports
    .filter((row) => row.id || row.analysis_id)
    .slice(0, 3);

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.bom}
        actions={
          <>
            <SecondaryLink href="/reports">Saved analyses</SecondaryLink>
          </>
        }
      />

      <div className="cv-bom-workspace-grid">
        <section className="cv-card pad cv-bom-create-card">
          <div className="cv-bom-card-heading">
            <div>
              <h2 className="cv-card-title">Create a BOM analysis</h2>
              <p className="cv-card-subtitle">
                Add project details, upload the file, then review validation before analysis.
              </p>
            </div>
            <span className="cv-bom-step">Step {STAGES.indexOf(activeStage) + 1} of {STAGES.length}</span>
          </div>

          <section className="cv-bom-progress-inline" aria-live="polite" aria-busy={busy}>
            <div className="cv-bom-stages">
              {STAGES.map((stage) => (
                <span
                  key={stage}
                  className={`cv-bom-stage${stage === activeStage ? " active" : ""}`}
                >
                  {stage}
                </span>
              ))}
            </div>
            <div className="cv-bom-progress" aria-hidden>
              <i style={{ width: busy ? "55%" : summary ? "85%" : file ? "28%" : "12%" }} />
            </div>
            {busy ? (
              <div className="cv-loading cv-bom-inline-message" role="status">
                Analyzing the BOM with available evidence and saving it to your workspace…
              </div>
            ) : null}
            {error ? <div className="cv-error" role="alert">{error}</div> : null}
            {summary ? (
              <p className="cv-small-note cv-bom-summary">
                Saved {summary.project_name || summary.analysis_id}
                {summary.has_hierarchy
                  ? ` · assembly roll-up ${summary.top_rolled_risk || "n/a"}`
                  : ""}{" "}
                · {summary.total_parts} parts · health {summary.health_score ?? "—"}
              </p>
            ) : null}
          </section>

          <div className="cv-bom-fields cv-bom-fields-grid">
            <label className="cv-field">
              <span>Project</span>
              <input
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                placeholder="e.g. Motor controller"
              />
            </label>
            <label className="cv-field">
              <span>BOM name</span>
              <input
                value={bomName}
                onChange={(e) => setBomName(e.target.value)}
                placeholder="Defaults to filename"
              />
            </label>
            <label className="cv-field">
              <span>Revision</span>
              <input
                value={revision}
                onChange={(e) => setRevision(e.target.value)}
                placeholder="e.g. A"
              />
            </label>
          </div>

          <div className="cv-upload-zone cv-bom-upload-zone cv-bom-dropzone">
            <div className="cv-bom-upload-icon" aria-hidden="true">
              <Icon name="upload" />
            </div>
            <h3>{file ? file.name : "New analysis"}</h3>
            <p>
              Upload a CSV or XLSX BOM. Add Parent MPN and Line Type columns when you want to roll component risk up to assemblies.
            </p>
            <label className="cv-bom-file-picker">
              <span>{file ? "Choose a different file" : "Choose file"}</span>
              <input
                type="file"
                accept=".csv,.xlsx"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
              />
              <small>{file ? file.name : "CSV or XLSX · up to 10 MB"}</small>
            </label>
            <div className="cv-bom-analyze-actions">
              <button
                type="button"
                className="cv-button primary"
                disabled={!file || busy}
                onClick={onAnalyze}
              >
                {busy ? "Analyzing…" : "Analyze BOM"}
              </button>
            </div>
          </div>
        </section>

        <aside className="cv-bom-side-cards" aria-label="Analysis guidance and recent activity">
          <section className="cv-card pad cv-bom-side-card">
            <h2 className="cv-card-title">Before you analyze</h2>
            <p className="cv-card-subtitle">
              A short validation preview prevents avoidable report errors.
            </p>
            <ul className="cv-bom-checklist">
              <li>
                <span className="cv-bom-check-icon"><Icon name="check" /></span>
                <span><strong>Confirm required columns</strong><small>Map the MPN, quantity, and hierarchy fields.</small></span>
              </li>
              <li>
                <span className="cv-bom-check-icon"><Icon name="shield" /></span>
                <span><strong>Review evidence coverage</strong><small>Check which records use sample evidence.</small></span>
              </li>
              <li>
                <span className="cv-bom-check-icon"><Icon name="report" /></span>
                <span><strong>Save a traceable report</strong><small>Return to this revision from Saved analyses.</small></span>
              </li>
            </ul>
          </section>

          <section className="cv-card pad cv-bom-side-card cv-bom-recent-card">
            <div className="cv-bom-recent-heading">
              <div>
                <h2 className="cv-card-title">Recent analyses</h2>
                <p className="cv-card-subtitle">Pick up where you left off.</p>
              </div>
              <Link href="/reports" className="cv-bom-view-all">View all</Link>
            </div>

            {reportsBusy ? (
              <p className="cv-bom-recent-state" role="status">Loading saved analyses…</p>
            ) : reportsError ? (
              <p className="cv-bom-recent-state" role="alert">Recent analyses could not load. <Link href="/reports">Open Saved analyses</Link>.</p>
            ) : visibleReports.length ? (
              <ul className="cv-bom-recent-list">
                {visibleReports.map((row) => {
                  const id = String(row.id || row.analysis_id || "");
                  const title = String(row.bom_name || row.filename || row.project_name || id || "BOM analysis");
                  const revisionLabel = row.revision ? ` · rev ${String(row.revision)}` : "";
                  const partsLabel = row.total_parts == null ? "Saved report" : `${String(row.total_parts)} parts`;
                  const dateLabel = formatReportDate(row.created_at);
                  return (
                    <li key={id}>
                      <Link href={`/reports/${encodeURIComponent(id)}`} className="cv-bom-recent-link">
                        <span className="cv-bom-recent-copy">
                          <strong>{title}{revisionLabel}</strong>
                          <small>{partsLabel} · updated {dateLabel}</small>
                        </span>
                        <span className="cv-button small">Open</span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="cv-bom-recent-state">
                No saved reports yet. Create an analysis, then return here to continue.
              </p>
            )}
          </section>
        </aside>
      </div>
    </Shell>
  );
}

