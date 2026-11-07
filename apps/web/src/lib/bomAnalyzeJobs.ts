/** In-memory analyze jobs scoped by authenticated user + workspace. */

import type { AnalyzeSummary } from "./api";

export type AnalyzeJobStatus = "idle" | "running" | "succeeded" | "failed";

/** Job results must be full analyze summaries — never a partial payload. */
export type AnalyzeJobResult = AnalyzeSummary;

export type AnalyzeJob = {
  id: string;
  ownerKey: string;
  workspaceId?: string;
  status: AnalyzeJobStatus;
  startedAt: string;
  finishedAt?: string;
  fileName: string;
  projectName: string;
  bomName: string;
  revision: string;
  result?: AnalyzeJobResult;
  error?: string;
  oneTimeReportRequired?: boolean;
};

export type JobSessionIdentity = {
  user_id?: string;
  email?: string;
  workspace_id?: string;
};

type JobListener = (job: AnalyzeJob | null) => void;

export type AnalyzeRunner = (
  file: { name: string },
  token: string,
  meta: { projectName?: string; bomName?: string; revision?: string },
) => Promise<AnalyzeJobResult>;

const activeJobsByOwner = new Map<string, AnalyzeJob>();
const listenersByOwner = new Map<string, Set<JobListener>>();

/** Scope key: authenticated identity AND workspace (never user-only). */
export function identityKey(session?: JobSessionIdentity): string {
  const identity = session?.user_id || session?.email?.trim().toLowerCase() || "anonymous";
  const workspace = session?.workspace_id?.trim() || "no-workspace";
  return `${identity}::${workspace}`;
}

function ownerListeners(ownerKey: string): Set<JobListener> {
  let set = listenersByOwner.get(ownerKey);
  if (!set) {
    set = new Set();
    listenersByOwner.set(ownerKey, set);
  }
  return set;
}

function emitJob(ownerKey: string) {
  const job = activeJobsByOwner.get(ownerKey) || null;
  for (const listener of ownerListeners(ownerKey)) listener(job);
}

/** Runtime guard so incomplete API payloads cannot be treated as AnalyzeSummary. */
export function parseAnalyzeSummary(value: unknown): AnalyzeSummary | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  if (typeof row.analysis_id !== "string" || !row.analysis_id) return null;
  if (typeof row.total_parts !== "number" || !Number.isFinite(row.total_parts)) return null;
  if (!("health_score" in row)) return null;
  if (typeof row.health_status !== "string") return null;
  if (typeof row.high_risk_count !== "number") return null;
  if (typeof row.medium_risk_count !== "number") return null;
  if (typeof row.low_risk_count !== "number") return null;
  if (typeof row.mode !== "string") return null;
  return {
    analysis_id: row.analysis_id,
    total_parts: row.total_parts,
    health_score: (row.health_score as number | null) ?? null,
    health_status: row.health_status,
    high_risk_count: row.high_risk_count,
    medium_risk_count: row.medium_risk_count,
    low_risk_count: row.low_risk_count,
    mode: row.mode,
    project_id: typeof row.project_id === "string" ? row.project_id : undefined,
    project_name: typeof row.project_name === "string" ? row.project_name : undefined,
    bom_id: typeof row.bom_id === "string" ? row.bom_id : undefined,
    bom_name: typeof row.bom_name === "string" ? row.bom_name : undefined,
    revision: typeof row.revision === "string" ? row.revision : undefined,
    persisted: typeof row.persisted === "boolean" ? row.persisted : undefined,
    has_hierarchy: typeof row.has_hierarchy === "boolean" ? row.has_hierarchy : undefined,
    top_rolled_risk: typeof row.top_rolled_risk === "string" ? row.top_rolled_risk : undefined,
  };
}

export function getActiveAnalyzeJob(session?: JobSessionIdentity): AnalyzeJob | null {
  return activeJobsByOwner.get(identityKey(session)) || null;
}

export function subscribeAnalyzeJob(
  listener: JobListener,
  session?: JobSessionIdentity,
): () => void {
  const ownerKey = identityKey(session);
  ownerListeners(ownerKey).add(listener);
  listener(activeJobsByOwner.get(ownerKey) || null);
  return () => {
    ownerListeners(ownerKey).delete(listener);
  };
}

export function startAnalyzeJobWithRunner(
  file: { name: string },
  token: string,
  meta: { projectName?: string; bomName?: string; revision?: string },
  session: JobSessionIdentity | undefined,
  runner: AnalyzeRunner,
  onErrorPayload?: (err: unknown) => { message: string; oneTimeReportRequired?: boolean },
): AnalyzeJob {
  const ownerKey = identityKey(session);
  const existing = activeJobsByOwner.get(ownerKey);
  if (existing?.status === "running") return existing;

  const job: AnalyzeJob = {
    id: `job-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    ownerKey,
    workspaceId: session?.workspace_id,
    status: "running",
    startedAt: new Date().toISOString(),
    fileName: file.name,
    projectName: meta.projectName || "",
    bomName: meta.bomName || "",
    revision: meta.revision || "A",
  };
  activeJobsByOwner.set(ownerKey, job);
  emitJob(ownerKey);

  void runner(file, token, meta)
    .then((result) => {
      const current = activeJobsByOwner.get(ownerKey);
      if (!current || current.id !== job.id || current.ownerKey !== ownerKey) return;
      const summary = parseAnalyzeSummary(result);
      if (!summary) {
        activeJobsByOwner.set(ownerKey, {
          ...job,
          status: "failed",
          finishedAt: new Date().toISOString(),
          error: "Analyze returned an incomplete summary.",
        });
        emitJob(ownerKey);
        return;
      }
      activeJobsByOwner.set(ownerKey, {
        ...job,
        status: "succeeded",
        finishedAt: new Date().toISOString(),
        result: summary,
      });
      emitJob(ownerKey);
    })
    .catch((err) => {
      const current = activeJobsByOwner.get(ownerKey);
      if (!current || current.id !== job.id || current.ownerKey !== ownerKey) return;
      const mapped = onErrorPayload?.(err);
      activeJobsByOwner.set(ownerKey, {
        ...job,
        status: "failed",
        finishedAt: new Date().toISOString(),
        error: mapped?.message || (err instanceof Error ? err.message : "Analyze failed"),
        oneTimeReportRequired: Boolean(mapped?.oneTimeReportRequired),
      });
      emitJob(ownerKey);
    });

  return job;
}

export function clearFinishedAnalyzeJob(session?: JobSessionIdentity): void {
  const ownerKey = identityKey(session);
  const job = activeJobsByOwner.get(ownerKey);
  if (!job || job.status === "running") return;
  activeJobsByOwner.delete(ownerKey);
  emitJob(ownerKey);
}

/** Test helper: reset in-memory job state between cases. */
export function resetAnalyzeJobsForTests(): void {
  activeJobsByOwner.clear();
  listenersByOwner.clear();
}
