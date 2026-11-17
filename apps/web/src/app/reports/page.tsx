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
      setManagementNotice(`BOM moved to ${String(target?.name || "the selected project")}; its report history is preserved.`);
    } catch (err) {
      setManagementError(err instanceof Error ? err.message : "BOM could not be moved to that project.");
    } finally {
      setManagementBusy("");
    }
  }

  async function onDeleteBom(bom: Record<string, unknown>) {
    if (!session) return;
    const bomId = String(bom.id || "");
    const bomName = String(bom.name || "this BOM");
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
        <section className="cv-card pad" style={{ marginBottom: 18 }} data-testid="saved-bom-management">
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
            const projectName = String(project.name || "Project");
            const boms = (project.boms || []) as Array<Record<string, unknown>>;
            if (!boms.length) return null;
            return (
              <div key={projectId} style={{ marginTop: 18 }} data-testid={`saved-project-${projectId}`}>
                <div className="cv-form-grid" style={{ gridTemplateColumns: "minmax(220px, 1fr) auto", alignItems: "end" }}>
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
                    className="cv-button small"
                    disabled={managementBusy !== "" || !String(projectDrafts[projectId] ?? projectName).trim()}
                    onClick={() => void onRenameProject(projectId)}
                  >
                    {managementBusy === projectId ? "Saving…" : "Save project name"}
                  </button>
                </div>
                <div className="cv-table-wrap" style={{ marginTop: 10 }}>
                  <table className="cv-table">
                    <thead>
                      <tr>
                        <th>BOM name</th>
                        <th>Saved revisions</th>
                        <th>Latest analysis</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {boms.map((bom) => {
                        const bomId = String(bom.id || "");
                        const bomName = String(bom.name || "Saved BOM");
                        const bomReports = reports.filter((report) => String(report.bom_id || "") === bomId);
                        const revisions = [...new Set(bomReports.map((report) => String(report.revision || "").trim()).filter(Boolean))];
                        const latest = (bom.latest_analysis || {}) as Record<string, unknown>;
                        const latestId = String(bom.latest_analysis_id || latest.id || "");
                        return (
                          <tr key={bomId}>
                            <td>
                              <input
                                value={bomDrafts[bomId] ?? bomName}
                                onChange={(event) => setBomDrafts((current) => ({ ...current, [bomId]: event.target.value }))}
                                maxLength={160}
                                aria-label={`BOM name for ${bomName}`}
                              />
                            </td>
                            <td>{revisions.length ? revisions.join(", ") : "—"}</td>
                            <td>
                              {latestId ? (
                                <Link href={`/reports/${encodeURIComponent(latestId)}`}>
                                  Open {String(latest.revision || "latest")}
                                </Link>
                              ) : "No saved analysis"}
                            </td>
                            <td>
                              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                                <button
                                  type="button"
                                  className="cv-button small"
                                  disabled={managementBusy !== "" || !String(bomDrafts[bomId] ?? bomName).trim()}
                                  onClick={() => void onRenameBom(bomId)}
                                >
                                  {managementBusy === bomId ? "Saving…" : "Save name"}
                                </button>
                                {latestId ? (
                                  <Link className="cv-button small secondary" href={`/reports/${encodeURIComponent(latestId)}`}>
                                    Edit BOM
                                  </Link>
                                ) : null}
                                <label className="cv-field" style={{ minWidth: 160, margin: 0 }}>
                                  <span className="cv-visually-hidden">Move {bomName} to project</span>
                                  <select
                                    aria-label={`Move ${bomName} to project`}
                                    value={bomProjectDrafts[bomId] ?? projectId}
                                    onChange={(event) => setBomProjectDrafts((current) => ({ ...current, [bomId]: event.target.value }))}
                                  >
                                    {projects.map((option) => (
                                      <option key={String(option.id)} value={String(option.id)}>
                                        {String(option.name || "Project")}
                                      </option>
                                    ))}
                                  </select>
                                </label>
                                <button
                                  type="button"
                                  className="cv-button small secondary"
                                  disabled={managementBusy !== "" || (bomProjectDrafts[bomId] ?? projectId) === projectId}
                                  onClick={() => void onMoveBom(bomId, projectId)}
                                >
                                  {managementBusy === bomId ? "Saving…" : "Move"}
                                </button>
                                <button
                                  type="button"
                                  className="cv-button small"
                                  style={{ color: "#b42318", borderColor: "#f3b6b3" }}
                                  disabled={managementBusy !== ""}
                                  onClick={() => void onDeleteBom({
                                    ...bom,
                                    analysis_count: bomReports.length,
                                    revision_count: revisions.length,
                                  })}
                                >
                                  Delete BOM
                                </button>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
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
                {stressReport.filename || "Uploaded BOM"} ·{" "}
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
            <div className="cv-table-wrap">
              <table className="cv-table">
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
                    return (
                      <tr key={id}>
                        <td><strong>{String(row.filename || row.bom_name || id)}</strong></td>
                        <td>{row.health_score == null ? "Not scored" : `${String(row.health_score)}/100`}</td>
                        <td>{String(row.total_parts ?? "—")}</td>
                        <td>{String(row.high_risk_count ?? "—")}</td>
                        <td>{row.created_at ? new Date(String(row.created_at)).toLocaleDateString() : "—"}</td>
                        <td><Link className="cv-button small" href={`/reports/${encodeURIComponent(id)}`}>Open &amp; download</Link></td>
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
