"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { EmptyState } from "@/components/EmptyState";
import { EvidenceNotice, LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink } from "@/components/PageHeader";
import { Shell } from "@/components/Shell";
import {
  deleteBom,
  listProjects,
  listReports,
  moveBom,
  renameBom,
  renameProject,
} from "@/lib/api";
import {
  cacheVerifiedPublicBomReport,
  completePublicBomAudit,
  fetchVerifiedPublicBomReport,
  normalizeStressReportId,
  peekStressReportId,
  readCachedVerifiedPublicBomReport,
  verifiedReportExportHref,
  type PublicBomVerifiedReport,
} from "@/lib/publicBomStress";
import { PAGE_META } from "@/lib/routes";
import { userFacingLabel } from "@/lib/display";
import { useRequireSession } from "@/lib/session";

function projectNameDraftsFor(projects: Array<Record<string, unknown>>): Record<string, string> {
  const drafts: Record<string, string> = {};
  for (const project of projects) drafts[String(project.id || "")] = String(project.name || "");
  return drafts;
}

function bomNameDraftsFor(projects: Array<Record<string, unknown>>): Record<string, string> {
  const drafts: Record<string, string> = {};
  for (const project of projects) {
    const boms = (project.boms || []) as Array<Record<string, unknown>>;
    for (const bom of boms) drafts[String(bom.id || "")] = String(bom.name || "");
  }
  return drafts;
}

function reportRecordId(report: Record<string, unknown>): string {
  return String(report.analysis_id || report.id || "").trim();
}

function reportRevisionLabel(report: Record<string, unknown>): string {
  const revision = String(report.revision || "").trim();
  if (revision) return `Rev ${revision}`;
  const saved = report.created_at ? new Date(String(report.created_at)).toLocaleDateString() : "Saved report";
  return saved;
}

function reportSavedDate(report: Record<string, unknown>): string {
  if (!report.created_at) return "Date not recorded";
  const date = new Date(String(report.created_at));
  return Number.isNaN(date.getTime()) ? "Date not recorded" : date.toLocaleString();
}

function healthLabel(value: unknown): string {
  if (value === null || value === undefined || String(value).trim() === "") return "Not scored";
  const score = Number(value);
  return Number.isFinite(score) ? `${score}/100` : "Not scored";
}

function ReportsInner() {
  const session = useRequireSession();
  const search = useSearchParams();
  const stressHandoff =
    (search.get("public_bom_stress") || "").trim() === "1";
  const reportIdFromQuery = normalizeStressReportId(search.get("report_id"));

  const [reports, setReports] = useState<Array<Record<string, unknown>>>([]);
  const [projects, setProjects] = useState<Array<Record<string, unknown>>>([]);
  const [projectDrafts, setProjectDrafts] = useState<Record<string, string>>({});
  const [bomDrafts, setBomDrafts] = useState<Record<string, string>>({});
  const [bomProjectDrafts, setBomProjectDrafts] = useState<Record<string, string>>({});
  const [managementBusy, setManagementBusy] = useState("");
  const [managementError, setManagementError] = useState("");
  const [managementNotice, setManagementNotice] = useState("");
  const [gap, setGap] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const [stressReport, setStressReport] =
    useState<PublicBomVerifiedReport | null>(null);
  const [stressError, setStressError] = useState("");
  const [stressBusy, setStressBusy] = useState(false);
  const [completeBusy, setCompleteBusy] = useState(false);

  useEffect(() => {
    if (!session) return;
    setBusy(true);
    Promise.all([
      listReports(session.access_token),
      listProjects(session.access_token),
    ])
      .then(([reportPayload, projectPayload]) => {
        setReports(reportPayload.reports || []);
        setGap(reportPayload.gap || "");
        const nextProjects = projectPayload.projects || [];
        setProjects(nextProjects);
        setProjectDrafts(projectNameDraftsFor(nextProjects));
        setBomDrafts(bomNameDraftsFor(nextProjects));
        setBomProjectDrafts(Object.fromEntries(
          nextProjects.flatMap((project) =>
            ((project.boms || []) as Array<Record<string, unknown>>).map((bom) => [
              String(bom.id || ""),
              String(project.id || ""),
            ] as const),
          ),
        ));
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Saved BOMs could not load."))
      .finally(() => setBusy(false));
  }, [session]);

  async function reloadSavedBoms() {
    if (!session) return;
    const [reportPayload, projectPayload] = await Promise.all([
      listReports(session.access_token),
      listProjects(session.access_token),
    ]);
    setReports(reportPayload.reports || []);
    setGap(reportPayload.gap || "");
    const nextProjects = projectPayload.projects || [];
    setProjects(nextProjects);
    setProjectDrafts(projectNameDraftsFor(nextProjects));
    setBomDrafts(bomNameDraftsFor(nextProjects));
    setBomProjectDrafts(Object.fromEntries(
      nextProjects.flatMap((project) =>
        ((project.boms || []) as Array<Record<string, unknown>>).map((bom) => [
          String(bom.id || ""),
          String(project.id || ""),
        ] as const),
      ),
    ));
  }

  async function onRenameProject(projectId: string) {
    if (!session) return;
    const name = String(projectDrafts[projectId] || "").trim();
    if (!name) {
      setManagementError("Enter a project name before saving.");
      return;
    }
    setManagementBusy(projectId);
    setManagementError("");
    setManagementNotice("");
    try {
      await renameProject(session.access_token, projectId, name);
      await reloadSavedBoms();
      setManagementNotice("Project name updated.");
    } catch (err) {
      setManagementError(err instanceof Error ? err.message : "Project name could not be updated.");
    } finally {
      setManagementBusy("");
    }
  }

  async function onRenameBom(bomId: string) {
    if (!session) return;
    const name = String(bomDrafts[bomId] || "").trim();
    if (!name) {
      setManagementError("Enter a BOM name before saving.");
      return;
    }
    setManagementBusy(bomId);
    setManagementError("");
    setManagementNotice("");
    try {
      await renameBom(session.access_token, bomId, name);
      await reloadSavedBoms();
      setManagementNotice("BOM name updated for all saved revisions.");
    } catch (err) {
      setManagementError(err instanceof Error ? err.message : "BOM name could not be updated.");
    } finally {
      setManagementBusy("");
    }
  }

  async function onMoveBom(bomId: string, currentProjectId: string) {
    if (!session) return;
    const projectId = String(bomProjectDrafts[bomId] || "");
    if (!projectId || projectId === currentProjectId) return;
    setManagementBusy(bomId);
    setManagementError("");
    setManagementNotice("");
    try {
      await moveBom(session.access_token, bomId, projectId);
      await reloadSavedBoms();
      const target = projects.find((project) => String(project.id || "") === projectId);
      setManagementNotice(`BOM moved to ${userFacingLabel(target?.name, "the selected project")}; its report history is preserved.`);
    } catch (err) {
      setManagementError(err instanceof Error ? err.message : "BOM could not be moved to that project.");
    } finally {
      setManagementBusy("");
    }
  }

  async function onDeleteBom(bom: Record<string, unknown>) {
    if (!session) return;
    const bomId = String(bom.id || "");
    const bomName = userFacingLabel(bom.name, "this BOM");
    const revisions = Number(bom.revision_count || 0);
    const reportCount = Number(bom.analysis_count || (bom.latest_analysis_id ? 1 : 0));
    const confirmed = window.confirm(
      `Delete “${bomName}” and all ${reportCount} saved report${reportCount === 1 ? "" : "s"}, revisions, engineering decisions, quotes, and monitoring history? This cannot be undone.`,
    );
    if (!confirmed) return;
    setManagementBusy(bomId);
    setManagementError("");
    setManagementNotice("");
    try {
      const deleted = await deleteBom(session.access_token, bomId);
      await reloadSavedBoms();
      setManagementNotice(
        `Deleted ${bomName} and ${deleted.deleted_analysis_count} saved report${deleted.deleted_analysis_count === 1 ? "" : "s"}${revisions ? ` across ${revisions} revision${revisions === 1 ? "" : "s"}` : ""}.`,
      );
    } catch (err) {
      setManagementError(err instanceof Error ? err.message : "BOM could not be deleted.");
    } finally {
      setManagementBusy("");
    }
  }

  useEffect(() => {
    if (!session) return;
    const identity = session.user_id || session.email;
    // Prefer the handoff selector, then the last opened report id (reload).
    const selectedReportId = reportIdFromQuery || peekStressReportId();
    const cached = readCachedVerifiedPublicBomReport(
      identity,
      selectedReportId,
    );
    if (cached) setStressReport(cached);

    let cancelled = false;
    setStressBusy(true);
    setStressError("");
    setCompleteBusy(false);

    (async () => {
      try {
        let report = await fetchVerifiedPublicBomReport(
          session.access_token,
          selectedReportId,
        );
        const pending = (report.results || []).some(
          (row) => row.enrichment_pending,
        );
        if (!report.full_enriched || pending) {
          setCompleteBusy(true);
          report = await completePublicBomAudit(
            session.access_token,
            report.id || selectedReportId,
          );
        }
        if (cancelled) return;
        setStressReport(report);
        cacheVerifiedPublicBomReport(identity, report);
      } catch (err) {
        if (cancelled) return;
        if (!cached) setStressReport(null);
        if (stressHandoff || selectedReportId) {
          setStressError(
            err instanceof Error
              ? err.message
              : "Your verified public audit is not available yet.",
          );
        }
      } finally {
        if (!cancelled) {
          setStressBusy(false);
          setCompleteBusy(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [session, stressHandoff, reportIdFromQuery]);

  if (!session) return null;

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.reports}
        actions={<PrimaryLink href="/bom-analyzer">New BOM analysis</PrimaryLink>}
      />
      {<EvidenceNotice gap={gap} />}

      {!busy && projects.length ? (
        <section className="cv-card pad cv-saved-bom-management" style={{ marginBottom: 18 }} data-testid="saved-bom-management">
          <div className="cv-section-heading cv-section-heading--card">
            <div>
              <h2>Manage saved BOMs</h2>
              <p>Rename projects and BOMs, edit a BOM as a new revision, or delete a BOM and its saved history.</p>
            </div>
          </div>
          {managementError ? <div className="cv-error" role="alert">{managementError}</div> : null}
          {managementNotice ? <p className="cv-small-note" role="status">{managementNotice}</p> : null}
          {projects.map((project) => {
            const projectId = String(project.id || "");
            const projectName = userFacingLabel(project.name, "Project");
            const boms = (project.boms || []) as Array<Record<string, unknown>>;
            if (!boms.length) return null;
            return (
              <div key={projectId} className="cv-saved-project" data-testid={`saved-project-${projectId}`}>
                <div className="cv-saved-project-heading">
                  <label className="cv-field">
                    <span>Project name</span>
                    <input
                      value={projectDrafts[projectId] ?? projectName}
                      onChange={(event) => setProjectDrafts((current) => ({ ...current, [projectId]: event.target.value }))}
                      maxLength={120}
                      aria-label={`Project name for ${projectName}`}
                    />
                  </label>
                  <button
                    type="button"
                    className="cv-button secondary"
                    disabled={managementBusy !== "" || !String(projectDrafts[projectId] ?? projectName).trim()}
                    onClick={() => void onRenameProject(projectId)}
                  >
                    {managementBusy === projectId ? "Saving…" : "Save project name"}
                  </button>
                </div>
                <div className="cv-saved-bom-list">
                  {boms.map((bom) => {
                    const bomId = String(bom.id || "");
                    const bomName = userFacingLabel(bom.name, "Saved BOM");
                    const bomReports = reports
                      .filter((report) => String(report.bom_id || "") === bomId && reportRecordId(report))
                      .sort((a, b) => Date.parse(String(b.created_at || "")) - Date.parse(String(a.created_at || "")));
                    const latest = (bom.latest_analysis || {}) as Record<string, unknown>;
                    const latestId = String(bom.latest_analysis_id || latest.id || "");
                    const revisionCount = new Set(bomReports.map((report) => reportRevisionLabel(report))).size;
                    return (
                      <article key={bomId} className="cv-saved-bom-card" data-testid={`saved-bom-${bomId}`}>
                        <div className="cv-saved-bom-heading">
                          <div>
                            <span className="cv-eyebrow">Saved BOM</span>
                            <h3>{bomName}</h3>
                          </div>
                          <span className="cv-saved-bom-count">{revisionCount} revision{revisionCount === 1 ? "" : "s"}</span>
                        </div>
                        <div className="cv-saved-bom-name-row">
                          <label className="cv-field">
                            <span>BOM name</span>
                            <input
                              value={bomDrafts[bomId] ?? bomName}
                              onChange={(event) => setBomDrafts((current) => ({ ...current, [bomId]: event.target.value }))}
                              maxLength={160}
                              aria-label={`BOM name for ${bomName}`}
                            />
                          </label>
                          <button
                            type="button"
                            className="cv-button secondary"
                            disabled={managementBusy !== "" || !String(bomDrafts[bomId] ?? bomName).trim()}
                            onClick={() => void onRenameBom(bomId)}
                          >
                            {managementBusy === bomId ? "Saving…" : "Save BOM name"}
                          </button>
                          {latestId ? (
                            <Link className="cv-button primary" href={`/reports/${encodeURIComponent(latestId)}`}>
                              Open to edit BOM
                            </Link>
                          ) : null}
                        </div>
                        <div className="cv-saved-revisions">
                          <div className="cv-saved-revisions-title">
                            <strong>Open a saved revision</strong>
                            <span>Each link opens that exact report snapshot.</span>
                          </div>
                          {bomReports.length ? (
                            <div className="cv-revision-links" aria-label={`Saved revisions for ${bomName}`}>
                              {bomReports.map((savedReport) => {
                                const savedId = reportRecordId(savedReport);
                                const revisionLabel = reportRevisionLabel(savedReport);
                                return (
                                  <Link
                                    key={savedId}
                                    className="cv-revision-link"
                                    href={`/reports/${encodeURIComponent(savedId)}`}
                                    aria-label={`Open ${revisionLabel} of ${bomName}, saved ${reportSavedDate(savedReport)}`}
                                  >
                                    <strong>{revisionLabel}</strong>
                                    <span>{reportSavedDate(savedReport)}</span>
                                  </Link>
                                );
                              })}
                            </div>
                          ) : (
                            <p className="cv-small-note">No saved report revisions are available yet.</p>
                          )}
                        </div>
                        <div className="cv-saved-bom-actions">
                          <label className="cv-field">
                            <span>Move to project</span>
                            <select
                              aria-label={`Move ${bomName} to project`}
                              value={bomProjectDrafts[bomId] ?? projectId}
                              onChange={(event) => setBomProjectDrafts((current) => ({ ...current, [bomId]: event.target.value }))}
                            >
                              {projects.map((option) => (
                                <option key={String(option.id)} value={String(option.id)}>
                                  {userFacingLabel(option.name, "Project")}
                                </option>
                              ))}
                            </select>
                          </label>
                          <button
                            type="button"
                            className="cv-button secondary"
                            disabled={managementBusy !== "" || (bomProjectDrafts[bomId] ?? projectId) === projectId}
                            onClick={() => void onMoveBom(bomId, projectId)}
                          >
                            {managementBusy === bomId ? "Saving…" : "Move BOM"}
                          </button>
                          <button
                            type="button"
                            className="cv-button cv-button-danger"
                            disabled={managementBusy !== ""}
                            onClick={() => void onDeleteBom({
                              ...bom,
                              analysis_count: bomReports.length,
                              revision_count: revisionCount,
                            })}
                          >
                            Delete BOM
                          </button>
                        </div>
                      </article>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </section>
      ) : null}

      {stressHandoff || stressReport || stressBusy || stressError ? (
        <section
          className="cv-card pad"
          data-testid="public-bom-verified-report"
          style={{ marginBottom: 18 }}
        >
          <div className="cv-section-heading cv-section-heading--card">
            <div>
              <h2>Free BOM audit</h2>
              <p>
                Complete supplier-backed results unlocked after email
                verification. This audit stays available here after reload.
              </p>
            </div>
          </div>
          {stressBusy && !stressReport ? (
            <LoadingCard
              label={
                completeBusy
                  ? "Finishing supplier lookups for remaining components…"
                  : "Loading your verified public audit…"
              }
            />
          ) : null}
          {stressError && !stressReport ? (
            <div className="cv-error" role="alert">
              {stressError}
            </div>
          ) : null}
          {stressReport ? (
            <>
              <p className="cv-small-note" style={{ marginTop: 0 }}>
                {userFacingLabel(stressReport.filename, "Uploaded BOM")} ·{" "}
                {stressReport.row_count ?? stressReport.results?.length ?? 0}{" "}
                components
                {stressReport.created_at
                  ? ` · ${new Date(stressReport.created_at).toLocaleString()}`
                  : ""}
                {stressReport.full_enriched ? " · Complete" : ""}
              </p>
              {completeBusy ? (
                <LoadingCard label="Finishing supplier lookups for remaining components…" />
              ) : null}
              <div className="cv-table-wrap">
                <table className="cv-table" data-testid="public-bom-verified-table">
                  <thead>
                    <tr>
                      <th>MPN</th>
                      <th>Manufacturer</th>
                      <th>Qty</th>
                      <th>Lifecycle</th>
                      <th>Reported stock</th>
                      <th>Lead time (weeks)</th>
                      <th>Matching suppliers</th>
                      <th>Risk</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(stressReport.results || []).map((row, index) => (
                      <tr key={`${row.mpn || "row"}-${index}`}>
                        <td>{row.mpn || ""}</td>
                        <td>{row.manufacturer || "Not matched"}</td>
                        <td>
                          {row.quantity == null ? "—" : String(row.quantity)}
                        </td>
                        <td>{row.lifecycle || "Unverified"}</td>
                        <td>{row.stock == null ? "—" : String(row.stock)}</td>
                        <td>
                          {row.lead_time_weeks == null
                            ? "—"
                            : String(row.lead_time_weeks)}
                        </td>
                        <td>
                          {row.supplier_count == null
                            ? "—"
                            : String(row.supplier_count)}
                        </td>
                        <td>{row.risk || "Needs verification"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {stressReport.full_enriched !== false ? (
                <div
                  className="cv-actions"
                  style={{ marginTop: 12, display: "flex", gap: 8 }}
                >
                  <a
                    className="cv-button small"
                    data-testid="public-bom-download-csv"
                    href={verifiedReportExportHref(stressReport.id, "csv")}
                    onClick={async (event) => {
                      event.preventDefault();
                      if (!session) return;
                      const res = await fetch(
                        verifiedReportExportHref(stressReport.id, "csv"),
                        {
                          headers: {
                            Authorization: `Bearer ${session.access_token}`,
                          },
                        },
                      );
                      if (!res.ok) return;
                      const blob = await res.blob();
                      const url = URL.createObjectURL(blob);
                      const link = document.createElement("a");
                      link.href = url;
                      link.download = "bom-audit-complete.csv";
                      link.click();
                      URL.revokeObjectURL(url);
                    }}
                  >
                    Download CSV
                  </a>
                  <a
                    className="cv-button small"
                    data-testid="public-bom-download-xlsx"
                    href={verifiedReportExportHref(stressReport.id, "xlsx")}
                    onClick={async (event) => {
                      event.preventDefault();
                      if (!session) return;
                      const res = await fetch(
                        verifiedReportExportHref(stressReport.id, "xlsx"),
                        {
                          headers: {
                            Authorization: `Bearer ${session.access_token}`,
                          },
                        },
                      );
                      if (!res.ok) return;
                      const blob = await res.blob();
                      const url = URL.createObjectURL(blob);
                      const link = document.createElement("a");
                      link.href = url;
                      link.download = "bom-audit-complete.xlsx";
                      link.click();
                      URL.revokeObjectURL(url);
                    }}
                  >
                    Download Excel
                  </a>
                </div>
              ) : null}
            </>
          ) : null}
        </section>
      ) : null}

      {busy ? <LoadingCard label="Loading saved reports…" /> : null}
      {error ? <div className="cv-error" role="alert">Reports could not load. {error}</div> : null}
      {!busy && !error ? (
        reports.length ? (
          <section className="cv-card pad">
            <div className="cv-section-heading cv-section-heading--card">
              <div>
                <h2>Saved analyses</h2>
                <p>Open a report to review its evidence and download PDF, Excel, or CSV copies.</p>
              </div>
              <span className="cv-data-note">{reports.length} report{reports.length === 1 ? "" : "s"}</span>
            </div>
            <div className="cv-table-wrap cv-saved-reports-table-wrap">
              <table className="cv-table cv-saved-reports-table">
                <thead>
                  <tr>
                    <th>Analysis</th>
                    <th>Health</th>
                    <th>Components</th>
                    <th>High risk</th>
                    <th>Saved</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {reports.map((row) => {
                    const id = String(row.id || row.analysis_id || "");
                    const score = healthLabel(row.health_score);
                    const scored = score !== "Not scored";
                    const revision = row.revision ? `Rev ${String(row.revision)}` : "Saved analysis";
                    return (
                      <tr key={id}>
                        <td>
                          <strong>{userFacingLabel(row.bom_name || row.filename || row.project_name, "Saved analysis")}</strong>
                          <small className="cv-saved-report-revision">{revision}{row.project_label ? ` · ${userFacingLabel(row.project_label, "Project")}` : ""}</small>
                        </td>
                        <td>
                          <div className="cv-report-health-cell">
                            <strong>{score}</strong>
                            <span className={`cv-badge ${scored ? "green" : "amber"}`}>
                              {userFacingLabel(row.health_status, scored ? "Scored" : "Needs verification")}
                            </span>
                            {!scored ? (
                              <small title={String(row.summary_message || "A complete evidence check is required for every BOM line before Cadivor calculates the overall score.")}>
                                {Number(row.needs_verification_count) > 0
                                  ? `${String(row.needs_verification_count)} component${Number(row.needs_verification_count) === 1 ? "" : "s"} need evidence verification`
                                  : "Score withheld until evidence is complete"}
                              </small>
                            ) : null}
                          </div>
                        </td>
                        <td>{String(row.total_parts ?? "—")}</td>
                        <td>{String(row.high_risk_count ?? "—")}</td>
                        <td>{row.created_at ? new Date(String(row.created_at)).toLocaleDateString() : "—"}</td>
                        <td><Link className="cv-button secondary" href={`/reports/${encodeURIComponent(id)}`}>Open report</Link></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        ) : (
          !stressReport ? (
            <EmptyState
              icon="report"
              title="No saved reports yet"
              body="Completed BOM analyses are saved to this workspace and appear here for you to reopen."
              action={<PrimaryLink href="/bom-analyzer">Start a BOM analysis</PrimaryLink>}
            />
          ) : null
        )
      ) : null}
    </Shell>
  );
}

export default function ReportsIndexPage() {
  return (
    <Suspense fallback={<div className="cv-card pad">Loading reports…</div>}>
      <ReportsInner />
    </Suspense>
  );
}
