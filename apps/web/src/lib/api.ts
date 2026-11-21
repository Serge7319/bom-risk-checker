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
  appendIntakeOptions(body, options