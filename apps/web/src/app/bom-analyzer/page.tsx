"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BomWorkflowStepper } from "@/components/BomWorkflowStepper";
import { Icon } from "@/components/Icons";
import { Shell } from "@/components/Shell";
import { PageHeader, SecondaryLink } from "@/components/PageHeader";
import {
  listDecisionRecords,
  listReports,
  validateBom,
  type AnalyzeSummary,
  type BomValidationPreview,
} from "@/lib/api";
import {
  clearFinishedAnalyzeJob,
  fileIdentityKey,
  getActiveAnalyzeJob,
  loadDraftFile,
  markReviewProgress,
  readDraftMeta,
  readReviewProgress,
  saveDraftFile,
  startAnalyzeJob,
  subscribeAnalyzeJob,
  writeDraftMeta,
  type BomDraftMeta,
  type BomReviewProgress,
} from "@/lib/bomDraft";
import { buildWorkflowGuide } from "@/lib/bomWorkflow";
import { PAGE_META } from "@/lib/routes";
import { rememberAnalysis, useRequireSession } from "@/lib/session";

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
  const session = useRequireSession();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [recentReports, setRecentReports] = useState<Array<Record<string, unknown>>>([]);
  const [reportsBusy, setReportsBusy] = useState(true);
  const [reportsError, setReportsError] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [projectName, setProjectName] = useState("");
  const [bomName, setBomName] = useState("");
  const [revision, setRevision] = useState("A");
  const [validating, setValidating] = useState(false);
  const [validation, setValidation] = useState<BomValidationPreview | null>(null);
  const [validationError, setValidationError] = useState("");
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState("");
  const [oneTimeReportRequired, setOneTimeReportRequired] = useState(false);
  const [summary, setSummary] = useState<AnalyzeSummary | null>(null);
  const [analysisId, setAnalysisId] = useState<string | null>(null);
  const [review, setReview] = useState<BomReviewProgress | null>(null);
  const [hasDecisionRecord, setHasDecisionRecord] = useState(false);
  const [draftReady, setDraftReady] = useState(false);
  const [backgroundNote, setBackgroundNote] = useState("");
  const [draftPersistNotice, setDraftPersistNotice] = useState("");
  const [validatedFileKey, setValidatedFileKey] = useState("");
  const validationRequestIdRef = useRef(0);
  const selectedFileKeyRef = useRef("");

  const persistMeta = useCallback(
    (patch: Partial<BomDraftMeta>) => {
      if (!session) return;
      const current = readDraftMeta(session);
      const next: BomDraftMeta = {
        ...current,
        projectName,
        bomName,
        revision,
        fileName: file?.name || current.fileName,
        fileSize: file?.size || current.fileSize,
        fileType: file?.type || current.fileType,
        fileKey: file ? fileIdentityKey(file) : current.fileKey,
        validation,
        validationError,
        analysisId,
        summary,
        analyzeError,
        oneTimeReportRequired,
        ...patch,
      };
      writeDraftMeta(next, session);
    },
    [
      session,
      projectName,
      bomName,
      revision,
      file,
      validation,
      validationError,
      analysisId,
      summary,
      analyzeError,
      oneTimeReportRequired,
    ],
  );

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

  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    (async () => {
      const meta = readDraftMeta(session);
      setProjectName(meta.projectName || "");
      setBomName(meta.bomName || "");
      setRevision(meta.revision || "A");
      setValidation(meta.validation);
      setValidationError(meta.validationError || "");
      setValidatedFileKey(meta.fileKey || "");
      selectedFileKeyRef.current = meta.fileKey || "";
      setAnalyzeError(meta.analyzeError || "");
      setOneTimeReportRequired(Boolean(meta.oneTimeReportRequired));
      setSummary(meta.summary);
      setAnalysisId(meta.analysisId);
      if (meta.analysisId) {
        setReview(readReviewProgress(meta.analysisId, session));
      }
      const restored = await loadDraftFile(session);
      if (cancelled) return;
      if (restored) {
        setFile(restored);
        const key = fileIdentityKey(restored);
        selectedFileKeyRef.current = key;
        if (meta.fileKey && meta.fileKey !== key) {
          setValidation(null);
          setValidatedFileKey("");
        } else if (meta.validation && meta.fileKey === key) {
          setValidatedFileKey(key);
        }
      }
      const job = getActiveAnalyzeJob(session);
      if (job?.status === "running") {
        setAnalyzing(true);
        setBackgroundNote(
          "Analysis continues in this browser session while you use other pages. Return here to see status.",
        );
      } else if (job?.status === "succeeded" && job.result) {
        setSummary(job.result);
        setAnalysisId(job.result.analysis_id);
        setAnalyzing(false);
        rememberAnalysis({ ...job.result, filename: job.fileName }, session);
        persistMeta({
          summary: job.result,
          analysisId: job.result.analysis_id,
          analyzeError: "",
          oneTimeReportRequired: false,
        });
        clearFinishedAnalyzeJob(session);
      } else if (job?.status === "failed") {
        setAnalyzeError(job.error || "Analyze failed");
        setOneTimeReportRequired(Boolean(job.oneTimeReportRequired));
        setAnalyzing(false);
        clearFinishedAnalyzeJob(session);
      }
      setDraftReady(true);
    })();
    return () => {
      cancelled = true;
    };
    // Restore once per session identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  useEffect(() => {
    if (!session) return;
    return subscribeAnalyzeJob((job) => {
      if (!job) return;
      if (job.ownerKey && job.ownerKey !== (session.user_id || session.email?.trim().toLowerCase() || "anonymous")) {
        return;
      }
      if (job.status === "running") {
        setAnalyzing(true);
        setAnalyzeError("");
        setBackgroundNote(
          "Analysis continues in this browser session while you use other pages. Return here to see status.",
        );
        return;
      }
      if (job.status === "succeeded" && job.result) {
        setAnalyzing(false);
        setSummary(job.result);
        setAnalysisId(job.result.analysis_id);
        setAnalyzeError("");
        setOneTimeReportRequired(false);
        rememberAnalysis({ ...job.result, filename: job.fileName }, session);
        writeDraftMeta(
          {
            ...readDraftMeta(session),
            summary: job.result,
            analysisId: job.result.analysis_id,
            analyzeError: "",
            oneTimeReportRequired: false,
          },
          session,
        );
        clearFinishedAnalyzeJob(session);
        return;
      }
      if (job.status === "failed") {
        setAnalyzing(false);
        setAnalyzeError(job.error || "Analyze failed");
        setOneTimeReportRequired(Boolean(job.oneTimeReportRequired));
        writeDraftMeta(
          {
            ...readDraftMeta(session),
            analyzeError: job.error || "Analyze failed",
            oneTimeReportRequired: Boolean(job.oneTimeReportRequired),
          },
          session,
        );
        clearFinishedAnalyzeJob(session);
      }
    }, session);
  }, [session]);

  useEffect(() => {
    if (!session || !analysisId) return;
    listDecisionRecords(session.access_token, analysisId)
      .then(({ records }) => {
        const found = (records || []).length > 0;
        setHasDecisionRecord(found);
        if (found) {
          setReview(
            markReviewProgress(
              analysisId,
              { decisionRecordedAt: new Date().toISOString() },
              session,
            ),
          );
        }
      })
      .catch(() => setHasDecisionRecord(false));
  }, [session, analysisId]);

  useEffect(() => {
    if (!session || !draftReady) return;
    persistMeta({});
  }, [
    session,
    draftReady,
    projectName,
    bomName,
    revision,
    file,
    validation,
    validationError,
    analysisId,
    summary,
    analyzeError,
    oneTimeReportRequired,
    persistMeta,
  ]);

  const runValidation = useCallback(
    async (nextFile: File, requestId: number, fileKey: string) => {
      if (!session) return;
      try {
        const preview = await validateBom(nextFile, session.access_token);
        if (requestId !== validationRequestIdRef.current) return;
        if (selectedFileKeyRef.current !== fileKey) return;
        setValidation(preview);
        setValidatedFileKey(fileKey);
        if (!preview.can_analyze) {
          setValidationError(
            preview.errors[0] || "Required validation did not pass. Analysis stays disabled.",
          );
        } else {
          setValidationError("");
        }
      } catch (err) {
        if (requestId !== validationRequestIdRef.current) return;
        if (selectedFileKeyRef.current !== fileKey) return;
        setValidation(null);
        setValidatedFileKey("");
        setValidationError(err instanceof Error ? err.message : "Validation failed");
      } finally {
        if (requestId === validationRequestIdRef.current) {
          setValidating(false);
        }
      }
    },
    [session],
  );

  async function onFileChosen(next: File | null) {
    if (!session) return;
    // Synchronously clear previous validation before any await.
    const requestId = ++validationRequestIdRef.current;
    const nextKey = next ? fileIdentityKey(next) : "";
    selectedFileKeyRef.current = nextKey;
    setFile(next);
    setValidation(null);
    setValidationError("");
    setValidatedFileKey("");
    setDraftPersistNotice("");
    setSummary(null);
    setAnalysisId(null);
    setReview(null);
    setHasDecisionRecord(false);
    setAnalyzeError("");
    setOneTimeReportRequired(false);
    setBackgroundNote("");
    setValidating(Boolean(next));
    if (!next) {
      setValidating(false);
      return;
    }
    if (next.size > 10 * 1024 * 1024) {
      setValidating(false);
      setValidationError("BOM file must be 10 MB or smaller.");
      return;
    }
    if (!bomName.trim()) {
      setBomName(next.name.replace(/\.(csv|xlsx)$/i, ""));
    }
    try {
      await saveDraftFile(next, session);
    } catch (err) {
      if (requestId !== validationRequestIdRef.current) return;
      setDraftPersistNotice(
        err instanceof Error
          ? `Draft could not be saved for later resume (${err.message}). Validation continues with the file still in memory.`
          : "Draft could not be saved for later resume. Validation continues with the file still in memory.",
      );
    }
    if (requestId !== validationRequestIdRef.current) return;
    await runValidation(next, requestId, nextKey);
  }

  function onAnalyze() {
    if (!session || !file || analyzing) return;
    const matches =
      Boolean(validation?.can_analyze) &&
      validatedFileKey === fileIdentityKey(file) &&
      !validating;
    if (!matches) return;
    setAnalyzeError("");
    setOneTimeReportRequired(false);
    setSummary(null);
    setAnalysisId(null);
    setBackgroundNote(
      "Analysis continues in this browser session while you use other pages. Return here to see status for your account.",
    );
    startAnalyzeJob(
      file,
      session.access_token,
      {
        projectName: projectName.trim() || undefined,
        bomName: bomName.trim() || file.name.replace(/\.(csv|xlsx)$/i, ""),
        revision: revision.trim() || "A",
      },
      session,
    );
    setAnalyzing(true);
  }

  const validationMatchesFile = Boolean(
    file &&
      validation &&
      validatedFileKey &&
      validatedFileKey === fileIdentityKey(file),
  );

  const guide = useMemo(
    () =>
      buildWorkflowGuide({
        hasFile: Boolean(file),
        validating,
        validation,
        validationError,
        validationMatchesFile,
        analyzing,
        analyzeError,
        summary,
        analysisId,
        review,
        hasDecisionRecord,
        monitoringAvailable: false,
      }),
    [
      file,
      validating,
      validation,
      validationError,
      validationMatchesFile,
      analyzing,
      analyzeError,
      summary,
      analysisId,
      review,
      hasDecisionRecord,
    ],
  );

  if (!session) return null;

  const visibleReports = recentReports
    .filter((row) => row.id || row.analysis_id)
    .slice(0, 3);
  const primary = guide.primaryCta;
  const canAnalyze = Boolean(
    file &&
      validationMatchesFile &&
      validation?.can_analyze &&
      !analyzing &&
      !validating,
  );

  function handlePrimary() {
    if (primary.disabled) return;
    if (primary.action === "choose-file") {
      fileInputRef.current?.click();
      return;
    }
    if (primary.action === "analyze" || primary.action === "retry-analyze") {
      onAnalyze();
    }
  }

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.bom}
        actions={
          <>
            <Link className="cv-button" href="/single-bom-report" target="_blank" rel="noreferrer">
              One-time report
            </Link>
            <SecondaryLink href="/reports">Saved analyses</SecondaryLink>
          </>
        }
      />

      <p className="cv-bom-guidance-note" role="note">
        This workflow guides analysis and review. Sidebar navigation and other tools stay available — leave anytime and resume this draft later.
      </p>

      <div className="cv-bom-workspace-grid">
        <section className="cv-card pad cv-bom-create-card">
          <div className="cv-bom-card-heading">
            <div>
              <h2 className="cv-card-title">Create a BOM analysis</h2>
              <p className="cv-card-subtitle">
                Add project details, upload the file, then review validation before analysis.
              </p>
            </div>
            <span className="cv-bom-step">
              Stage {guide.stages.findIndex((s) => s.id === guide.currentStage) + 1} of{" "}
              {guide.stages.length}
            </span>
          </div>

          <BomWorkflowStepper guide={guide} analyzing={analyzing} />

          {backgroundNote && analyzing ? (
            <p className="cv-small-note cv-bom-background-note" role="status">
              {backgroundNote}
            </p>
          ) : null}
          {draftPersistNotice ? (
            <p className="cv-bom-validation-warnings" role="status">
              {draftPersistNotice}
            </p>
          ) : null}
          <p className="cv-bom-guidance-note" role="note" data-testid="synthetic-sample-label">
            Evidence and local demos may use clearly labeled synthetic sample BOM data. Production risk scoring is unchanged.
          </p>

          <div className="cv-bom-fields cv-bom-fields-grid">
            <label className="cv-field">
              <span>Project</span>
              <input
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                placeholder="e.g. Motor controller"
                disabled={analyzing}
              />
            </label>
            <label className="cv-field">
              <span>BOM name</span>
              <input
                value={bomName}
                onChange={(e) => setBomName(e.target.value)}
                placeholder="Defaults to filename"
                disabled={analyzing}
              />
            </label>
            <label className="cv-field">
              <span>Revision</span>
              <input
                value={revision}
                onChange={(e) => setRevision(e.target.value)}
                placeholder="e.g. A"
                disabled={analyzing}
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
                ref={fileInputRef}
                type="file"
                accept=".csv,.xlsx"
                disabled={analyzing}
                onChange={(e) => void onFileChosen(e.target.files?.[0] || null)}
              />
              <small>{file ? file.name : "CSV or XLSX · up to 10 MB"}</small>
            </label>
          </div>

          {file ? (
            <section className="cv-bom-validation" aria-live="polite">
              <div className="cv-bom-validation-heading">
                <h3 className="cv-card-title">Validation preview</h3>
                <p className="cv-card-subtitle">
                  Uses the same parse path as analysis. Analysis stays disabled until required checks pass.
                  Row counts are source BOM rows before part aggregation.
                </p>
              </div>
              {validating ? (
                <p className="cv-bom-recent-state" role="status">
                  Validating columns and part counts…
                </p>
              ) : null}
              {validation ? (
                <>
                  <dl className="cv-bom-validation-stats">
                    <div>
                      <dt>Rows</dt>
                      <dd>{validation.row_count}</dd>
                    </div>
                    <div>
                      <dt>Unique parts</dt>
                      <dd>{validation.unique_part_count}</dd>
                    </div>
                    <div>
                      <dt>Columns detected</dt>
                      <dd>{validation.detected_columns.length}</dd>
                    </div>
                    <div>
                      <dt>Ready to analyze</dt>
                      <dd>{validation.can_analyze ? "Yes" : "No"}</dd>
                    </div>
                  </dl>
                  {validation.detected_columns.length ? (
                    <div className="cv-bom-column-list">
                      <p className="cv-small-note">Detected columns</p>
                      <ul>
                        {validation.detected_columns.map((col) => (
                          <li key={`${col.source}-${col.normalized}`}>
                            <strong>{col.source}</strong>
                            <span>→ {col.normalized || "unmapped"}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {validation.errors.length ? (
                    <div className="cv-error" role="alert">
                      <strong>Validation errors</strong>
                      <ul>
                        {validation.errors.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                      {validation.missing_required.length ? (
                        <p className="cv-small-note" style={{ marginTop: 8 }}>
                          Missing required: {validation.missing_required.join(", ")}
                        </p>
                      ) : null}
                    </div>
                  ) : null}
                  {validation.warnings.length ? (
                    <div className="cv-bom-validation-warnings" role="status">
                      <strong>Warnings</strong>
                      <ul>
                        {validation.warnings.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </>
              ) : null}
              {validationError && !validation?.errors.length ? (
                <div className="cv-error" role="alert">
                  {validationError}
                </div>
              ) : null}
            </section>
          ) : null}

          {analyzeError ? (
            <div className="cv-error" role="alert">
              {analyzeError}
              <p className="cv-small-note" style={{ marginTop: 8 }}>
                Your selected file and project details are still available. Fix the issue, then retry analysis.
              </p>
              {oneTimeReportRequired ? (
                <div style={{ marginTop: 10 }}>
                  <Link
                    className="cv-button primary"
                    href="/single-bom-report"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open one-time report purchase
                  </Link>
                  <p className="cv-small-note" style={{ marginTop: 8 }}>
                    Keep this BOM open. After checkout is confirmed, return here and run the analysis; your selected file will still be ready.
                  </p>
                </div>
              ) : null}
            </div>
          ) : null}

          {summary ? (
            <div className="cv-bom-success" role="status">
              <p className="cv-bom-summary">
                Saved {summary.project_name || summary.analysis_id}
                {summary.has_hierarchy
                  ? ` · assembly roll-up ${summary.top_rolled_risk || "n/a"}`
                  : ""}{" "}
                · {summary.total_parts} parts · health {summary.health_score ?? "—"}
              </p>
              <p className="cv-small-note">
                Received, Validating, and Analyzing are complete. Continue with Risks in the saved report.
              </p>
            </div>
          ) : null}

          <div className="cv-bom-analyze-actions cv-bom-primary-cta">
            {primary.href ? (
              <Link className="cv-button primary" href={primary.href}>
                {primary.label}
              </Link>
            ) : (
              <button
                type="button"
                className="cv-button primary"
                disabled={
                  primary.disabled ||
                  (primary.action === "analyze" || primary.action === "retry-analyze"
                    ? !canAnalyze
                    : false)
                }
                onClick={handlePrimary}
              >
                {primary.label}
              </button>
            )}
            {canAnalyze && primary.action !== "analyze" ? (
              <button
                type="button"
                className="cv-button"
                disabled={!canAnalyze}
                onClick={onAnalyze}
              >
                Analyze BOM
              </button>
            ) : null}
          </div>
        </section>

        <aside className="cv-bom-side-cards" aria-label="Analysis guidance and recent activity">
          <section className="cv-card pad cv-bom-side-card">
            <h2 className="cv-card-title">Before you analyze</h2>
            <p className="cv-card-subtitle">
              Validation preview prevents avoidable report errors. Only Analyze is gated.
            </p>
            <ul className="cv-bom-checklist">
              <li>
                <span className="cv-bom-check-icon"><Icon name="check" /></span>
                <span><strong>Confirm required columns</strong><small>MPN is required; quantity and manufacturer improve matching.</small></span>
              </li>
              <li>
                <span className="cv-bom-check-icon"><Icon name="shield" /></span>
                <span><strong>Review evidence coverage</strong><small>Check which records use sample evidence in the saved report.</small></span>
              </li>
              <li>
                <span className="cv-bom-check-icon"><Icon name="report" /></span>
                <span><strong>Resume from Recent analyses</strong><small>Saved reports keep Risks → Evidence → Decision → Monitor available.</small></span>
              </li>
            </ul>
          </section>

          <section className="cv-card pad cv-bom-side-card cv-bom-recent-card">
            <div className="cv-bom-recent-heading">
              <div>
                <h2 className="cv-card-title">Recent analyses</h2>
                <p className="cv-card-subtitle">Resume a saved analysis at Risks or later.</p>
              </div>
              <Link href="/reports" className="cv-bom-view-all">View all</Link>
            </div>

            {reportsBusy ? (
              <p className="cv-bom-recent-state" role="status">Loading saved analyses…</p>
            ) : reportsError ? (
              <p className="cv-bom-recent-state" role="alert">
                Recent analyses could not load. <Link href="/reports">Open Saved analyses</Link>.
              </p>
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
                      <Link
                        href={`/reports/${encodeURIComponent(id)}`}
                        className="cv-bom-recent-link"
                        onClick={() => {
                          markReviewProgress(
                            id,
                            { risksOpenedAt: new Date().toISOString() },
                            session,
                          );
                        }}
                      >
                        <span className="cv-bom-recent-copy">
                          <strong>{title}{revisionLabel}</strong>
                          <small>{partsLabel} · updated {dateLabel}</small>
                        </span>
                        <span className="cv-button small">Resume</span>
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
