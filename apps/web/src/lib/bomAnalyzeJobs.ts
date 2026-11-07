/** In-memory analyze jobs scoped by authenticated owner identity. */

export type AnalyzeJobStatus = "idle" | "running" | "succeeded" | "failed";

export type AnalyzeJobResult = {
  analysis_id: string;
  total_parts?: number;
  [key: string]: unknown;
};

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

export function identityKey(session?: JobSessionIdentity): string {
  const identity = session?.user_id || session?.email?.trim().toLowerCase();
  return identity || "anonymous";
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
      activeJobsByOwner.set(ownerKey, {
        ...job,
        status: "succeeded",
        finishedAt: new Date().toISOString(),
        result,
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
