const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") || "http://127.0.0.1:8787";

export const SMOKE_EMAIL = "auth-smoke@cadivor.test";
export const SMOKE_PASSWORD = "cadivor-auth-smoke";

export type Session = {
  access_token: string;
  email: string;
  workspace: string;
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
};

export type Report = AnalyzeSummary & {
  id: string;
  filename: string;
  created_at: string;
  summary_message?: string;
  parts: Array<Record<string, unknown>>;
};

const SESSION_KEY = "cadivor_next_smoke_session";

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
  const res = await fetch(`${API_BASE}/auth/smoke-login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(detail.detail || "Login failed");
  }
  return res.json();
}

export async function analyzeBom(file: File, token: string): Promise<AnalyzeSummary> {
  const body = new FormData();
  body.append("file", file);
  const res = await fetch(`${API_BASE}/boms/analyze`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body,
  });
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(detail.detail || "Analyze failed");
  }
  return res.json();
}

export async function fetchReport(analysisId: string, token: string): Promise<Report> {
  const res = await fetch(`${API_BASE}/reports/${analysisId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(detail.detail || "Report not found");
  }
  return res.json();
}

export { API_BASE };
