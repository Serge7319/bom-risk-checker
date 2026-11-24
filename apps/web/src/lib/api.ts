import { getSupabaseBrowserClient } from "@/lib/supabase";
import { userFacingError } from "@/lib/display";

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
  platform_role?: string;
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
  assessment_coverage?: number | null;
  needs_verification_count?: number;
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
  derived_from_analysis_id?: string;
  applied_decision_ids?: string[];
  used_decision_ids?: string[];
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
    unverified_count?: number;
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
    super(userFacingError(message, "The request could not be completed."));
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

export const SESSION_KEY = "cadivor_next_session";
export const LEGACY_SESSION_KEY = "cadivor_next_sandbox_session";
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

function tokenBelongsToSession(token: string, session: Session): boolean {
  try {
    const segment = token.split(".")[1];
    if (!segment) return true;
    const base64 = segment.replace(/-/g, "+").replace(/_/g, "/");
    const payload = JSON.parse(atob(base64.padEnd(Math.ceil(base64.length / 4) * 4, "="))) as {
      sub?: string;
    };
    return !session.user_id || !payload.sub || session.user_id === payload.sub;
  } catch {
    return true;
  }
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
    if (!tokenBelongsToSession(fallback, appSession)) {
      throw new ApiError(
        "Your Cadivor account changed in another tab. Refresh this page before continuing.",
        409,
        { code: "session_account_mismatch" },
      );
    }

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
  } catch (error) {
    if (error instanceof ApiError) throw error;
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
    throw new Error(userFacingError(detail.detail, `Request failed (${response.status})`));
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
  marketingAttribution?: Record<string, string>,
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
      marketing_attribution: marketingAttribution,
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
    platform_role?: string;
    client_workspace_id_trusted: boolean;
    trial_started_at?: string;
    trial_ends_at?: string;
    trial_status?: string;
    trial_days_remaining?: number;
  }>("/auth/me", { token });
}

export type BomIntakeSeverity = "error" | "warning" | "info";

export type BomIntakeIssue = {
  code: string;
  severity: BomIntakeSeverity;
  message: string;
  field?: string | null;
};

/** A column role the user can assign. `requirement` drives the UI wording. */
export type BomIntakeField = {
  id: string;
  label: string;
  requirement: "required" | "recommended" | "supplier_specific" | "optional";
  help: string;
};

export type BomIntakeColumn = {
  index: number;
  source: string;
  suggested_field: string | null;
  assigned_field: string;
  /** recognized | confirm | choose | not-used | supplier-export | user */
  confidence: string;
  candidates: string[];
  note: string;
  sample: string[];
};

export type BomIntakeRow = {
  row_number: number;
  status: "ok" | "warning" | "error" | "excluded";
  /** Values exactly as uploaded, keyed by column role. */
  raw: Record<string, string>;
  /** Values that will be used for analysis. */
  normalized: Record<string, string | number | null>;
  source: Record<string, string>;
  corrections?: Record<string, { original: string; corrected: string }>;
  issues: BomIntakeIssue[];
};

/** The user's explicit intake choices. Nothing here is ever inferred. */
export type BomIntakeOptions = {
  /** Zero-based column index -> role id, or "ignore". null = use detected mapping. */
  columnMapping: Record<string, string> | null;
  /** Spreadsheet row number -> corrected values by role id. */
  rowCorrections: Record<string, Record<string, string>>;
  supplierSpecific: boolean;
  defaultSupplier: string;
  excludeInvalidRows: boolean;
};

export const DEFAULT_BOM_INTAKE_OPTIONS: BomIntakeOptions = {
  columnMapping: null,
  rowCorrections: {},
  supplierSpecific: false,
  defaultSupplier: "",
  excludeInvalidRows: false,
};

export type BomValidationPreview = {
  ok: boolean;
  can_analyze: boolean;
  filename: string;
  detected_columns: Array<{ source: string; normalized: string }>;
  required_columns: string[];
  missing_required: string[];
  row_count: number;
  unique_part_count: number;
  parsed_row_count?: number;
  errors: string[];
  warnings: string[];
  has_hierarchy_columns?: boolean;
  workspace_id?: string;
  // Intake review (absent on drafts saved before the intake review existed).
  format?: string;
  sheet?: string;
  header_row?: number;
  supplier_profile?: { id: string; label: string; evidence: string[] };
  fields?: BomIntakeField[];
  columns?: BomIntakeColumn[];
  applied_mapping?: Record<string, string>;
  mapping_source?: "auto" | "user";
  rows?: BomIntakeRow[];
  rows_total?: number;
  rows_shown?: number;
  rows_truncated?: boolean;
  issues?: BomIntakeIssue[];
  counts?: Record<string, number>;
  supplier_specific?: boolean;
  default_supplier?: string;
  exclude_invalid_rows?: boolean;
  corrections_applied?: number;
  blank_rows_skipped?: number;
};

/** Send only the choices the user actually made. */
function appendIntakeOptions(body: FormData, options?: BomIntakeOptions) {
  if (!options) return;
  if (options.columnMapping) {
    body.append("column_mapping", JSON.stringify(options.columnMapping));
  }
  if (Object.keys(options.rowCorrections).length) {
    body.append("row_corrections", JSON.stringify(options.rowCorrections));
  }
  if (options.supplierSpecific) {
    body.append("supplier_specific", "true");
    if (options.defaultSupplier.trim()) {
      body.append("default_supplier", options.defaultSupplier.trim());
    }
  }
  if (options.excludeInvalidRows) body.append("exclude_invalid_rows", "true");
}

export async function validateBom(
  file: File,
  token: string,
  options?: BomIntakeOptions,
): Promise<BomValidationPreview> {
  const body = new FormData();
  body.append("file", file);
  appendIntakeOptions(body, options);
  return apiJson("/boms/validate", { method: "POST", token, body });
}

export async function analyzeBom(
  file: File,
  token: string,
  meta?: {
    projectName?: string;
    bomName?: string;
    revision?: string;
    sourceAnalysisId?: string;
    appliedDecisionIds?: string[];
    usedDecisionIds?: string[];
    intake?: BomIntakeOptions;
  },
): Promise<AnalyzeSummary> {
  const body = new FormData();
  body.append("file", file);
  if (meta?.projectName) body.append("project_name", meta.projectName);
  if (meta?.bomName) body.append("bom_name", meta.bomName);
  if (meta?.revision) body.append("revision", meta.revision);
  if (meta?.sourceAnalysisId) body.append("source_analysis_id", meta.sourceAnalysisId);
  if (meta?.appliedDecisionIds?.length) {
    body.append("applied_decision_ids", JSON.stringify(meta.appliedDecisionIds));
  }
  if (meta?.usedDecisionIds?.length) {
    body.append("used_decision_ids", JSON.stringify(meta.usedDecisionIds));
  }
  appendIntakeOptions(body, meta?.intake);
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
    priority_severity_counts?: Record<string, number>;
    next_actions: Array<Record<string, unknown>>;
  }>("/workspace/home", { token });
}

export async function fetchWorkspacePriorityQueue(token: string, offset = 0) {
  const query = new URLSearchParams({ offset: String(Math.max(0, offset)) });
  return apiJson<{
    ok: boolean;
    items: Array<Record<string, unknown>>;
    reports_total: number;
    reports_loaded: number;
    reports_scanned: number;
    next_offset: number;
    has_more: boolean;
  }>(`/workspace/priority-queue?${query.toString()}`, { token });
}

export async function listProjects(token: string) {
  return apiJson<{
    ok: boolean;
    projects: Array<Record<string, unknown>>;
  }>("/projects", { token });
}

export async function renameProject(token: string, projectId: string, name: string) {
  return apiJson<{ ok: boolean; project: Record<string, unknown> }>(
    `/projects/${encodeURIComponent(projectId)}`,
    { method: "PATCH", token, body: JSON.stringify({ name }) },
  );
}

export async function renameBom(
  token: string,
  bomId: string,
  name: string,
  projectId?: string,
) {
  return apiJson<{ ok: boolean; bom: Record<string, unknown> }>(
    `/boms/${encodeURIComponent(bomId)}`,
    {
      method: "PATCH",
      token,
      body: JSON.stringify({ name, ...(projectId ? { project_id: projectId } : {}) }),
    },
  );
}

export async function moveBom(token: string, bomId: string, projectId: string) {
  return apiJson<{ ok: boolean; bom: Record<string, unknown> }>(
    `/boms/${encodeURIComponent(bomId)}`,
    { method: "PATCH", token, body: JSON.stringify({ project_id: projectId }) },
  );
}

export async function deleteBom(token: string, bomId: string) {
  return apiJson<{
    ok: boolean;
    deleted: string;
    deleted_analysis_count: number;
  }>(`/boms/${encodeURIComponent(bomId)}`, { method: "DELETE", token });
}

export async function fetchReport(analysisId: string, token: string): Promise<Report> {
  return apiJson(`/reports/${analysisId}`, { token });
}

export type ReportExportFormat = "pdf" | "csv" | "xlsx" | "plm-csv";

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
    throw new Error(userFacingError(detail.detail, `Report download failed (${response.status})`));
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

async function downloadAuthenticatedCsv(path: string, token: string, fallbackName: string): Promise<void> {
  assertApiBaseConfigured();
  const send = (accessToken: string) => fetch(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  const activeToken = await currentSupabaseAccessToken(token);
  let response = await send(activeToken);
  if (response.status === 401) {
    const refreshedToken = await refreshSupabaseAccessToken();
    if (refreshedToken && refreshedToken !== activeToken) response = await send(refreshedToken);
    if (response.status === 401) redirectToLoginAfterAuthFailure();
  }
  if (!response.ok) {
    const detail = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(userFacingError(detail.detail, `CSV download failed (${response.status})`));
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") || "";
  const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] || fallbackName;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export type DecisionRecordExportTemplate = "medical-device" | "aerospace";

export async function downloadDecisionRecordExport(
  token: string,
  template: DecisionRecordExportTemplate,
  analysisId?: string,
): Promise<void> {
  const query = analysisId ? `?analysis_id=${encodeURIComponent(analysisId)}` : "";
  await downloadAuthenticatedCsv(
    `/decision-records/export/${template}${query}`,
    token,
    `cadivor-${template}-decision-draft.csv`,
  );
}

export async function downloadWorkspaceActivityExport(token: string): Promise<void> {
  await downloadAuthenticatedCsv(
    "/workspace/activity/export.csv",
    token,
    "cadivor-workspace-activity.csv",
  );
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
  decision_candidate_scope?: "primary" | "all_selected";
  decision_candidate_mpns?: string[];
  manufacturer_a?: string | null;
  manufacturer_b?: string | null;
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

export type DecisionCandidate = {
  mpn: string;
  manufacturer?: string;
};

export function getDecisionCandidates(
  record: Partial<DecisionRecord> | null | undefined,
): DecisionCandidate[] {
  const snapshot = record?.comparison_snapshot && typeof record.comparison_snapshot === "object"
    ? record.comparison_snapshot
    : {};
  const manufacturers = snapshot.multi_candidate_manufacturers
    && typeof snapshot.multi_candidate_manufacturers === "object"
    ? snapshot.multi_candidate_manufacturers as Record<string, unknown>
    : {};
  const explicitlySelected = Array.isArray(record?.decision_candidate_mpns)
    ? record.decision_candidate_mpns
    : [];
  const listed = record?.decision_candidate_scope === "all_selected"
    ? (explicitlySelected.length ? explicitlySelected : Array.isArray(snapshot.multi_candidate_mpns) ? snapshot.multi_candidate_mpns : [])
    : [];
  const seen = new Set<string>();
  const mpns = listed
    .map((value) => String(value || "").trim())
    .filter((mpn) => {
      const key = mpn.toLowerCase();
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  if (!mpns.length && String(record?.part_b || "").trim()) {
    mpns.push(String(record?.part_b || "").trim());
  }
  return mpns.map((mpn) => ({
    mpn,
    manufacturer: String(manufacturers[mpn] || (
      mpn.toLowerCase() === String(record?.part_b || "").trim().toLowerCase()
        ? record?.manufacturer_b
        : ""
    ) || "").trim() || undefined,
  }));
}

export async function listDecisionRecords(token: string, analysisId?: string) {
  const query = analysisId ? `?analysis_id=${encodeURIComponent(analysisId)}` : "";
  return apiJson<{ ok: boolean; records: DecisionRecord[] }>(
    `/decision-records${query}`,
    { token },
  );
}

export async function createDecisionRecordShare(token: string, decisionRecordId: string) {
  return apiJson<{ ok: boolean; token: string; expires_at: string }>(
    "/decision-records/share",
    {
      method: "POST",
      token,
      body: JSON.stringify({ decision_record_id: decisionRecordId }),
    },
  );
}

export async function inviteDecisionApprover(
  token: string,
  decisionRecordId: string,
  email: string,
) {
  return apiJson<{ ok: boolean; sent: boolean; expires_at: string }>(
    "/decision-records/approvers",
    {
      method: "POST",
      token,
      body: JSON.stringify({ decision_record_id: decisionRecordId, email }),
    },
  );
}

export async function fetchDecisionApproval(token: string) {
  return apiJson<{
    ok: boolean;
    record: Partial<DecisionRecord>;
    status: string;
    response_rationale?: string | null;
    expires_at: string;
  }>(`/decision-approvals/${encodeURIComponent(token)}`, { cache: "no-store" });
}

export async function respondToDecisionApproval(
  token: string,
  decision: "approved" | "rejected",
  rationale: string,
) {
  return apiJson<{ ok: boolean; status: string }>(
    `/decision-approvals/${encodeURIComponent(token)}/respond`,
    {
      method: "POST",
      body: JSON.stringify({ decision, rationale }),
    },
  );
}

export async function fetchSharedDecisionRecord(shareToken: string) {
  return apiJson<{
    ok: boolean;
    record: Partial<DecisionRecord>;
    expires_at: string;
  }>(`/decision-records/share/${encodeURIComponent(shareToken)}`, {
    cache: "no-store",
  });
}

export async function recordDecision(
  token: string,
  payload: {
    analysis_id?: string | null;
    part_a: string;
    part_b: string;
    manufacturer_a?: string | null;
    manufacturer_b?: string | null;
    decision: string;
    reviewer: string;
    rationale: string;
    validation_checks?: string[];
    follow_up_action?: string;
    follow_up_owner?: string;
    follow_up_due_date?: string | null;
    residual_risk?: string;
    verified_primary_evidence?: boolean;
    decision_candidate_scope?: "primary" | "all_selected";
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

export async function updateMonitoringPreferences(
  token: string,
  preferences: Record<string, boolean>,
) {
  return apiJson<{ ok: boolean; preferences: Record<string, unknown> }>(
    "/tools/monitoring/preferences",
    { method: "PUT", token, body: JSON.stringify(preferences) },
  );
}

export async function fetchMonitoringSlack(token: string) {
  return apiJson<{
    ok: boolean;
    integration: { enabled: boolean; configured: boolean; encryption_ready: boolean; can_manage: boolean };
  }>("/tools/monitoring/slack", { token });
}

export async function updateMonitoringSlack(
  token: string,
  body: { enabled: boolean; webhook_url?: string; clear?: boolean },
) {
  return apiJson<{
    ok: boolean;
    integration: { enabled: boolean; configured: boolean; encryption_ready: boolean; can_manage: boolean };
  }>("/tools/monitoring/slack", {
    method: "PUT",
    token,
    body: JSON.stringify(body),
  });
}

export async function refreshLiveMonitoring(
  token: string,
  payload: { analysis_id: string; part_number?: string },
) {
  return apiJson<Record<string, unknown>>("/tools/monitoring/live-refresh", {
    method: "POST",
    token,
    body: JSON.stringify(payload),
  });
}

/**
 * Explicit monitoring refresh — the only client path that persists alerts.
 * Scope is always explicit: a selected analysis (optionally one part) or
 * `portfolio` (workspace-wide). Does not call live suppliers.
 */
export async function refreshMonitoring(
  token: string,
  scope:
    | { analysisId: string; partNumber?: string }
    | { portfolio: true },
) {
  const params = new URLSearchParams();
  if ("portfolio" in scope) {
    params.set("scope", "portfolio");
  } else {
    params.set("analysis_id", scope.analysisId);
    if (scope.partNumber) params.set("part_number", scope.partNumber);
  }
  return apiJson<Record<string, unknown>>(
    `/tools/monitoring/refresh?${params.toString()}`,
    { token, method: "POST" },
  );
}

/** Default client bound for one pairwise compare (progress + fail-closed). */
export const COMPARE_PARTS_TIMEOUT_MS = 60_000;

export async function compareParts(
  token: string,
  partA: string,
  partB: string,
  analysisId?: string,
  datasheets?: { a?: File | null; b?: File | null },
  options?: {
    signal?: AbortSignal;
    timeoutMs?: number;
    manufacturerA?: string | null;
    manufacturerB?: string | null;
  },
) {
  const manufacturerA = String(options?.manufacturerA || "").trim();
  const manufacturerB = String(options?.manufacturerB || "").trim();
  const body = datasheets?.a || datasheets?.b ? new FormData() : null;
  if (body) {
    body.append("part_a", partA);
    body.append("part_b", partB);
    body.append("analysis_id", analysisId || "");
    if (manufacturerA) body.append("manufacturer_a", manufacturerA);
    if (manufacturerB) body.append("manufacturer_b", manufacturerB);
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
        manufacturer_a: manufacturerA || null,
        manufacturer_b: manufacturerB || null,
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
  identity?: { mpn?: string | null; manufacturer?: string | null },
) {
  const body = new FormData();
  body.append("file", file);
  body.append("question", question);
  const mpn = String(identity?.mpn || "").trim();
  const manufacturer = String(identity?.manufacturer || "").trim();
  if (mpn) body.append("mpn", mpn);
  if (manufacturer) body.append("manufacturer", manufacturer);
  return apiJson<Record<string, unknown>>("/tools/datasheet-qa", {
    method: "POST",
    token,
    body,
  });
}

/** Explicit monitoring email action — never implied by refresh or page GET. */
export async function notifyMonitoringAlert(
  token: string,
  alertId: string,
) {
  return apiJson<Record<string, unknown>>("/tools/monitoring/notify", {
    token,
    method: "POST",
    body: JSON.stringify({ alert_id: alertId }),
  });
}

export async function fetchProcurement(token: string, analysisId?: string) {
  const q = analysisId ? `?analysis_id=${encodeURIComponent(analysisId)}` : "";
  return apiJson<Record<string, unknown>>(`/tools/procurement${q}`, { token });
}

export type ProcurementQuote = {
  id: string;
  quote_id: string;
  analysis_id: string;
  project_name?: string | null;
  bom_name?: string | null;
  revision?: string | null;
  requested_mpn: string;
  requested_manufacturer?: string;
  supplier: string;
  quote_reference?: string;
  offered_mpn: string;
  offered_manufacturer?: string;
  identity_status: "exact_part" | "manufacturer_unconfirmed" | "alternate_candidate";
  requires_engineering_review: boolean;
  currency?: string;
  unit_price?: number | null;
  price_break_quantity?: number | null;
  price_breaks: Array<{ quantity: number; unit_price: number }>;
  minimum_order_quantity?: number | null;
  pack_quantity?: number | null;
  stock?: number | null;
  lead_time_weeks?: number | null;
  valid_until?: string;
  source_url?: string;
  notes?: string;
  created_at: string;
  evidence_kind: string;
};

export async function listProcurementQuotes(
  token: string,
  analysisId: string,
) {
  const query = new URLSearchParams({ analysis_id: analysisId });
  return apiJson<{ ok: boolean; analysis_id: string; quotes: ProcurementQuote[] }>(
    `/tools/procurement/quotes?${query}`,
    { token },
  );
}

export async function createProcurementQuote(
  token: string,
  payload: {
    analysis_id: string;
    requested_mpn: string;
    requested_manufacturer?: string;
    supplier: string;
    quote_reference?: string;
    offered_mpn: string;
    offered_manufacturer?: string;
    currency?: string;
    price_breaks?: Array<{ quantity: number; unit_price: number }>;
    minimum_order_quantity?: number | null;
    pack_quantity?: number | null;
    stock?: number | null;
    lead_time_weeks?: number | null;
    valid_until?: string;
    source_url?: string;
    notes?: string;
  },
) {
  return apiJson<{ ok: boolean; quote: ProcurementQuote }>(
    "/tools/procurement/quotes",
    { method: "POST", token, body: JSON.stringify(payload) },
  );
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

export async function recalculatePortfolioHealth(token: string, analysisId: string) {
  return apiJson<Record<string, unknown>>("/tools/portfolio/recalculate-health", {
    method: "POST",
    token,
    body: JSON.stringify({ analysis_id: analysisId }),
  });
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

export async function beginSubscriptionCheckout(
  token: string,
  plan: string,
  billingInterval: "month" | "year" = "month",
) {
  return apiJson<{
    ok: boolean;
    checkout?: { state: string; url?: string };
    code?: string;
    detail?: string;
  }>("/billing/checkout", {
    method: "POST",
    token,
    body: JSON.stringify({ plan, billing_interval: billingInterval }),
  });
}

export async function beginProfessionalApiAddonCheckout(token: string) {
  return apiJson<{
    ok: boolean;
    checkout?: { state: string; url?: string };
    detail?: string;
    code?: string;
  }>("/billing/addons/professional-api/checkout", {
    method: "POST",
    token,
    body: JSON.stringify({}),
  });
}

export async function beginMonitoredPartsAddonCheckout(
  token: string,
  billingInterval: "month" | "year",
) {
  return apiJson<{
    ok: boolean;
    addon_added?: boolean;
    capacity?: number;
    billing_interval?: "month" | "year";
    detail?: string;
    code?: string;
  }>("/billing/addons/monitored-parts/checkout", {
    method: "POST",
    token,
    body: JSON.stringify({ billing_interval: billingInterval }),
  });
}

export async function removeMonitoredPartsAddon(token: string) {
  return apiJson<{ ok: boolean; addon_removed?: boolean; detail?: string }>(
    "/billing/addons/monitored-parts/remove",
    { method: "POST", token, body: JSON.stringify({}) },
  );
}

export async function beginUsageOverageCheckout(
  token: string,
  creditKind: "bom_analysis",
) {
  return apiJson<{
    ok: boolean;
    checkout?: { state: string; url?: string };
    detail?: string;
  }>("/billing/addons/usage-overage/checkout", {
    method: "POST",
    token,
    body: JSON.stringify({ credit_kind: creditKind }),
  });
}

export type DeveloperApiKey = {
  id: string;
  name: string;
  key_prefix: string;
  created_at: string;
  last_used_at?: string | null;
};

export async function fetchDeveloperApiKeys(token: string) {
  return apiJson<{ ok: boolean; keys: DeveloperApiKey[] }>("/developer/api-keys", { token });
}

export async function createDeveloperApiKey(token: string, name: string) {
  return apiJson<{ ok: boolean; key: DeveloperApiKey & { secret: string } }>("/developer/api-keys", {
    method: "POST",
    token,
    body: JSON.stringify({ name }),
  });
}

export async function revokeDeveloperApiKey(token: string, keyId: string) {
  return apiJson<{ ok: boolean; revoked: boolean }>(
    `/developer/api-keys/${encodeURIComponent(keyId)}`,
    { method: "DELETE", token },
  );
}

export type DeveloperWebhook = {
  id: string;
  name: string;
  destination_host: string;
  event_types: string[];
  active: boolean;
  created_at?: string | null;
};

export type DeveloperWebhookDelivery = {
  id: string;
  webhook_id: string;
  event_id: string;
  event_type: string;
  status: string;
  attempt_count: number;
  response_status?: number | null;
  failure_code?: string | null;
  created_at?: string | null;
  delivered_at?: string | null;
};

export type DeveloperWebhookSettings = {
  ok: boolean;
  encryption_configured: boolean;
  allowed_event_types: string[];
  webhooks: DeveloperWebhook[];
  deliveries: DeveloperWebhookDelivery[];
};

export async function fetchDeveloperWebhooks(token: string) {
  return apiJson<DeveloperWebhookSettings>("/developer/webhooks", { token, cache: "no-store" });
}

export async function createDeveloperWebhook(
  token: string,
  payload: { name: string; url: string; event_types: string[] },
) {
  return apiJson<{ ok: boolean; webhook: DeveloperWebhook; signing_secret: string }>(
    "/developer/webhooks",
    { method: "POST", token, body: JSON.stringify(payload) },
  );
}

export async function deleteDeveloperWebhook(token: string, webhookId: string) {
  return apiJson<{ ok: boolean; removed: boolean }>(
    `/developer/webhooks/${encodeURIComponent(webhookId)}`,
    { method: "DELETE", token },
  );
}

export async function sendDeveloperWebhookTest(token: string, webhookId: string) {
  return apiJson<{
    ok: boolean;
    delivery: DeveloperWebhookDelivery;
    dispatch: { attempted: number; delivered: number; pending: number; failed: number };
  }>(`/developer/webhooks/${encodeURIComponent(webhookId)}/test`, {
    method: "POST", token, body: JSON.stringify({}),
  });
}

export async function beginBillingPortal(token: string) {
  return apiJson<{
    ok: boolean;
    checkout?: { state: string; url?: string };
    code?: string;
    detail?: string;
    support_reference?: string;
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
    configured_unverified_count?: number;
    connectors?: Array<Record<string, unknown>>;
    gap?: string | null;
  };
  billing_checkout?: { status?: string; enabled?: boolean };
  detail?: string;
};

export async function fetchServiceReadiness(token: string) {
  return apiJson<ServiceReadiness>("/integrations/service-readiness", { token });
}

export type CompliancePackType = "rohs" | "reach" | "pfas" | "conflict_minerals" | "pcn" | "audit";

export async function fetchCompliancePack(token: string, packType: CompliancePackType, analysisId?: string) {
  const analysisQuery = analysisId ? `?analysis_id=${encodeURIComponent(analysisId)}` : "";
  return apiJson<Record<string, unknown>>(
    `/compliance/${encodeURIComponent(packType)}${analysisQuery}`,
    { token },
  );
}

export async function downloadCompliancePack(
  token: string,
  analysisId: string,
  packType: CompliancePackType,
): Promise<void> {
  const result = await fetchCompliancePack(token, packType, analysisId);
  const blob = new Blob([JSON.stringify(result, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `cadivor-${packType}-${analysisId.slice(0, 12)}.json`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
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

export type RuntimeMaintenanceStatus = {
  maintenance_mode: boolean;
  maintenance_message: string;
  is_admin: boolean;
  planned_maintenance_message?: string;
  planned_maintenance_starts_at?: string | null;
  planned_maintenance_ends_at?: string | null;
};

export type PublicServiceStatus = {
  maintenance_mode: boolean;
  maintenance_message: string;
  planned_maintenance_message: string;
  planned_maintenance_starts_at: string | null;
  planned_maintenance_ends_at: string | null;
};

export async function fetchPublicServiceStatus() {
  return apiJson<PublicServiceStatus>("/public/service-status", { cache: "no-store" });
}

export async function fetchRuntimeMaintenance(token: string) {
  return apiJson<RuntimeMaintenanceStatus>("/runtime/maintenance", { token, cache: "no-store" });
}

export type AdminPlatformOverview = {
  registered_users?: number;
  active_now?: number;
  active_last_30_days?: number;
  suspended_users?: number;
  maintenance_mode: boolean;
  maintenance_message: string;
  planned_maintenance_message: string;
  planned_maintenance_starts_at: string | null;
  planned_maintenance_ends_at: string | null;
};

export async function fetchAdminPlatformSettings(token: string) {
  return apiJson<{ ok: boolean; overview: AdminPlatformOverview }>("/admin/platform-settings", { token, cache: "no-store" });
}

export async function updateAdminMaintenanceMode(
  token: string,
  body: {
    maintenance_mode: boolean;
    maintenance_message: string;
    confirmation: string;
  },
) {
  return apiJson<{
    ok: boolean;
    maintenance_mode: boolean;
    maintenance_message: string;
  }>("/admin/platform-settings/maintenance", {
    method: "PUT",
    token,
    body: JSON.stringify(body),
  });
}

export async function updateAdminPlannedMaintenance(
  token: string,
  body: {
    message: string;
    starts_at: string | null;
    ends_at: string | null;
  },
) {
  return apiJson<{
    ok: boolean;
    planned_maintenance_message: string;
    planned_maintenance_starts_at: string | null;
    planned_maintenance_ends_at: string | null;
  }>("/admin/platform-settings/planned-maintenance", {
    method: "PUT",
    token,
    body: JSON.stringify(body),
  });
}

export async function fetchAdminAccountEntitlements(token: string, email: string) {
  return apiJson<{
    ok: boolean;
    account: { email: string; feature_overrides: Record<string, boolean> };
  }>(`/admin/account-entitlements?email=${encodeURIComponent(email)}`, { token });
}

export async function updateAdminAccountEntitlements(
  token: string,
  email: string,
  featureOverrides: Record<string, boolean>,
) {
  return apiJson<{
    ok: boolean;
    account: { email: string; feature_overrides: Record<string, boolean> };
  }>("/admin/account-entitlements", {
    method: "PUT",
    token,
    body: JSON.stringify({ email, feature_overrides: featureOverrides }),
  });
}

export type AdminAccount = {
  id: string;
  email: string;
  full_name?: string | null;
  role_title?: string | null;
  company_name?: string | null;
  profile_image_url?: string | null;
  role?: string | null;
  plan?: string | null;
  account_status: "active" | "suspended";
  suspended_reason?: string | null;
  trial_started_at?: string | null;
  trial_ends_at?: string | null;
  plan_changed_at?: string | null;
  signup_at?: string | null;
  last_sign_in_at?: string | null;
  last_active_at?: string | null;
  activity_status?: "active" | "idle" | "offline";
};

export async function fetchAdminAccounts(token: string) {
  return apiJson<{ ok: boolean; users: AdminAccount[] }>("/admin/users", { token });
}

export async function fetchAdminAccountProfile(token: string, userId: string) {
  return apiJson<{ ok: boolean; user: AdminAccount }>(
    `/admin/users/${encodeURIComponent(userId)}`,
    { token },
  );
}

export type AdminManualPlanInvoice = {
  id: string;
  plan: string;
  billing_interval: "month" | "year";
  amount_minor: number;
  currency: string;
  status: "creating" | "open" | "payment_recorded" | "paid" | "void";
  due_days?: number | null;
  hosted_invoice_url?: string | null;
  invoice_pdf?: string | null;
  invoice_sent_at?: string | null;
  due_at?: string | null;
  created_at?: string | null;
  paid_at?: string | null;
  payment_method?: "stripe" | "cash" | "check" | "offline_unclassified" | null;
  payment_reference?: string | null;
  payment_recorded_at?: string | null;
  grant_starts_at?: string | null;
  grant_ends_at?: string | null;
  stripe_invoice_id?: string | null;
};

export async function fetchAdminManualPlanBilling(token: string, userId: string) {
  return apiJson<{ ok: boolean; invoices: AdminManualPlanInvoice[] }>(
    `/admin/users/${encodeURIComponent(userId)}/billing`,
    { token },
  );
}

export async function adminManualPlanBillingAction(
  token: string,
  userId: string,
  body: Record<string, unknown>,
) {
  return apiJson<Record<string, unknown>>(
    `/admin/users/${encodeURIComponent(userId)}/billing`,
    { method: "POST", token, body: JSON.stringify(body) },
  );
}

export async function updateAdminAccountStatus(
  token: string,
  userId: string,
  status: "active" | "suspended",
  reason = "",
) {
  return apiJson<{ ok: boolean; account_status: "active" | "suspended" }>(
    `/admin/users/${encodeURIComponent(userId)}`,
    { method: "PATCH", token, body: JSON.stringify({ status, reason }) },
  );
}

export async function deleteAdminAccount(
  token: string,
  userId: string,
  confirmationEmail: string,
) {
  return apiJson<{
    ok: boolean;
    deleted: boolean;
    cleanup?: {
      private_workspaces_deleted: number;
      shared_workspaces_preserved: number;
      shared_workspaces_ownership_transferred: number;
    };
  }>(`/admin/users/${encodeURIComponent(userId)}`, {
    method: "DELETE",
    token,
    body: JSON.stringify({ confirmation_email: confirmationEmail }),
  });
}
