"use client";

import {
  analyzeBom,
  ApiError,
  type AnalyzeSummary,
  type BomValidationPreview,
  type Session,
} from "@/lib/api";

export type { BomValidationPreview };

const META_KEY = "cadivor_bom_analyzer_draft_meta";
const REVIEW_KEY = "cadivor_bom_review_progress";
const DB_NAME = "cadivor_bom_analyzer_draft";
const STORE = "files";
const FILE_ID = "current";

export type BomDraftMeta = {
  projectName: string;
  bomName: string;
  revision: string;
  fileName: string;
  fileSize: number;
  fileType: string;
  updatedAt: string;
  validation: BomValidationPreview | null;
  validationError: string;
  analysisId: string | null;
  summary: AnalyzeSummary | null;
  analyzeError: string;
  oneTimeReportRequired: boolean;
};

export type BomReviewProgress = {
  analysisId: string;
  risksOpenedAt?: string;
  evidenceReviewedAt?: string;
  decisionRecordedAt?: string;
  monitorOpenedAt?: string;
};

export type AnalyzeJobStatus = "idle" | "running" | "succeeded" | "failed";

export type AnalyzeJob = {
  id: string;
  status: AnalyzeJobStatus;
  startedAt: string;
  finishedAt?: string;
  fileName: string;
  projectName: string;
  bomName: string;
  revision: string;
  result?: AnalyzeSummary;
  error?: string;
  oneTimeReportRequired?: boolean;
};

type DraftFileRecord = {
  id: string;
  name: string;
  type: string;
  lastModified: number;
  blob: Blob;
};

function identityKey(session?: Pick<Session, "user_id" | "email">): string {
  const identity = session?.user_id || session?.email?.trim().toLowerCase();
  return identity || "anonymous";
}

function metaStorageKey(session?: Pick<Session, "user_id" | "email">): string {
  return `${META_KEY}:${identityKey(session)}`;
}

function reviewStorageKey(
  analysisId: string,
  session?: Pick<Session, "user_id" | "email">,
): string {
  return `${REVIEW_KEY}:${identityKey(session)}:${analysisId}`;
}

export function emptyDraftMeta(): BomDraftMeta {
  return {
    projectName: "",
    bomName: "",
    revision: "A",
    fileName: "",
    fileSize: 0,
    fileType: "",
    updatedAt: new Date().toISOString(),
    validation: null,
    validationError: "",
    analysisId: null,
    summary: null,
    analyzeError: "",
    oneTimeReportRequired: false,
  };
}

export function readDraftMeta(
  session?: Pick<Session, "user_id" | "email">,
): BomDraftMeta {
  if (typeof window === "undefined") return emptyDraftMeta();
  try {
    const raw = window.localStorage.getItem(metaStorageKey(session));
    if (!raw) return emptyDraftMeta();
    return { ...emptyDraftMeta(), ...(JSON.parse(raw) as BomDraftMeta) };
  } catch {
    return emptyDraftMeta();
  }
}

export function writeDraftMeta(
  meta: BomDraftMeta,
  session?: Pick<Session, "user_id" | "email">,
): void {
  if (typeof window === "undefined") return;
  const next = { ...meta, updatedAt: new Date().toISOString() };
  window.localStorage.setItem(metaStorageKey(session), JSON.stringify(next));
}

export function clearDraftMeta(session?: Pick<Session, "user_id" | "email">): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(metaStorageKey(session));
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = window.indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: "id" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error("IndexedDB unavailable"));
  });
}

export async function saveDraftFile(
  file: File,
  session?: Pick<Session, "user_id" | "email">,
): Promise<void> {
  if (typeof window === "undefined" || !window.indexedDB) return;
  const db = await openDb();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).put({
      id: `${FILE_ID}:${identityKey(session)}`,
      name: file.name,
      type: file.type,
      lastModified: file.lastModified,
      blob: file,
    } satisfies DraftFileRecord);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error || new Error("Could not save BOM draft file"));
  });
  db.close();
}

export async function loadDraftFile(
  session?: Pick<Session, "user_id" | "email">,
): Promise<File | null> {
  if (typeof window === "undefined" || !window.indexedDB) return null;
  try {
    const db = await openDb();
    const record = await new Promise<DraftFileRecord | undefined>((resolve, reject) => {
      const tx = db.transaction(STORE, "readonly");
      const request = tx.objectStore(STORE).get(`${FILE_ID}:${identityKey(session)}`);
      request.onsuccess = () => resolve(request.result as DraftFileRecord | undefined);
      request.onerror = () => reject(request.error || new Error("Could not load BOM draft file"));
    });
    db.close();
    if (!record?.blob) return null;
    return new File([record.blob], record.name, {
      type: record.type,
      lastModified: record.lastModified,
    });
  } catch {
    return null;
  }
}

export async function clearDraftFile(
  session?: Pick<Session, "user_id" | "email">,
): Promise<void> {
  if (typeof window === "undefined" || !window.indexedDB) return;
  try {
    const db = await openDb();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, "readwrite");
      tx.objectStore(STORE).delete(`${FILE_ID}:${identityKey(session)}`);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error || new Error("Could not clear BOM draft file"));
    });
    db.close();
  } catch {
    // Draft cleanup is best-effort.
  }
}

export function readReviewProgress(
  analysisId: string,
  session?: Pick<Session, "user_id" | "email">,
): BomReviewProgress {
  if (typeof window === "undefined") return { analysisId };
  try {
    const raw = window.localStorage.getItem(reviewStorageKey(analysisId, session));
    if (!raw) return { analysisId };
    const parsed = JSON.parse(raw) as BomReviewProgress;
    return { ...parsed, analysisId };
  } catch {
    return { analysisId };
  }
}

export function markReviewProgress(
  analysisId: string,
  patch: Partial<BomReviewProgress>,
  session?: Pick<Session, "user_id" | "email">,
): BomReviewProgress {
  const next = { ...readReviewProgress(analysisId, session), ...patch, analysisId };
  if (typeof window !== "undefined") {
    window.localStorage.setItem(reviewStorageKey(analysisId, session), JSON.stringify(next));
  }
  return next;
}

type JobListener = (job: AnalyzeJob | null) => void;

let activeJob: AnalyzeJob | null = null;
const listeners = new Set<JobListener>();

export function getActiveAnalyzeJob(): AnalyzeJob | null {
  return activeJob;
}

export function subscribeAnalyzeJob(listener: JobListener): () => void {
  listeners.add(listener);
  listener(activeJob);
  return () => listeners.delete(listener);
}

function emitJob() {
  for (const listener of listeners) listener(activeJob);
}

export function startAnalyzeJob(
  file: File,
  token: string,
  meta: { projectName?: string; bomName?: string; revision?: string },
): AnalyzeJob {
  if (activeJob?.status === "running") return activeJob;

  const job: AnalyzeJob = {
    id: `job-${Date.now()}`,
    status: "running",
    startedAt: new Date().toISOString(),
    fileName: file.name,
    projectName: meta.projectName || "",
    bomName: meta.bomName || "",
    revision: meta.revision || "A",
  };
  activeJob = job;
  emitJob();

  void analyzeBom(file, token, meta)
    .then((result) => {
      if (activeJob?.id !== job.id) return;
      activeJob = {
        ...job,
        status: "succeeded",
        finishedAt: new Date().toISOString(),
        result,
      };
      emitJob();
    })
    .catch((err) => {
      if (activeJob?.id !== job.id) return;
      activeJob = {
        ...job,
        status: "failed",
        finishedAt: new Date().toISOString(),
        error: err instanceof Error ? err.message : "Analyze failed",
        oneTimeReportRequired:
          err instanceof ApiError && err.payload.code === "one_time_report_required",
      };
      emitJob();
    });

  return job;
}

export function clearFinishedAnalyzeJob(): void {
  if (activeJob?.status === "running") return;
  activeJob = null;
  emitJob();
}
