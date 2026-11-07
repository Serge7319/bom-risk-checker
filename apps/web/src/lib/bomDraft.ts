"use client";

import {
  analyzeBom,
  ApiError,
  type AnalyzeSummary,
  type BomValidationPreview,
  type Session,
} from "@/lib/api";
import {
  clearFinishedAnalyzeJob as clearFinishedAnalyzeJobBase,
  getActiveAnalyzeJob as getActiveAnalyzeJobBase,
  resetAnalyzeJobsForTests as resetAnalyzeJobsForTestsBase,
  startAnalyzeJobWithRunner,
  subscribeAnalyzeJob as subscribeAnalyzeJobBase,
  type AnalyzeJob as AnalyzeJobBase,
  type AnalyzeJobStatus as AnalyzeJobStatusBase,
} from "@/lib/bomAnalyzeJobs";

export type { BomValidationPreview };

export type SessionIdentity = Pick<Session, "user_id" | "email" | "workspace_id">;
export type AnalyzeJobStatus = AnalyzeJobStatusBase;
export type AnalyzeJob = AnalyzeJobBase & { result?: AnalyzeSummary };

export function getActiveAnalyzeJob(session?: SessionIdentity) {
  return getActiveAnalyzeJobBase(session);
}
export function subscribeAnalyzeJob(
  listener: (job: AnalyzeJob | null) => void,
  session?: SessionIdentity,
) {
  return subscribeAnalyzeJobBase(listener as never, session);
}
export function clearFinishedAnalyzeJob(session?: SessionIdentity): void {
  clearFinishedAnalyzeJobBase(session);
}
export function resetAnalyzeJobsForTests(): void {
  resetAnalyzeJobsForTestsBase();
}

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
  fileKey: string;
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


type DraftFileRecord = {
  id: string;
  name: string;
  type: string;
  lastModified: number;
  blob: Blob;
};

export function identityKey(session?: SessionIdentity): string {
  const identity = session?.user_id || session?.email?.trim().toLowerCase();
  return identity || "anonymous";
}

export function fileIdentityKey(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

function metaStorageKey(session?: SessionIdentity): string {
  return `${META_KEY}:${identityKey(session)}`;
}

function reviewStorageKey(analysisId: string, session?: SessionIdentity): string {
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
    fileKey: "",
    updatedAt: new Date().toISOString(),
    validation: null,
    validationError: "",
    analysisId: null,
    summary: null,
    analyzeError: "",
    oneTimeReportRequired: false,
  };
}

export function readDraftMeta(session?: SessionIdentity): BomDraftMeta {
  if (typeof window === "undefined") return emptyDraftMeta();
  try {
    const raw = window.localStorage.getItem(metaStorageKey(session));
    if (!raw) return emptyDraftMeta();
    return { ...emptyDraftMeta(), ...(JSON.parse(raw) as BomDraftMeta) };
  } catch {
    return emptyDraftMeta();
  }
}

export function writeDraftMeta(meta: BomDraftMeta, session?: SessionIdentity): void {
  if (typeof window === "undefined") return;
  const next = { ...meta, updatedAt: new Date().toISOString() };
  window.localStorage.setItem(metaStorageKey(session), JSON.stringify(next));
}

export function clearDraftMeta(session?: SessionIdentity): void {
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

export async function saveDraftFile(file: File, session?: SessionIdentity): Promise<void> {
  if (typeof window === "undefined") {
    throw new Error("Draft persistence is only available in the browser.");
  }
  if (!window.indexedDB) {
    throw new Error("This browser does not support draft file persistence.");
  }
  const db = await openDb();
  try {
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
      tx.onabort = () => reject(tx.error || new Error("BOM draft save was aborted"));
    });
  } finally {
    db.close();
  }
}

export async function loadDraftFile(session?: SessionIdentity): Promise<File | null> {
  if (typeof window === "undefined" || !window.indexedDB) return null;
  try {
    const db = await openDb();
    try {
      const record = await new Promise<DraftFileRecord | undefined>((resolve, reject) => {
        const tx = db.transaction(STORE, "readonly");
        const request = tx.objectStore(STORE).get(`${FILE_ID}:${identityKey(session)}`);
        request.onsuccess = () => resolve(request.result as DraftFileRecord | undefined);
        request.onerror = () =>
          reject(request.error || new Error("Could not load BOM draft file"));
      });
      if (!record?.blob) return null;
      return new File([record.blob], record.name, {
        type: record.type,
        lastModified: record.lastModified,
      });
    } finally {
      db.close();
    }
  } catch {
    return null;
  }
}

export async function clearDraftFile(session?: SessionIdentity): Promise<void> {
  if (typeof window === "undefined" || !window.indexedDB) return;
  try {
    const db = await openDb();
    try {
      await new Promise<void>((resolve, reject) => {
        const tx = db.transaction(STORE, "readwrite");
        tx.objectStore(STORE).delete(`${FILE_ID}:${identityKey(session)}`);
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error || new Error("Could not clear BOM draft file"));
      });
    } finally {
      db.close();
    }
  } catch {
    // Draft cleanup is best-effort.
  }
}

export function readReviewProgress(
  analysisId: string,
  session?: SessionIdentity,
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
  session?: SessionIdentity,
): BomReviewProgress {
  const next = { ...readReviewProgress(analysisId, session), ...patch, analysisId };
  if (typeof window !== "undefined") {
    window.localStorage.setItem(reviewStorageKey(analysisId, session), JSON.stringify(next));
  }
  return next;
}

export function startAnalyzeJob(
  file: File,
  token: string,
  meta: { projectName?: string; bomName?: string; revision?: string },
  session?: SessionIdentity,
): AnalyzeJob {
  return startAnalyzeJobWithRunner(
    file,
    token,
    meta,
    session,
    async (f, t, m) => analyzeBom(f as File, t, m),
    (err) => ({
      message: err instanceof Error ? err.message : "Analyze failed",
      oneTimeReportRequired:
        err instanceof ApiError && err.payload.code === "one_time_report_required",
    }),
  ) as AnalyzeJob;
}

