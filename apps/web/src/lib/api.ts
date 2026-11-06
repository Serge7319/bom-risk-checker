import { getSupabaseBrowserClient } from "@/lib/supabase";

/** The deployed web service must set its matching API endpoint explicitly. */
const API_BASE = (process.env.NEXT_PUBLIC_API_BASE || "").trim().replace(/\/$/, "");

/** Local API hosts are blocked in production builds; allow only for explicit local/dev use. */
function allowLocalApiBase(): boolean {
  if (process.env.NODE_ENV === "development") return true;
  return (process.env.NEXT_PUBLIC_ALLOW_LOCAL_API || "").trim() === "1";
}

function assertApiBaseConfigured(): void {
  if (!API_BASE) {
    throw new Error("Cadivor could not connect. Refresh the page or contact support.");
  }
  const isLocal = /localhost|127\.0\.0\.1/i.test(API_BASE);
  if (isLocal && !allowLocalApiBase()) {
    throw new Error("Cadivor could not connect. Refresh the page or contact support.");
  }
}

export type Session = {
  access_token: string;
  /** Used once to seed Supabase JS; never copied to Cadivor's session record. */
  refresh_token?: string;
  email: string;
  workspace: string;
  workspace_id?: string;
  user_id?: string;
  plan: string;
  mode: string;
  trial_started_at?: string;
  trial_ends_at?: string;
  trial_status?: string;
  trial_days_remaining?: number;
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

const SESSION_KEY = "cadivor_next_session";
const LEGACY_SESSION_KEY = "cadivor_next_sandbox_session";
let refreshInFlight: Promise<string | null> | null = null;

function sessionMatchesSupabaseUser(
  appSession: Session | null,
  authUser: { id: string; email?: string | null } | null | undefined,
): boolean {
  if (!appSession || !authUser) return false;
  if (appSession.user_id) return appSession.user_id === authUser.id;
  return Boolean(
    appSession.email &&
      authUser.email &&
      appSession.email.trim().toLowerCase() === authUser.email.trim().toLowerCase(),
  );
}

function persistAccessToken(accessToken: string) {
  const current = getSession();
  if (!current || typeof window === "undefined") return;
  window.localStorage.setItem(
    SESSION_KEY,
    JSON.stringify({ ...current, access_token: accessToken }),
  );
}

async function refreshSupabaseAccessToken(): Promise<string | null> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const client = getSupabaseBrowserClient();
        const appSession = getSession();
        if (!client || !appSession) return null;

        const { data: current, error: currentError } = await client.auth.getSession();
        if (
          currentError ||
          !current.session ||
          !sessionMatchesSupabaseUser(appSession, current.session.user)
        ) {
          return null;
        }

        const { data, error } = await client.auth.refreshSession();
        if (
          error ||
          !data.session ||
          !sessionMatchesSupabaseUser(appSession, data.session.user)
        ) {
          return null;
        }

        persistAccessToken(data.session.access_token);
        return data.session.access_token;
      } catch {
        return null;
      }
    })().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

async function currentSupabaseAccessToken(fallback: string): Promise<string> {
  try {
    const client = getSupabaseBrowserClient();
    const appSession = getSession();
    if (!client || !appSession) return fallback;

    const { data, error } = await client.auth.getSession();
    const authSession = data.session;
    if (error || !authSession || !sessionMatchesSupabaseUser(appSession, authSession.user)) {
      return fallback;
    }

    const expiresSoon =
      authSession.expires_at != null &&
      authSession.expires_at <= Math.floor(Date.now() / 1000) + 45;
    if (expiresSoon) {
      return (await refreshSupabaseAccessToken()) || fallback;
    }

    persistAccessToken(authSession.access_token);
    return authSession.access_token;
  } catch {
    return fallback;
  }
}

function redirectToLoginAfterAuthFailure() {
  if (typeof window === "undefined") return;
  clearSession();
  if (!window.location.pathname.startsWith("/login")) {
    window.location.assign("/login?reason=session-refresh");
  }
}

async function apiJson<T>(
  path: string,
  init: RequestInit & { token?: string } = {},
): Promise<T> {
  assertApiBaseConfigured();
  const { token: initialToken, ...requestInit } = init;
  const send = (token?: string) => {
    const headers = new Headers(requestInit.headers || {});
    if (token) headers.set("Authorization", `Bearer ${token}`);
    if (
      requestInit.body &&
      !(requestInit.body instanceof FormData) &&
      !headers.has("Content-Type")
    ) {
      headers.set("Content-Type", "application/json");
    }
    return fetch(`${API_BASE}${path}`, { ...requestInit, headers });
  };

  const token = initialToken
    ? await currentSupabaseAccessToken(initialToken)
    : undefined;
  let res = await send(token);
  if (!res.ok) {
    if (res.status === 401 && initialToken) {
      const refreshedToken = await refreshSupabaseAccessToken();
      if (refreshedToken && refreshedToken !== token) {
        res = await send(refreshedToken);
      }
      if (res.status === 401) {
        redirectToLoginAfterAuthFailure();
      }
    }
  }
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(detail.detail || `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export function getSession(): Session | null {
  if (typeof window === "undefined") return null;
  try {
    const raw =
      window.localStorage.getItem(SESSION_KEY) ||
      window.localStorage.getItem(LEGACY_SESSION_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

export async function setSession(session: Session): Promise<void> {
  let storedSession = session;
  const client = getSupabaseBrowserClient();
  if (client && !session.refresh_token) {
    throw new Error("Sign-in did not return a refresh session. Please try again or contact support.");
  }
  if (client) {
    const { data, error } = await client.auth.setSession({
      access_token: session.access_token,
      refresh_token: session.refresh_token as string,
    });
    if (error || !data.session) {
      void client.auth.signOut({ scope: "local" }).catch(() => undefined);
      throw new Error("Sign-in succeeded, but Cadivor could not keep the session active. Please sign in again.");
    }
    storedSession = { ...session, access_token: data.session.access_token };
  }
  const safeSession = { ...storedSession };
  delete safeSession.refresh_token;
  window.localStorage.setItem(SESSION_KEY, JSON.stringify(safeSession));
  window.localStorage.removeItem(LEGACY_SESSION_KEY);
}

export function clearSession() {
  window.localStorage.removeItem(SESSION_KEY);
  window.localStorage.removeItem(LEGACY_SESSION_KEY);
  const client = getSupabaseBrowserClient();
  if (client) void client.auth.signOut({ scope: "local" }).catch(() => undefined);
}

export async function login(email: string, password: string): Promise<Session> {
  return apiJson<Session>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function fetchAuthConfig() {
  return apiJson<{ signup_enabled: boolean; trial_length_days: number }>("/auth/config");
}

export async function signup(
  email: string,
  password: string,
  workspaceName: string,
  captchaToken?: string,
) {
  return apiJson<{ accepted: boolean; message: string }>("/auth/signup", {
    method: "POST",
    body: JSON.stringify({
      email,
      password,
      workspace_name: workspaceName,
      captcha_token: captchaToken,
    }),
  });
}

export async function logout(token: string): Promise<void> {
  await apiJson("/auth/logout", { method: "POST", token });
}

export async function fetchMe(token: string) {
  return apiJson<{
    ok: boolean;
    email: string;
    user_id: string;
    workspace: string;
    workspace_id: string;
    plan: string;
    mode: string;
    client_workspace_id_trusted: boolean;
    trial_started_at?: string;
    trial_ends_at?: string;
    trial_status?: string;
    trial_days_remaining?: number;
  }>("/auth/me", { token });
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
    persistence?: string;
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

export async function findReplacement(
  token: string,
  body: { mpn: string; manufacturer?: string; analysis_id?: string | null },
) {
  return apiJson<Record<string, unknown>>("/tools/find-replacement", {
    method: "POST",
    token,
    body: JSON.stringify(body),
  });
}

export async function askCadivor(
  token: string,
  body: {
    analysis_id: string;
    question: string;
    history?: Array<{ role: string; content: string }>;
  },
) {
  return apiJson<Record<string, unknown>>("/tools/ask-cadivor", {
    method: "POST",
    token,
    body: JSON.stringify(body),
  });
}

export async function fetchPlanUsage(token: string) {
  return apiJson<Record<string, unknown>>("/plan/usage", { token });
}

export async function fetchBillingStatus(token: string) {
  return apiJson<Record<string, unknown>>("/billing/status", { token });
}

export async function fetchConnectors(token: string) {
  return apiJson<Record<string, unknown>>("/integrations/connectors", { token });
}

export async function fetchCompliancePack(token: string, packType: string) {
  return apiJson<Record<string, unknown>>(
    `/compliance/${encodeURIComponent(packType)}`,
    { token },
  );
}
