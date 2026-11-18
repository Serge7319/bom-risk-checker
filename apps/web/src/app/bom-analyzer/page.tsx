"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "@/components/Icons";
import { Shell } from "@/components/Shell";
import { PageHeader, SecondaryLink } from "@/components/PageHeader";
import { BomIntakeReview } from "@/components/BomIntakeReview";
import {
  DEFAULT_BOM_INTAKE_OPTIONS,
  listReports,
  validateBom,
  type AnalyzeSummary,
  type BomIntakeOptions,
  type BomValidationPreview,
} from "@/lib/api";
import {
  clearFinishedAnalyzeJob,
  fileIdentityKey,
  getActiveAnalyzeJob,
  identityKey,
  isInternalTestDraft,
  loadDraftFile,
  materializeBomFile,
  parseAnalyzeSummary,
  readDraftMeta,
  saveDraftFile,
  startAnalyzeJob,
  subscribeAnalyzeJob,
  writeDraftMeta,
  type BomDraftMeta,
} from "@/lib/bomDraft";
import { PAGE_META } from "@/lib/routes";
import { userFacingLabel } from "@/lib/display";
import { rememberAnalysis, useRequireSession } from "@/lib/session";
import { trackMarketingEventOnce } from "@/lib/marketingAnalytics";

function freshIntakeOptions(): BomIntakeOptions {
  return { ...DEFAULT_BOM_INTAKE_OPTIONS, rowCorrections: {} };
}

/** Stable comparison so key order never makes a no-op edit look like a change. */
function intakeSignature(options: BomIntakeOptions): string {
  const mapping = options.columnMapping
    ? Object.entries(options.columnMapping).sort(([a], [b]) => Number(a) - Number(b))
    : null;
  const corrections = Object.entries(options.rowCorrections)
    .map(([row, fields]) => [row, Object.entries(fields).sort(([a], [b]) => a.localeCompare(b))])
    .sort(([a], [b]) => Number(a) - Number(b));
  return JSON.stringify({
    mapping,
    corrections,
    supplierSpecific: options.supplierSpecific,
    defaultSupplier: options.supplierSpecific ? options.defaultSupplier.trim() : "",
    excludeInvalidRows: options.excludeInvalidRows,
  });
}

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
  // `intake` is what the user is editing; `appliedIntake` is what the preview
  // on screen was actually built with. Analysis only runs when they match.
  const [intake, setIntake] = useState<BomIntakeOptions>(freshIntakeOptions);
  const [appliedIntake, setAppliedIntake] = useState<BomIntakeOptions>(freshIntakeOptions);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState("");
  const [oneTimeReportRequired, setOneTimeReportRequired] = useState(false);
  const [summary, setSummary] = useState<AnalyzeSummary | null>(null);
  const [analysisId, setAnalysisId] = useState<string | null>(null);
  const [draftReady, setDraftReady] = useState(false);
  const [ignoredTestDraft, setIgnoredTestDraft] = useState(false);
  const ignoredTestDraftRef = useRef(false);
  const [backgroundNote, setBackgroundNote] = useState("");
  const [draftPersistNotice, setDraftPersistNotice] = useState("");
  const [validatedFileKey, setValidatedFileKey] = useState("");
  const [fileContentKey, setFileContentKey] = useState("");
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
        fileKey: fileContentKey || current.fileKey,
        // Row detail and column samples are rebuilt from the file after a reload.
        validation: validation ? { ...validation, rows: [] } : null,
        validationError,
        intake: appliedIntake,
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
      fileContentKey,
      validation,
      validationError,
      appliedIntake,
      analysisId,
      summary,
      analyzeError,
      oneTimeReportRequired,
    ],
  );

  const refreshRecentReports = useCallback(() => {
    if (!session) return;
    setReportsBusy(true);
    setReportsError("");
    listReports(session.access_token)
      .then((payload) => {
        setRecentReports(payload.reports || []);
      })
      .catch((err) => {
        setReportsError(err instanceof Error ? err.message : "Reports could not load.");
      })
      .finally(() => {
        setReportsBusy(false);
      });
  }, [session]);

  useEffect(() => {
    if (!session) return;
    refreshRecentReports();
  }, [session, refreshRecentReports]);

  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    (async () => {
      const meta = readDraftMeta(session);
      if (isInternalTestDraft(meta)) {
        ignoredTestDraftRef.current = true;
        setIgnoredTestDraft(true);
        setDraftReady(true);
        return;
      }
      setProjectName(meta.projectName || "");
      setBomName(meta.bomName || "");
      setRevision(meta.revision || "A");
      setValidation(meta.validation);
      setValidationError(meta.validationError || "");
      const restoredIntake: BomIntakeOptions = {
        ...freshIntakeOptions(),
        ...(meta.intake || {}),
        rowCorrections: { ...(meta.intake?.rowCorrections || {}) },
      };
      setIntake(restoredIntake);
      setAppliedIntake(restoredIntake);
      setValidatedFileKey(meta.fileKey || "");
      selectedFileKeyRef.current = meta.fileKey || "";
      setAnalyzeError(meta.analyzeError || "");
      setOneTimeReportRequired(Boolean(meta.oneTimeReportRequired));
      setSummary(meta.summary);
      setAnalysisId(meta.analysisId);
      const restored = await loadDraftFile(session);
      if (cancelled) return;
      if (restored) {
        setFile(restored);
        const key = await fileIdentityKey(restored);
        if (cancelled) return;
        selectedFileKeyRef.current = key;
        setFileContentKey(key);
        if (meta.fileKey && meta.fileKey !== key) {
          setValidation(null);
          setValidatedFileKey("");
        } else if (meta.validation && meta.fileKey === key) {
          setValidatedFileKey(key);
          // Rebuild the row-by-row review from the file with the saved choices.
          const requestId = ++validationRequestIdRef.current;
          setValidating(true);
          void runValidation(restored, requestId, key, restoredIntake);
        }
      }
      const job = getActiveAnalyzeJob(session);
      if (job?.status === "running") {
        setAnalyzing(true);
        setBackgroundNote(
          "Analysis continues in this browser session while you use other pages. Return here to see status.",
        );
      } else if (job?.status === "succeeded" && job.result) {
        const summaryResult = parseAnalyzeSummary(job.result);
        if (!summaryResult) {
          setAnalyzeError("Analyze returned an incomplete summary.");
          setAnalyzing(false);
          clearFinishedAnalyzeJob(session);
        } else if (summaryResult.persisted === false) {
          setAnalyzeError(
            "Analysis completed but was not saved to your workspace. Retry the analysis.",
          );
          setSummary(null);
          setAnalysisId(null);
          setAnalyzing(false);
          clearFinishedAnalyzeJob(session);
        } else {
          trackMarketingEventOnce(
            "bom_uploaded",
            `bom_uploaded:${summaryResult.analysis_id}`,
            { flow: "saved-bom-analysis" },
            "/bom-analyzer",
          );
          trackMarketingEventOnce(
            "first_analysis_completed",
            `first_analysis_completed:${session.user_id || ""}`,
            { flow: "saved-bom-analysis" },
            "/bom-analyzer",
          );
          setSummary(summaryResult);
          setAnalysisId(summaryResult.analysis_id);
          setAnalyzing(false);
          rememberAnalysis({ ...summaryResult, filename: job.fileName }, session);
          persistMeta({
            summary: summaryResult,
            analysisId: summaryResult.analysis_id,
            analyzeError: "",
            oneTimeReportRequired: false,
          });
          clearFinishedAnalyzeJob(session);
          refreshRecentReports();
        }
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
      if (ignoredTestDraftRef.current) return;
      if (!job) return;
      if (job.ownerKey && job.ownerKey !== identityKey(session)) {
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
        const summaryResult = parseAnalyzeSummary(job.result);
        setAnalyzing(false);
        if (!summaryResult) {
          setAnalyzeError("Analyze returned an incomplete summary.");
          clearFinishedAnalyzeJob(session);
          return;
        }
        if (summaryResult.persisted === false) {
          setAnalyzeError(
            "Analysis completed but was not saved to your workspace. Retry the analysis.",
          );
          setSummary(null);
          setAnalysisId(null);
          clearFinishedAnalyzeJob(session);
          return;
        }
        trackMarketingEventOnce(
          "bom_uploaded",
          `bom_uploaded:${summaryResult.analysis_id}`,
          { flow: "saved-bom-analysis" },
          "/bom-analyzer",
        );
        trackMarketingEventOnce(
          "first_analysis_completed",
          `first_analysis_completed:${session.user_id || ""}`,
          { flow: "saved-bom-analysis" },
          "/bom-analyzer",
        );
        setSummary(summaryResult);
        setAnalysisId(summaryResult.analysis_id);
        setAnalyzeError("");
        setOneTimeReportRequired(false);
        rememberAnalysis({ ...summaryResult, filename: job.fileName }, session);
        writeDraftMeta(
          {
            ...readDraftMeta(session),
            summary: summaryResult,
            analysisId: summaryResult.analysis_id,
            analyzeError: "",
            oneTimeReportRequired: false,
          },
          session,
        );
        clearFinishedAnalyzeJob(session);
        refreshRecentReports();
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
  }, [session, refreshRecentReports]);

  useEffect(() => {
    if (!session || !draftReady || ignoredTestDraftRef.current) return;
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
    appliedIntake,
    analysisId,
    summary,
    analyzeError,
    oneTimeReportRequired,
    persistMeta,
  ]);

  const runValidation = useCallback(
    async (nextFile: File, requestId: number, fileKey: string, options: BomIntakeOptions) => {
      if (!session) return;
      try {
        const preview = await validateBom(nextFile, session.access_token, options);
        if (requestId !== validationRequestIdRef.current) return;
        if (selectedFileKeyRef.current !== fileKey) return;
        setValidation(preview);
        setValidatedFileKey(fileKey);
        setAppliedIntake(options);
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
    if (next) {
      ignoredTestDraftRef.current = false;
      setIgnoredTestDraft(false);
    }
    // Synchronously clear previous validation before any await.
    const requestId = ++validationRequestIdRef.current;
    selectedFileKeyRef.current = "";
    setFileContentKey("");
    setFile(next);
    setValidation(null);
    // A new file never inherits another file's mapping or corrections.
    setIntake(freshIntakeOptions());
    setAppliedIntake(freshIntakeOptions());
    setValidationError("");
    setValidatedFileKey("");
    setDraftPersistNotice("");
    setSummary(null);
    setAnalysisId(null);
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
    let workingFile: File;
    let nextKey: string;
    try {
      // Materialize bytes immediately so a later NotFoundError on the picker
      // handle (or a failed IndexedDB draft write) cannot strand Validating.
      const materialized = await materializeBomFile(next);
      workingFile = materialized.file;
      nextKey = materialized.identityKey;
    } catch (err) {
      if (requestId !== validationRequestIdRef.current) return;
      setValidating(false);
      setFile(null);
      setValidation(null);
      setValidatedFileKey("");
      setFileContentKey("");
      selectedFileKeyRef.current = "";
      const message =
        err instanceof Error
          ? err.message
          : "The selected BOM file could not be read.";
      setValidationError(
        /notfound|not found|could not be found/i.test(message)
          ? "The selected BOM file became unavailable before validation. Re-select the file to continue."
          : message,
      );
      return;
    }
    if (requestId !== validationRequestIdRef.current) return;
    setFile(workingFile);
    selectedFileKeyRef.current = nextKey;
    setFileContentKey(nextKey);
    // Never gate POST /boms/validate on IndexedDB. Draft save is best-effort and
    // must not leave Validating stuck if open/put stalls.
    void saveDraftFile(workingFile, session).catch((err) => {
      if (requestId !== validationRequestIdRef.current) return;
      setDraftPersistNotice(
        err instanceof Error
          ? `Draft could not be saved for later resume (${err.message}). Validation continues with the file still in memory.`
          : "Draft could not be saved for later resume. Validation continues with the file still in memory.",
      );
    });
    await runValidation(workingFile, requestId, nextKey, freshIntakeOptions());
  }

  function onRecheck() {
    if (!session || !file || validating || analyzing || !fileContentKey) return;
    const requestId = ++validationRequestIdRef.current;
    setValidating(true);
    setValidationError("");
    void runValidation(file, requestId, fileContentKey, intake);
  }

  const intakeDirty = intakeSignature(intake) !== intakeSignature(appliedIntake);

  function onAnalyze() {
    if (!session || !file || analyzing) return;
    const matches =
      !intakeDirty &&
      Boolean(validation?.can_analyze) &&
      Boolean(fileContentKey) &&
      validatedFileKey === fileContentKey &&
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
        intake: appliedIntake,
      },
      session,
    );
    setAnalyzing(true);
  }

  const validationMatchesFile = Boolean(
    file &&
      validation &&
      validatedFileKey &&
      fileContentKey &&
      validatedFileKey === fileContentKey,
  );

  if (!session) return null;

  const visibleReports = recentReports
    .filter((row) => row.id || row.analysis_id)
    .slice(0, 3);
  const canAnalyze = Boolean(
    file &&
      !intakeDirty &&
      validationMatchesFile &&
      validation?.can_analyze &&
      !analyzing &&
      !validating,
  );

  const savedAnalysisId = String(analysisId || summary?.analysis_id || "");
  const primary = savedAnalysisId
    ? {
        label: "Open risk review",
        href: `/detailed-risk-report?analysis_id=${encodeURIComponent(savedAnalysisId)}`,
      }
    : analyzing
      ? { label: "Analysis in progress…", disabled: true }
      : validating
        ? { label: "Validating…", disabled: true }
        : file && validationMatchesFile && intakeDirty
          ? { label: "Re-check with my changes", action: "recheck" as const }
          : analyzeError
          ? { label: "Retry analysis", action: "retry-analyze" as const }
          : canAnalyze
            ? { label: "Analyze BOM", action: "analyze" as const }
            : file && validationMatchesFile && validation && !validation.can_analyze
              ? { label: "Fix file and re-check", action: "choose-file" as const }
              : { label: "Choose BOM file", action: "choose-file" as const };

  function handlePrimary() {
    if ("disabled" in primary && primary.disabled) return;
    if (!("action" in primary)) return;
    if (primary.action === "choose-file") {
      fileInputRef.current?.click();
      return;
    }
    if (primary.action === "recheck") {
      onRecheck();
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

      <div
        className={`cv-bom-workspace-grid${validation?.columns?.length ? " cv-bom-workspace-grid--review" : ""}`}
      >
        <section className="cv-card pad cv-bom-create-card">
          <div>
            <h2 className="cv-card-title">Create a BOM analysis</h2>
            <p className="cv-card-subtitle">
              Add project details, upload the file, then review validation before analysis.
            </p>
          </div>

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
          {ignoredTestDraft ? (
            <p className="cv-bom-guidance-note" role="status">
              A test-only draft was not loaded. Choose a BOM file to start a new analysis.
            </p>
          ) : null}

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
                  Row counts are source BOM rows before part aggregation. Nothing is guessed: unclear columns and values are flagged for you.
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
                  {validation.columns?.length ? (
                    <BomIntakeReview
                      validation={validation}
                      options={intake}
                      onChange={setIntake}
                      onApply={onRecheck}
                      dirty={intakeDirty}
                      busy={validating || analyzing}
                    />
                  ) : (
                    <>
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
                  )}
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
                Saved {userFacingLabel(summary.project_name || summary.bom_name, "BOM analysis")}
                {summary.has_hierarchy
                  ? ` · assembly roll-up ${summary.top_rolled_risk || "n/a"}`
                  : ""}{" "}
                · {summary.total_parts} parts · health{" "}
                {summary.health_score != null
                  ? summary.health_score
                  : summary.health_status === "Needs verification"
                    ? "Needs verification"
                    : "—"}
              </p>
              <p className="cv-small-note">
                Your analysis is saved. Continue to the risk review whenever you are ready; other workspace pages remain available.
              </p>
            </div>
          ) : null}

          <div className="cv-bom-analyze-actions cv-bom-primary-cta">
            {"href" in primary && primary.href ? (
              <Link className="cv-button primary" href={primary.href}>
                {primary.label}
              </Link>
            ) : (
              <button
                type="button"
                className="cv-button primary"
                disabled={
                  ("disabled" in primary && primary.disabled) ||
                  (("action" in primary) && (primary.action === "analyze" || primary.action === "retry-analyze")
                    ? !canAnalyze
                    : false)
                }
                onClick={handlePrimary}
              >
                {primary.label}
              </button>
            )}
            {canAnalyze && (! ("action" in primary) || primary.action !== "analyze") ? (
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
                <span><strong>Confirm required columns</strong><small>Part number and quantity are required; manufacturer is recommended. You can correct column roles and values before analysis.</small></span>
              </li>
              <li>
                <span className="cv-bom-check-icon"><Icon name="shield" /></span>
                <span><strong>Review evidence coverage</strong><small>After analysis, inspect source labels on the Evidence page.</small></span>
              </li>
              <li>
                <span className="cv-bom-check-icon"><Icon name="report" /></span>
                <span><strong>Keep reports available</strong><small>Saved analyses remain in your workspace so you can reopen them later.</small></span>
              </li>
            </ul>
          </section>

          <section className="cv-card pad cv-bom-side-card cv-bom-recent-card">
            <div className="cv-bom-recent-heading">
              <div>
                <h2 className="cv-card-title">Recent analyses</h2>
                <p className="cv-card-subtitle">Reopen any saved analysis whenever you are ready.</p>
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
                  const title = userFacingLabel(row.bom_name || row.filename || row.project_name, "BOM analysis");
                  const revisionLabel = row.revision ? ` · rev ${String(row.revision)}` : "";
                  const partsLabel = row.total_parts == null ? "Saved report" : `${String(row.total_parts)} parts`;
                  const dateLabel = formatReportDate(row.created_at);
                  return (
                    <li key={id}>
                      <Link
                        href={`/reports/${encodeURIComponent(id)}`}
                        className="cv-bom-recent-link"
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
