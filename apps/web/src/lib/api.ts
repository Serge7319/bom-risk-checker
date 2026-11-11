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
  evidence_summary?: {
    live_count?: number;
    synthetic_count?: number;
    missing_count?: number;
    live_lookups_enabled?: boolean;
  };
  hierarchy?: {
    has_hierarchy?: boolean;
    assemblies?: Array<Record<string, unknown>>;
    top_level?: Record<string, unknown>;
    priority_contributors?: Array<Record<string, unknown>>;
  } | null;
};

export class ApiError extends Error {
  status: number;
  payload: Record<string, unknown>;

  constructor(message: string, status: number, payload: Record<string, unknown>) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

export type OneTimeReportOrder = {
  id: string;
  status: string;
  created_at?: string | null;
  paid_at?: string | null;
  analysis_id?: string | null;
};

export type OneTimeReportStatus = {
  ok: boolean;
  enabled: boolean;
  price?: { amount: number; currency: string };
  available_credit: boolean;
  analysis_in_progress: boolean;
  checkout?: { state: string; url?: string } | null;
  orders: OneTimeReportOrder[];
  max_components: number;
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
    const payload = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    const detail = typeof payload.detail === "string" ? payload.detail : `Request failed (${res.status})`;
    throw new ApiError(detail, res.status, payload);
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

export async function downloadReportCsv(analysisId: string, initialToken: string): Promise<void> {
  assertApiBaseConfigured();
  const send = (token: string) =>
    fetch(`${API_BASE}/reports/${encodeURIComponent(analysisId)}/export.csv`, {
      headers: { Authorization: `Bearer ${token}` },
    });

  let token = await currentSupabaseAccessToken(initialToken);
  let response = await send(token);
  if (response.status === 401) {
    const refreshedToken = await refreshSupabaseAccessToken();
    if (refreshedToken && refreshedToken !== token) {
      token = refreshedToken;
      response = await send(token);
    }
    if (response.status === 401) redirectToLoginAfterAuthFailure();
  }
  if (!response.ok) {
    const detail = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(detail.detail || `Request failed (${response.status})`);
  }

  const blob = await response.blob();
  const objectUrl = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = "cadivor-report.csv";
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => window.URL.revokeObjectURL(objectUrl), 1000);
}

export async function fetchAuthConfig() {
  return apiJson<{
    signup_enabled: boolean;
    trial_length_days: number;
    invitations_enabled?: boolean;
  }>("/auth/config");
}

export async function lookupInvitation(token: string) {
  return apiJson<{
    email: string;
    workspace_name: string;
    role: string;
    expires_at?: string;
    invited_by_name?: string;
  }>(`/invitations/lookup?token=${encodeURIComponent(token)}`);
}

export async function registerFromInvitation(body: {
  token: string;
  email: string;
  password: string;
  accepted_terms: boolean;
  terms_version?: string;
  privacy_version?: string;
}) {
  return apiJson<{
    ok: boolean;
    email: string;
    user_id?: string;
    message?: string;
    accepted?: Array<Record<string, unknown>>;
  }>("/invitations/register", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function signup(
  email: string,
  password: string,
  workspaceName: string,
  captchaToken?: string,
  acceptedTerms = false,
  versions?: { terms_version?: string; privacy_version?: string },
) {
  return apiJson<{ accepted: boolean; message: string }>("/auth/signup", {
    method: "POST",
    body: JSON.stringify({
      email,
      password,
      workspace_name: workspaceName,
      captcha_token: captchaToken,
      accepted_terms: acceptedTerms,
      terms_version: versions?.terms_version,
      privacy_version: versions?.privacy_version,
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

export type BomValidationPreview = {
  ok: boolean;
  can_analyze: boolean;
  filename: string;
  detected_columns: Array<{ source: string; normalized: string }>;
  required_columns: string[];
  missing_required: string[];
  row_count: number;
  unique_part_count: number;
  errors: string[];
  warnings: string[];
  has_hierarchy_columns?: boolean;
  workspace_id?: string;
};

export async function validateBom(
  file: File,
  token: string,
): Promise<BomValidationPreview> {
  const body = new FormData();
  body.append("file", file);
  return apiJson("/boms/validate", { method: "POST", token, body });
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

export type ReportExportFormat = "pdf" | "csv" | "xlsx";

export async function downloadReportExport(
  analysisId: string,
  token: string,
  format: ReportExportFormat,
): Promise<void> {
  assertApiBaseConfigured();
  const path = `/reports/${encodeURIComponent(analysisId)}/export/${format}`;
  const send = (accessToken: string) =>
    fetch(`${API_BASE}${path}`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });

  const activeToken = await currentSupabaseAccessToken(token);
  let response = await send(activeToken);
  if (response.status === 401) {
    const refreshedToken = await refreshSupabaseAccessToken();
    if (refreshedToken && refreshedToken !== activeToken) {
      response = await send(refreshedToken);
    }
    if (response.status === 401) redirectToLoginAfterAuthFailure();
  }
  if (!response.ok) {
    const detail = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(detail.detail || `Report download failed (${response.status})`);
  }

  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") || "";
  const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] || `cadivor-report.${format}`;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function listReports(token: string) {
  return apiJson<{
    ok: boolean;
    gap?: string;
    persistence?: string;
    reports: Array<Record<string, unknown>>;
  }>("/reports", { token });
}

export type DecisionRecord = {
  id: string;
  decision_id: string;
  analysis_id?: string | null;
  project_name?: string | null;
  bom_name?: string | null;
  revision?: string | null;
  part_a: string;
  part_b: string;
  decision: string;
  decision_label: string;
  reviewer: string;
  rationale: string;
  validation_checks?: string[];
  follow_up_action?: string;
  follow_up_owner?: string;
  follow_up_due_date?: string | null;
  residual_risk?: string;
  verified_primary_evidence?: boolean;
  qualification_status: string;
  qualification_note: string;
  created_at: string;
  comparison_snapshot: Record<string, unknown>;
};

export async function listDecisionRecords(token: string, analysisId?: string) {
  const query = analysisId ? `?analysis_id=${encodeURIComponent(analysisId)}` : "";
  return apiJson<{ ok: boolean; records: DecisionRecord[] }>(
    `/decision-records${query}`,
    { token },
  );
}

export async function recordDecision(
  token: string,
  payload: {
    analysis_id?: string | null;
    part_a: string;
    part_b: string;
    decision: string;
    reviewer: string;
    rationale: string;
    validation_checks?: string[];
    follow_up_action?: string;
    follow_up_owner?: string;
    follow_up_due_date?: string | null;
    residual_risk?: string;
    verified_primary_evidence?: boolean;
    comparison_snapshot?: Record<string, unknown> | null;
  },
  datasheets?: { a?: File | null; b?: File | null },
) {
  const body = datasheets?.a || datasheets?.b ? new FormData() : null;
  if (body) {
    for (const [key, value] of Object.entries(payload)) {
      if (value === undefined || value === null) continue;
      body.append(
        key,
        typeof value === "object" ? JSON.stringify(value) : Array.isArray(value) ? JSON.stringify(value) : String(value),
      );
    }
    if (datasheets?.a) body.append("datasheet_a", datasheets.a);
    if (datasheets?.b) body.append("datasheet_b", datasheets.b);
  }
  return apiJson<{ ok: boolean; record: DecisionRecord }>("/decision-records", {
    method: "POST",
    token,
    body: body || JSON.stringify(payload),
  });
}

export async function fetchMonitoring(token: string, analysisId?: string) {
  const q = analysisId ? `?analysis_id=${encodeURIComponent(analysisId)}` : "";
  return apiJson<Record<string, unknown>>(`/tools/monitoring${q}`, { token });
}

/** Default client bound for one pairwise compare (progress + fail-closed). */
export const COMPARE_PARTS_TIMEOUT_MS = 60_000;

export async function compareParts(
  token: string,
  partA: string,
  partB: string,
  analysisId?: string,
  datasheets?: { a?: File | null; b?: File | null },
  options?: { signal?: AbortSignal; timeoutMs?: number },
) {
  const body = datasheets?.a || datasheets?.b ? new FormData() : null;
  if (body) {
    body.append("part_a", partA);
    body.append("part_b", partB);
    body.append("analysis_id", analysisId || "");
    if (datasheets?.a) body.append("datasheet_a", datasheets.a);
    if (datasheets?.b) body.append("datasheet_b", datasheets.b);
  }
  const timeoutMs = options?.timeoutMs ?? COMPARE_PARTS_TIMEOUT_MS;
  const controller = new AbortController();
  const onAbort = () => controller.abort();
  if (options?.signal) {
    if (options.signal.aborted) controller.abort();
    else options.signal.addEventListener("abort", onAbort, { once: true });
  }
  const timer =
    timeoutMs > 0
      ? setTimeout(() => controller.abort(), timeoutMs)
      : null;
  try {
    return await apiJson<Record<string, unknown>>("/tools/compare-parts", {
      method: "POST",
      token,
      signal: controller.signal,
      body: body || JSON.stringify({
        part_a: partA,
        part_b: partB,
        analysis_id: analysisId || null,
      }),
    });
  } catch (err) {
    if (controller.signal.aborted) {
      throw new Error(
        `Comparison timed out after ${Math.round(timeoutMs / 1000)}s for ${partA} vs ${partB}. This is not a fit verdict and does not mean there are no candidates.`,
      );
    }
    throw err;
  } finally {
    if (timer) clearTimeout(timer);
    if (options?.signal) options.signal.removeEventListener("abort", onAbort);
  }
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

export async function beginSubscriptionCheckout(token: string, plan: string) {
  return apiJson<{
    ok: boolean;
    checkout?: { state: string; url?: string };
    code?: string;
    detail?: string;
  }>("/billing/checkout", {
    method: "POST",
    token,
    body: JSON.stringify({ plan }),
  });
}

export async function beginBillingPortal(token: string) {
  return apiJson<{
    ok: boolean;
    checkout?: { state: string; url?: string };
    code?: string;
    detail?: string;
  }>("/billing/portal", {
    method: "POST",
    token,
    body: JSON.stringify({}),
  });
}

export async function fetchOneTimeReportStatus(token: string) {
  return apiJson<OneTimeReportStatus>("/billing/one-time-report", { token });
}

export async function beginOneTimeReportCheckout(token: string) {
  return apiJson<{
    ok: boolean;
    checkout?: { state: string; url?: string };
    detail?: string;
  }>("/billing/one-time-report/checkout", {
    method: "POST",
    token,
    body: JSON.stringify({}),
  });
}

export async function fetchConnectors(token: string) {
  return apiJson<Record<string, unknown>>("/integrations/connectors", { token });
}

export type ServiceReadiness = {
  ok?: boolean;
  monitoring_email?: { status?: string; enabled?: boolean };
  scheduler?: {
    status?: string;
    enabled?: boolean;
    cron_token_configured?: boolean;
  };
  connectors?: {
    status?: string;
    ready_count?: number;
    live_ready_count?: number;
    file_workflow_count?: number;
    blocked_count?: number;
    connectors?: Array<Record<string, unknown>>;
    gap?: string | null;
  };
  billing_checkout?: { status?: string; enabled?: boolean };
  detail?: string;
};

export async function fetchServiceReadiness(token: string) {
  return apiJson<ServiceReadiness>("/integrations/service-readiness", { token });
}

export async function fetchCompliancePack(token: string, packType: string) {
  return apiJson<Record<string, unknown>>(
    `/compliance/${encodeURIComponent(packType)}`,
    { token },
  );
}

export async function fetchProfile(token: string) {
  return apiJson<Record<string, unknown>>("/settings/profile", { token });
}

export async function updateProfile(token: string, body: Record<string, unknown>) {
  return apiJson<Record<string, unknown>>("/settings/profile", {
    method: "PATCH",
    token,
    body: JSON.stringify(body),
  });
}

export async function fetchPreferences(token: string) {
  return apiJson<Record<string, unknown>>("/settings/preferences", { token });
}

export async function updatePreferences(token: string, body: Record<string, unknown>) {
  return apiJson<Record<string, unknown>>("/settings/preferences", {
    method: "PATCH",
    token,
    body: JSON.stringify(body),
  });
}

export async function fetchSecurityStatus(token: string) {
  return apiJson<Record<string, unknown>>("/settings/security", { token });
}

export async function requestPasswordReset(email: string) {
  return apiJson<{ ok?: boolean; accepted?: boolean; message?: string }>(
    "/auth/password-reset",
    { method: "POST", body: JSON.stringify({ email }) },
  );
}

export async function completePasswordReset(
  accessToken: string,
  password: string,
) {
  return apiJson<{ ok?: boolean; message?: string }>(
    "/auth/password-reset/complete",
    {
      method: "POST",
      body: JSON.stringify({ access_token: accessToken, password }),
    },
  );
}

export async function changePassword(
  token: string,
  body: { current_password: string; new_password: string },
) {
  return apiJson<{ ok?: boolean; detail?: string }>("/auth/password", {
    method: "POST",
    token,
    body: JSON.stringify(body),
  });
}

export async function revokeOtherSessions(token: string) {
  return apiJson<{ ok?: boolean }>("/auth/sessions/revoke-others", {
    method: "POST",
    token,
    body: JSON.stringify({}),
  });
}

export async function listWorkspaces(token: string) {
  return apiJson<Record<string, unknown>>("/workspaces", { token });
}

export async function createWorkspace(token: string, name: string) {
  return apiJson<Record<string, unknown>>("/workspaces", {
    method: "POST",
    token,
    body: JSON.stringify({ name }),
  });
}

export async function switchWorkspace(token: string, workspaceId: string) {
  return apiJson<Record<string, unknown>>("/workspaces/active", {
    method: "POST",
    token,
    body: JSON.stringify({ workspace_id: workspaceId }),
  });
}

export async function fetchWorkspaceSettings(token: string) {
  return apiJson<Record<string, unknown>>("/workspace/settings", { token });
}

export async function updateWorkspaceSettings(
  token: string,
  body: Record<string, unknown>,
) {
  return apiJson<Record<string, unknown>>("/workspace/settings", {
    method: "PATCH",
    token,
    body: JSON.stringify(body),
  });
}

export async function listWorkspaceMembers(token: string) {
  return apiJson<Record<string, unknown>>("/workspace/members", { token });
}

export async function listWorkspaceInvitations(token: string) {
  return apiJson<Record<string, unknown>>("/workspace/invitations", { token });
}

export async function createWorkspaceInvitation(
  token: string,
  body: { email: string; role: string; expires_in_days?: number },
) {
  return apiJson<Record<string, unknown>>("/workspace/invitations", {
    method: "POST",
    token,
    body: JSON.stringify(body),
  });
}

export async function resendWorkspaceInvitation(token: string, inviteId: string) {
  return apiJson<Record<string, unknown>>(
    `/workspace/invitations/${encodeURIComponent(inviteId)}/resend`,
    { method: "POST", token, body: JSON.stringify({}) },
  );
}

export async function cancelWorkspaceInvitation(token: string, inviteId: string) {
  return apiJson<Record<string, unknown>>(
    `/workspace/invitations/${encodeURIComponent(inviteId)}`,
    { method: "DELETE", token },
  );
}

export async function listWorkspaceActivity(token: string, limit = 40) {
  return apiJson<Record<string, unknown>>(
    `/workspace/activity?limit=${encodeURIComponent(String(limit))}`,
    { token },
  );
}
