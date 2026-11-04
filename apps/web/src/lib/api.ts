/** Sandbox migration API only — no localhost fallback. */
const SANDBOX_API_BASE = "https://cadivor-next-api-sandbox.up.railway.app";
const API_BASE = (
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") || SANDBOX_API_BASE
).replace(/\/$/, "");
if (/localhost|127\.0\.0\.1/i.test(API_BASE)) {
  throw new Error(
    `NEXT_PUBLIC_API_BASE must target the Railway sandbox API, not localhost (got ${API_BASE})`,
  );
}

export const SMOKE_EMAIL = "auth-smoke@cadivor.test";
export const SMOKE_PASSWORD = "cadivor-auth-smoke";

export type Session = {
  access_token: string;
  email: string;
  workspace: string;
  workspace_id?: string;
  plan: string;
  mode: string;
};

export type AnalyzeSummary = {
  analysis_id: string;
  total_parts: number;
  health_score: number | null;
  health_status: string;
  high_risk_count: number;
  medium_risk_count: number;
  low_risk_count: number;
  mode: string;
  project_id?: string;
  project_name?: string;
  bom_id?: string;
  bom_name?: string;
  revision?: string;
  persisted?: boolean;
  has_hierarchy?: boolean;
  top_rolled_risk?: string;
};

export type Report = AnalyzeSummary & {
  id: string;
  filename: string;
  created_at: string;
  summary_message?: string;
  parts: Array<Record<string, unknown>>;
  hierarchy?: {
    has_hierarchy?: boolean;
    assemblies?: Array<Record<string, unknown>>;
    top_level?: Record<string, unknown>;
    priority_contributors?: Array<Record<string, unknown>>;
  } | null;
};

const SESSION_KEY = "cadivor_next_smoke_session";

async function apiJson<T>(
  path: string,
  init: RequestInit & { token?: string } = {},
): Promise<T> {
  const headers = new Headers(init.headers || {});
  if (init.token) headers.set("Authorization", `Bearer ${init.token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(detail.detail || `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export function getSession(): Session | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

export function setSession(session: Session) {
  window.localStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

export function clearSession() {
  window.localStorage.removeItem(SESSION_KEY);
}

export async function smokeLogin(email: string, password: string): Promise<Session> {
  return apiJson("/auth/smoke-login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function analyzeBom(
  file: File,
  token: string,
  meta?: { projectName?: string; bomName?: string; revision?: string },
): Promise<AnalyzeSummary> {
  const body = new FormData();
  body.append("file", file);
  if (meta?.projectName) body.append("project_name", meta.projectName);
  if (meta?.bomName) body.append("bom_name", meta.bomName);
  if (meta?.revision) body.append("revision", meta.revision);
  return apiJson("/boms/analyze", { method: "POST", token, body });
}

export async function fetchWorkspaceHome(token: string) {
  return apiJson<{
    ok: boolean;
    gap?: string;
    metrics: Record<string, number>;
    projects: Array<Record<string, unknown>>;
    recent_analyses: Array<Record<string, unknown>>;
    priority_risks: Array<Record<string, unknown>>;
    next_actions: Array<Record<string, unknown>>;
  }>("/workspace/home", { token });
}

export async function listProjects(token: string) {
  return apiJson<{
    ok: boolean;
    projects: Array<Record<string, unknown>>;
  }>("/projects", { token });
}

export async function fetchReport(analysisId: string, token: string): Promise<Report> {
  return apiJson(`/reports/${analysisId}`, { token });
}

export async function listReports(token: string) {
  return apiJson<{
    ok: boolean;
    gap?: string;
    reports: Array<Record<string, unknown>>;
  }>("/reports", { token });
}

export async function fetchMonitoring(token: string, analysisId?: string) {
  const q = analysisId ? `?analysis_id=${encodeURIComponent(analysisId)}` : "";
  return apiJson<Record<string, unknown>>(`/tools/monitoring${q}`, { token });
}

export async function compareParts(
  token: string,
  partA: string,
  partB: string,
  analysisId?: string,
) {
  return apiJson<Record<string, unknown>>("/tools/compare-parts", {
    method: "POST",
    token,
    body: JSON.stringify({
      part_a: partA,
      part_b: partB,
      analysis_id: analysisId || null,
    }),
  });
}

export async function askDatasheet(
  token: string,
  file: File,
  question: string,
) {
  const body = new FormData();
  body.append("file", file);
  body.append("question", question);
  return apiJson<Record<string, unknown>>("/tools/datasheet-qa", {
    method: "POST",
    token,
    body,
  });
}

export async function fetchProcurement(token: string, analysisId?: string) {
  const q = analysisId ? `?analysis_id=${encodeURIComponent(analysisId)}` : "";
  return apiJson<Record<string, unknown>>(`/tools/procurement${q}`, { token });
}

export async function fetchDesignImpact(
  token: string,
  opts?: { analysisId?: string; mpn?: string },
) {
  const params = new URLSearchParams();
  if (opts?.analysisId) params.set("analysis_id", opts.analysisId);
  if (opts?.mpn) params.set("mpn", opts.mpn);
  const q = params.toString() ? `?${params}` : "";
  return apiJson<Record<string, unknown>>(`/tools/design-impact${q}`, { token });
}

export async function fetchCostOptimization(
  token: string,
  opts?: { analysisId?: string; buildQuantity?: number },
) {
  const params = new URLSearchParams();
  if (opts?.analysisId) params.set("analysis_id", opts.analysisId);
  if (opts?.buildQuantity) params.set("build_quantity", String(opts.buildQuantity));
  const q = params.toString() ? `?${params}` : "";
  return apiJson<Record<string, unknown>>(`/tools/cost-optimization${q}`, { token });
}

export async function runSupplyRisk(
  token: string,
  body: Record<string, unknown>,
) {
  return apiJson<Record<string, unknown>>("/tools/supply-risk", {
    method: "POST",
    token,
    body: JSON.stringify(body),
  });
}

export async function fetchPortfolio(token: string) {
  return apiJson<Record<string, unknown>>("/tools/portfolio", { token });
}

export async function fetchDetailedRisk(token: string, analysisId?: string) {
  const q = analysisId ? `?analysis_id=${encodeURIComponent(analysisId)}` : "";
  return apiJson<Record<string, unknown>>(`/tools/detailed-risk${q}`, { token });
}

export { API_BASE };
