"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "@/components/Icons";
import { Shell } from "@/components/Shell";
import { PageHeader, SecondaryLink } from "@/components/PageHeader";
import { BomIntakeReview } from "@/components/BomIntakeReview";
import {
  beginUsageOverageCheckout,
  DEFAULT_BOM_INTAKE_OPTIONS,
  fetchBillingStatus,
  fetchPlanUsage,
  fetchReport,
  listProjects,
  listReports,
  validateBom,
  type AnalyzeSummary,
  type BomIntakeOptions,
  type BomValidationPreview,
} from "@/lib/api";
import {
  clearDraftFile,
  clearDraftMeta,
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
import { trackMarketingEvent, trackMarketingEventOnce } from "@/lib/marketingAnalytics";

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

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

type SavedBomPrefill = {
  projectName: string;
  bomName: string;
  revision: string;
  sourceAnalysisId: string;
  intake: BomIntakeOptions;
};

function csvCell(value: unknown): string {
  return `"${String(value ?? "").replaceAll('"', '""')}"`;
}

function clearSavedBomSourceQuery(): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (!url.searchParams.has("source_analysis_id")) return;
  url.searchParams.delete("source_analysis_id");
  window.history.replaceState(
    window.history.state,
    "",
    `${url.pathname}${url.search}${url.hash}`,
  );
}

function createSavedBomFile(report: Record<string, unknown>): {
  file: File;
  intake: BomIntakeOptions;
} {
  const parts = Array.isArray(report.parts) ? report.parts.map(asRecord) : [];
  const rows: Array<Record<string, string>> = [];
  for (const part of parts) {
    const sourceRows = Array.isArray(part.source_rows) ? part.source_rows.map(asRecord) : [];
    if (sourceRows.length) {
      for (const sourceRow of sourceRows) {
        const normalized = asRecord(sourceRow.normalized);
        const row: Record<string, string> = {
          mpn: String(normalized.mpn || part.MPN || part.mpn || ""),
          manufacturer: String(normalized.manufacturer || part.Manufacturer || part.manufacturer || ""),
          description: String(normalized.description || part.Description || part.description || ""),
          parent_mpn: String(normalized.parent_mpn || part["Parent MPN"] || part.parent_mpn || ""),
          line_type: String(normalized.line_type || part["Line Type"] || part.line_type || ""),
          quantity: String(normalized.quantity ?? part["Quantity"] ?? part.quantity ?? "1"),
          reference_designators: String(normalized.reference_designators || ""),
          bom_level: String(normalized.bom_level || ""),
          supplier_part_number: String(normalized.supplier_part_number || ""),
          supplier: String(normalized.supplier || ""),
        };
        if (row.mpn.trim()) rows.push(row);
      }
    } else {
      const row: Record<string, string> = {
        mpn: String(part.MPN || part.mpn || ""),
        manufacturer: String(part.Manufacturer || part.manufacturer || ""),
        description: String(part.Description || part.description || ""),
        parent_mpn: String(part["Parent MPN"] || part.parent_mpn || ""),
        line_type: String(part["Line Type"] || part.line_type || ""),
        quantity: String(part.quantity_per_parent ?? part["Quantity per Parent"] ?? part.Quantity ?? part.quantity ?? "1"),
        reference_designators: String(part.reference_designators || ""),
        bom_level: String(part.bom_level || ""),
        supplier_part_number: String(part.supplier_part_number || ""),
        supplier: String(part.supplier || ""),
      };
      if (row.mpn.trim()) rows.push(row);
    }
  }
  if (!rows.length) {
    throw new Error("This saved report does not contain reusable BOM rows. Choose the original BOM file to run a new analysis.");
  }

  const intakeRecord = asRecord(report.intake);
  const supplierSpecific = intakeRecord.supplier_specific === true;
  const headers: Array<[string, string]> = [
    ["mpn", "MPN"],
    ["manufacturer", "Manufacturer"],
    ["description", "Description"],
    ["parent_mpn", "Parent MPN"],
    ["line_type", "Line Type"],
    ["quantity", "Quantity"],
    ["reference_designators", "Reference Designators"],
    ["bom_level", "BOM Level"],
    ["supplier_part_number", "Supplier Part Number"],
    ...(supplierSpecific ? [["supplier", "Supplier"] as [string, string]] : []),
  ];
  const csv = [
    headers.map(([, label]) => csvCell(label)).join(","),
    ...rows.map((row) => headers.map(([key]) => csvCell(row[key])).join(",")),
  ].join("\r\n");
  const stem = String(report.bom_name || report.filename || "Saved-BOM")
    .replace(/\.(csv|xlsx)$/i, "")
    .replace(/[^a-z0-9-_]+/gi, "-")
    .replace(/^-+|-+$/g, "") || "Saved-BOM";
  const file = new File([csv], `${stem}-saved.csv`, { type: "text/csv" });
  const intake = { ...freshIntakeOptions(), supplierSpecific };
  return { file, intake };
}

function formatPriceFromCents(amount: unknown, currency: unknown): string {
  const cents = Number(amount);
  if (!Number.isFinite(cents) || cents <= 0) return "";
  const code = String(currency || "usd").toUpperCase();
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: code }).format(cents / 100);
  } catch {
    return `$${(cents / 100).toFixed(2)}`;
  }
}

export default function BomAnalyzerPage() {
  const session = useRequireSession();
  const accessToken = session?.access_token || "";
  const fileInputRef = useRef<HTMLInputElement>(null);
  const draftFileWriteRef = useRef<Promise<void> | null>(null);
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
  const [planUsageSnapshot, setPlanUsageSnapshot] = useState<Record<string, unknown> | null>(null);
  const [billingSnapshot, setBillingSnapshot] = useState<Record<string, unknown> | null>(null);
  const [analysisPackBusy, setAnalysisPackBusy] = useState(false);
  const [analysisPackError, setAnalysisPackError] = useState("");
  const [summary, setSummary] = useState<AnalyzeSummary | null>(null);
  const [analysisId, setAnalysisId] = useState<string | null>(null);
  const [sourceAnalysisId, setSourceAnalysisId] = useState<string | null>(null);
  const [savedBomNameForAnalysis, setSavedBomNameForAnalysis] = useState("");
  const [loadingSavedBom, setLoadingSavedBom] = useState(false);
  const [savedBomLoadError, setSavedBomLoadError] = useState("");
  const [draftReady, setDraftReady] = useState(false);
  const [clearingBom, setClearingBom] = useState(false);
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
        fileName: file?.name || "",
        fileSize: file?.size || 0,
        fileType: file?.type || "",
        fileKey: fileContentKey || "",
        // Row detail and column samples are rebuilt from the file after a reload.
        validation: validation ? { ...validation, rows: [] } : null,
        validationError,
        intake: appliedIntake,
        analysisId,
        sourceAnalysisId,
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
      sourceAnalysisId,
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

  const refreshUsageAndBilling = useCallback(async () => {
    if (!accessToken) return;
    const [usageResult, billingResult] = await Promise.allSettled([
      fetchPlanUsage(accessToken),
      fetchBillingStatus(accessToken),
    ]);
    if (usageResult.status === "fulfilled") setPlanUsageSnapshot(usageResult.value);
    if (billingResult.status === "fulfilled") setBillingSnapshot(billingResult.value);
  }, [accessToken]);

  useEffect(() => {
    if (!accessToken) return;
    refreshRecentReports();
  }, [accessToken, refreshRecentReports]);

  useEffect(() => {
    void refreshUsageAndBilling();
  }, [refreshUsageAndBilling]);

  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    (async () => {
      const sourceId = new URLSearchParams(window.location.search)
        .get("source_analysis_id")
        ?.trim();
      if (sourceId) {
        setLoadingSavedBom(true);
        setFile(null);
        setSummary(null);
        setAnalysisId(null);
        setSourceAnalysisId(sourceId);
        setSavedBomLoadError("");
        try {
          const [savedReport, projectsPayload] = await Promise.all([
            fetchReport(sourceId, session.access_token),
            listProjects(session.access_token).catch(() => ({ projects: [] })),
          ]);
          if (cancelled) return;
          const report = savedReport as unknown as Record<string, unknown>;
          const { file: savedFile, intake: savedIntake } = createSavedBomFile(report);
          const projectId = String(report.project_id || "");
          const project = (projectsPayload.projects || [])
            .find((row) => String(row.id || "") === projectId);
          const reportedProject = String(report.project_name || "");
          const projectName = String(project?.name || reportedProject.split(" — ")[0] || "");
          const bomName = String(report.bom_name || report.filename || "Saved BOM");
          const prefill: SavedBomPrefill = {
            projectName,
            bomName,
            revision: String(report.revision || "A"),
            sourceAnalysisId: String(report.analysis_id || report.id || sourceId),
            intake: savedIntake,
          };
          setSavedBomNameForAnalysis(bomName);
          await onFileChosen(savedFile, prefill);
          if (cancelled) return;
        } catch (err) {
          if (!cancelled) {
            setSavedBomLoadError(
              err instanceof Error
                ? err.message
                : "The saved BOM could not be loaded. Open Saved analyses and try again.",
            );
          }
        } finally {
          if (!cancelled) {
            setLoadingSavedBom(false);
            setDraftReady(true);
          }
        }
        return;
      }

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
      setSourceAnalysisId(meta.sourceAnalysisId || null);
      setSavedBomNameForAnalysis(meta.sourceAnalysisId ? meta.bomName : "");
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
          clearSavedBomSourceQuery();
          refreshRecentReports();
          void refreshUsageAndBilling();
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
        clearSavedBomSourceQuery();
        refreshRecentReports();
        void refreshUsageAndBilling();
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

  async function onFileChosen(next: File | null, savedContext?: SavedBomPrefill) {
    // Cancelling the native file picker should leave the current BOM untouched.
    if (!session || !next || clearingBom) return;
    ignoredTestDraftRef.current = false;
    setIgnoredTestDraft(false);
    const nextIntake = savedContext?.intake || freshIntakeOptions();
    if (savedContext) {
      setProjectName(savedContext.projectName);
      setBomName(savedContext.bomName);
      setRevision(savedContext.revision);
      setSourceAnalysisId(savedContext.sourceAnalysisId);
      setSavedBomNameForAnalysis(savedContext.bomName);
      setSavedBomLoadError("");
    } else {
      setSourceAnalysisId(null);
      setSavedBomNameForAnalysis("");
      setLoadingSavedBom(false);
      setSavedBomLoadError("");
    }
    // Synchronously clear previous validation before any await.
    const requestId = ++validationRequestIdRef.current;
    selectedFileKeyRef.current = "";
    setFileContentKey("");
    setFile(next);
    setValidation(null);
    // A new file never inherits another file's mapping or corrections.
    setIntake(nextIntake);
    setAppliedIntake(nextIntake);
    setValidationError("");
    setValidatedFileKey("");
    setDraftPersistNotice("");
    setSummary(null);
    setAnalysisId(null);
    setAnalyzeError("");
    setAnalysisPackError("");
    setOneTimeReportRequired(false);
    setBackgroundNote("");
    setValidating(Boolean(next));
    if (next.size > 10 * 1024 * 1024) {
      setValidating(false);
      setValidationError("BOM file must be 10 MB or smaller.");
      return;
    }
    if (!(savedContext?.bomName || bomName).trim()) {
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
    const previousDraftWrite = draftFileWriteRef.current || Promise.resolve();
    const draftWrite = previousDraftWrite
      .catch(() => undefined)
      .then(
        () =>
          new Promise<void>((resolve, reject) => {
            void saveDraftFile(workingFile, session).then(resolve, reject);
          }),
      );
    draftFileWriteRef.current = draftWrite;
    void draftWrite.catch((err) => {
      if (requestId !== validationRequestIdRef.current) return;
      setDraftPersistNotice(
        err instanceof Error
          ? `Draft could not be saved for later resume (${err.message}). Validation continues with the file still in memory.`
          : "Draft could not be saved for later resume. Validation continues with the file still in memory.",
      );
    });
    await runValidation(workingFile, requestId, nextKey, nextIntake);
  }

  async function onClearBom() {
    if (!session || analyzing || validating || clearingBom) return;
    setClearingBom(true);
    ++validationRequestIdRef.current;
    selectedFileKeyRef.current = "";
    if (fileInputRef.current) fileInputRef.current.value = "";
    setFile(null);
    setProjectName("");
    setBomName("");
    setRevision("A");
    setSourceAnalysisId(null);
    setSavedBomNameForAnalysis("");
    setSavedBomLoadError("");
    setValidating(false);
    setValidation(null);
    setValidationError("");
    setIntake(freshIntakeOptions());
    setAppliedIntake(freshIntakeOptions());
    setValidatedFileKey("");
    setFileContentKey("");
    setDraftPersistNotice("");
    setSummary(null);
    setAnalysisId(null);
    setAnalyzeError("");
    setAnalysisPackError("");
    setOneTimeReportRequired(false);
    setBackgroundNote("");
    ignoredTestDraftRef.current = false;
    setIgnoredTestDraft(false);
    clearDraftMeta(session);
    try {
      await draftFileWriteRef.current?.catch(() => undefined);
      await clearDraftFile(session);
      clearDraftMeta(session);
    } finally {
      setClearingBom(false);
    }
  }

  async function onSampleBom() {
    if (analyzing || validating) return;
    try {
      const response = await fetch("/sample-bom.csv", { cache: "force-cache" });
      if (!response.ok) throw new Error("The sample BOM is unavailable right now.");
      const text = await response.text();
      const sample = new File([text], "Cadivor_sample_BOM.csv", { type: "text/csv" });
      setProjectName("Sample controller project");
      await onFileChosen(sample);
      setBomName("Sample controller BOM");
    } catch (err) {
      setValidationError(err instanceof Error ? err.message : "Could not load the sample BOM.");
    }
  }

  async function onBuyAnalysisPack(placement: "near_limit" | "limit") {
    if (!session || analysisPackBusy) return;
    setAnalysisPackBusy(true);
    setAnalysisPackError("");
    trackMarketingEvent("upgrade_clicked", {
      intent: "bom-analysis-overage",
      placement,
      plan: String(billingSnapshot?.current_plan || planUsageSnapshot?.plan || "unknown").toLowerCase(),
    }, "/bom-analyzer");
    try {
      const result = await beginUsageOverageCheckout(session.access_token, "bom_analysis");
      if (!result.ok || !result.checkout?.url) {
        throw new Error(result.detail || "Billing could not be started. Please try again or contact support.");
      }
      trackMarketingEvent("checkout_started", {
        intent: "bom-analysis-overage",
        placement,
        plan: String(billingSnapshot?.current_plan || planUsageSnapshot?.plan || "unknown").toLowerCase(),
      }, "/bom-analyzer");
      window.location.assign(result.checkout.url);
    } catch (err) {
      setAnalysisPackError(err instanceof Error ? err.message : "Billing could not be started. Please try again or contact support.");
    } finally {
      setAnalysisPackBusy(false);
    }
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
        sourceAnalysisId: sourceAnalysisId || undefined,
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
  const usageLimits = asRecord(planUsageSnapshot?.limits);
  const usage = asRecord(planUsageSnapshot?.usage);
  const overageCredits = asRecord(usage.overage_credits);
  const monthlyLimit = Number(usageLimits.monthly_bom_limit);
  const monthlyUsed = Number(usage.analyses_this_month);
  const availableAnalysisCredits = Number(overageCredits.bom_analysis || 0);
  const hasFiniteMonthlyLimit = Number.isFinite(monthlyLimit) && monthlyLimit > 0;
  const reachedMonthlyLimit = hasFiniteMonthlyLimit && monthlyUsed >= monthlyLimit && availableAnalysisCredits <= 0;
  const nearMonthlyLimit = hasFiniteMonthlyLimit &&
    monthlyUsed >= Math.max(1, Math.ceil(monthlyLimit * 0.8)) &&
    monthlyUsed < monthlyLimit && availableAnalysisCredits <= 0;
  const analysisPack = asRecord(asRecord(billingSnapshot?.addons).bom_analysis);
  const analysisPackCredits = Number(analysisPack.credits);
  const analysisPackPrice = formatPriceFromCents(analysisPack.amount, analysisPack.currency);
  const canBuyAnalysisPack = billingSnapshot?.has_active_subscription === true && analysisPack.enabled === true;
  const analysisPackLabel = analysisPackCredits > 0
    ? `Buy ${analysisPackCredits.toLocaleString()} more analyses${analysisPackPrice ? ` · ${analysisPackPrice} one time` : ""}`
    : "Buy analysis pack";
  const primary = savedAnalysisId
    ? {
        label: "Review risk findings",
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
        className={`cv-bom-workspace-grid${file ? " cv-bom-workspace-grid--review" : ""}`}
      >
        <section className="cv-card pad cv-bom-create-card">
          <div>
            <h2 className="cv-card-title">Create a BOM analysis</h2>
            <p className="cv-card-subtitle">
              Add project details, upload the file, then review validation before analysis.
            </p>
            {loadingSavedBom ? (
              <div className="cv-evidence-context" role="status" style={{ marginTop: 10 }}>
                Loading the saved BOM and project details. No file upload is needed.
              </div>
            ) : null}
            {savedBomLoadError ? (
              <div className="cv-error" role="alert" style={{ marginTop: 10 }}>
                {savedBomLoadError} You can still choose a BOM file to continue.
              </div>
            ) : null}
            {sourceAnalysisId && file ? (
              <div className="cv-evidence-context" role="note" style={{ marginTop: 10 }}>
                <strong>Saved BOM loaded:</strong> {userFacingLabel(savedBomNameForAnalysis || bomName, "BOM")}.
                {" "}Its saved component list and project details are prefilled; no upload is needed.
                {" "}Analyzing creates a new report and leaves the current report unchanged.
              </div>
            ) : null}
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

          {nearMonthlyLimit ? (
            <div className="cv-notice" role="status">
              <strong>You’ve used {monthlyUsed} of {monthlyLimit} BOM analyses this month.</strong>
              <p style={{ margin: "5px 0 10px" }}>
                The next analysis may be blocked when you reach your plan limit.
              </p>
              {canBuyAnalysisPack ? (
                <button
                  className="cv-button"
                  type="button"
                  disabled={analysisPackBusy}
                  onClick={() => void onBuyAnalysisPack("near_limit")}
                >
                  {analysisPackBusy ? "Opening checkout…" : analysisPackLabel}
                </button>
              ) : (
                <Link className="cv-button" href="/settings?tab=billing">Review plan and billing options</Link>
              )}
              {analysisPackError ? <p className="cv-error" role="alert" style={{ marginTop: 10 }}>{analysisPackError}</p> : null}
            </div>
          ) : null}

          <div className="cv-bom-fields cv-bom-fields-grid">
            <label className="cv-field">
              <span>Project</span>
              <input
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                placeholder="e.g. Motor controller"
                disabled={analyzing || clearingBom}
              />
            </label>
            <label className="cv-field">
              <span>BOM name</span>
              <input
                value={bomName}
                onChange={(e) => setBomName(e.target.value)}
                placeholder="Defaults to filename"
                disabled={analyzing || clearingBom}
              />
            </label>
            <label className="cv-field">
              <span>Revision</span>
              <input
                value={revision}
                onChange={(e) => setRevision(e.target.value)}
                placeholder="e.g. A"
                disabled={analyzing || clearingBom}
              />
            </label>
          </div>

          <div className="cv-upload-zone cv-bom-upload-zone cv-bom-dropzone">
            <div className="cv-bom-upload-icon" aria-hidden="true">
              <Icon name="upload" />
            </div>
            <h3>{file ? (sourceAnalysisId ? savedBomNameForAnalysis || bomName : file.name) : "New analysis"}</h3>
            <p>
              {sourceAnalysisId
                ? "This saved BOM is ready to analyze. Review the part list below or choose a different file."
                : "Upload a CSV or XLSX BOM. Add Parent MPN and Line Type columns when you want to roll component risk up to assemblies."}
            </p>
            <div className="cv-bom-upload-controls">
              <label className="cv-bom-file-picker">
                <span>{file ? "Choose a different file" : "Choose file"}</span>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".csv,.xlsx"
                  disabled={analyzing || validating || clearingBom}
                  onChange={(e) => void onFileChosen(e.target.files?.[0] || null)}
                />
                <small>{file ? file.name : "CSV or XLSX · up to 10 MB"}</small>
              </label>
              <div className="cv-bom-upload-actions">
                {file ? (
                  <button
                    type="button"
                    className="cv-button secondary cv-bom-clear-button"
                    onClick={() => void onClearBom()}
                    disabled={analyzing || validating || clearingBom}
                    aria-label="Clear the selected BOM and return to a new analysis"
                  >
                    {clearingBom ? "Clearing…" : "Clear BOM"}
                  </button>
                ) : null}
                <button
                  type="button"
                  className="cv-button cv-bom-sample-button"
                  onClick={() => void onSampleBom()}
                  disabled={analyzing || validating || clearingBom}
                >
                  {file ? "Replace with the 5-part sample BOM" : "Load the 5-part sample BOM"}
                </button>
              </div>
            </div>
            <small className="cv-small-note">
              Illustrative quantities and project grouping; supplier evidence is fetched live when available.
            </small>
            <div className="cv-small-note" style={{ display: "flex", gap: 14, flexWrap: "wrap", justifyContent: "center" }}>
              <a href="/templates/cadivor-basic-bom-template.csv" download>Download basic BOM CSV template</a>
              <a href="/templates/cadivor-plm-erp-bom-template.csv" download>Download PLM / ERP item template</a>
            </div>
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
              {oneTimeReportRequired || reachedMonthlyLimit ? (
                <div style={{ marginTop: 10 }}>
                  {canBuyAnalysisPack ? (
                    <div style={{ marginBottom: 10 }}>
                      <button
                        className="cv-button primary"
                        type="button"
                        disabled={analysisPackBusy}
                        onClick={() => void onBuyAnalysisPack("limit")}
                      >
                        {analysisPackBusy ? "Opening checkout…" : analysisPackLabel}
                      </button>
                      <p className="cv-small-note" style={{ marginTop: 6 }}>
                        Add analysis capacity to your subscription, then return here and retry this BOM.
                      </p>
                    </div>
                  ) : reachedMonthlyLimit ? (
                    <p style={{ margin: "0 0 10px" }}>
                      <Link href="/settings?tab=billing">Review plan and usage options</Link>
                    </p>
                  ) : null}
                  {analysisPackError ? <p role="alert" style={{ margin: "0 0 10px" }}>{analysisPackError}</p> : null}
                  {oneTimeReportRequired ? (
                    <>
                      <Link
                        className="cv-button"
                        href="/single-bom-report"
                        target="_blank"
                        rel="noreferrer"
                      >
                        Open one-time report purchase
                      </Link>
                      <p className="cv-small-note" style={{ marginTop: 8 }}>
                        Keep this BOM open. After checkout is confirmed, return here and run the analysis; your selected file will still be ready.
                      </p>
                    </>
                  ) : null}
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
                Your analysis is saved. Other workspace pages remain available while you review it.
                {sourceAnalysisId ? " The previous saved report is unchanged; this report contains the new Procurement snapshot." : ""}
              </p>
              <Link
                className="cv-button"
                href={`/procurement?analysis_id=${encodeURIComponent(String(summary.analysis_id || ""))}`}
                style={{ width: "fit-content" }}
              >
                Open this report in Procurement
              </Link>
              <section className="cv-bom-next-step" aria-labelledby="cv-bom-next-step-title">
                <span className="cv-eyebrow">Next step</span>
                <h3 id="cv-bom-next-step-title">Review the highest-priority finding</h3>
                <p>Open the risk review to inspect flagged parts and their evidence before deciding what to do next.</p>
              </section>
            </div>
          ) : null}

          {file || savedAnalysisId || analyzing || analyzeError ? (
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
          ) : null}
        </section>

        <aside className="cv-bom-side-cards" aria-label="First-run guidance and recent analyses">
          {!file && !savedAnalysisId && !analyzing && !analyzeError ? (
            <section className="cv-card pad cv-bom-side-card cv-bom-checklist-card" aria-labelledby="cv-bom-first-run-title">
              <h2 id="cv-bom-first-run-title" className="cv-card-title">First-run checklist</h2>
              <p className="cv-card-subtitle">A guided path from your first BOM to ongoing follow-up.</p>
              <ol className="cv-bom-checklist">
                <li>
                  <span className="cv-bom-check-icon cv-bom-check-number">1</span>
                  <div><strong>Upload a BOM</strong><small>Choose a CSV or XLSX file, or load the sample.</small></div>
                </li>
                <li>
                  <span className="cv-bom-check-icon cv-bom-check-number">2</span>
                  <div><strong>Review the top blocker</strong><small>Inspect its evidence, or review the highest-priority finding if none are blocked.</small></div>
                </li>
                <li>
                  <span className="cv-bom-check-icon cv-bom-check-number">3</span>
                  <div><strong>Ask Cadivor a question</strong><small>Get context on a part, alert, or evidence source.</small></div>
                </li>
                <li>
                  <span className="cv-bom-check-icon cv-bom-check-number">4</span>
                  <div><strong>Create a decision record</strong><small>Capture the chosen action and its rationale.</small></div>
                </li>
                <li>
                  <span className="cv-bom-check-icon cv-bom-check-number">5</span>
                  <div><strong>Turn on monitoring</strong><small>Opt in to scheduled supplier checks for selected parts.</small></div>
                </li>
              </ol>
            </section>
          ) : null}

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
              <div className="cv-bom-recent-table-wrap">
                <table className="cv-bom-recent-table">
                  <thead>
                    <tr><th scope="col">File</th><th scope="col">Project</th><th scope="col">Health</th><th scope="col">Status</th></tr>
                  </thead>
                  <tbody>
                    {visibleReports.map((row) => {
                      const id = String(row.id || row.analysis_id || "");
                      const title = userFacingLabel(row.filename || row.bom_name || row.project_name, "BOM analysis");
                      const revisionLabel = row.revision ? ` · rev ${String(row.revision)}` : "";
                      const numericHealth = Number(row.health_score);
                      const hasHealth = row.health_score !== null && row.health_score !== undefined && String(row.health_score).trim() !== "" && Number.isFinite(numericHealth);
                      const healthLabel = hasHealth ? `${Math.round(numericHealth)}` : "Not scored";
                      const healthStatus = String(row.health_status || "").trim();
                      const needsVerification = !hasHealth || /needs verification|unknown|not scored|not reported|no data/i.test(healthStatus);
                      return (
                        <tr key={id}>
                          <td>
                            <Link href={`/reports/${encodeURIComponent(id)}`} className="cv-bom-recent-file" title={`${title}${revisionLabel}`}>
                              {title}{revisionLabel}
                            </Link>
                          </td>
                          <td className="cv-bom-recent-project">{userFacingLabel(row.project_name, "—")}</td>
                          <td><span className={`cv-bom-recent-badge ${hasHealth ? "is-health" : "is-muted"}`}>{healthLabel}</span></td>
                          <td><span className={`cv-bom-recent-badge ${needsVerification ? "is-review" : "is-complete"}`}>{needsVerification ? "Needs verification" : "Complete"}</span></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
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
