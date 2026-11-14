/** Client helpers for the anonymous 5-part BOM audit and verified report handoff. */

export type PublicBomPreviewRow = {
  mpn: string;
  manufacturer?: string;
  lifecycle?: string;
  stock?: number | null;
  stock_evidence?: string;
  lead_time_weeks?: number | null;
  lead_time_source?: string;
  supplier_count?: number | null;
  sources?: string;
  supplier_coverage?: string;
  risk?: string;
  verified?: boolean;
  quantity?: number | null;
  matched_mpn?: string;
  lifecycle_evidence_summary?: string;
  risk_reasons?: string[];
  checked_at?: string;
  enrichment_pending?: boolean;
};

export type PublicBomAuditReport = {
  id: string;
  row_count: number;
  preview: PublicBomPreviewRow[];
  remaining_count: number;
  remaining_high_risk: number;
  remaining_unverified: number;
  remaining_pending?: number;
  preview_enriched_count?: number;
  qa_mode?: boolean;
  full_enriched?: boolean;
};

export type PublicBomStatus = {
  ok: boolean;
  enabled: boolean;
  preview_rows: number;
  max_rows: number;
  max_bytes: number;
  turnstile_required?: boolean;
  /** Server-verified confirmed allowlisted QA session only. Never a client flag. */
  qa_verified?: boolean;
  daily_enriched_row_limit?: number;
};

export type PublicBomVerifiedReport = {
  id: string;
  filename?: string;
  row_count?: number;
  results: PublicBomPreviewRow[];
  created_at?: string;
  full_enriched?: boolean;
  full_enriched_at?: string;
  qa_mode?: boolean;
  preview_enriched_count?: number;
};

export const PUBLIC_BOM_STRESS_FLAG = "cadivor_stress_report";
export const PUBLIC_BOM_STRESS_REPORT_ID_FLAG = "cadivor_stress_report_id";
export const PUBLIC_BOM_STRESS_PENDING_KEY = "cadivor_stress_report_pending";
export const PUBLIC_BOM_STRESS_REPORT_ID_KEY = "cadivor_stress_report_id";
export const PUBLIC_BOM_STRESS_CACHE_PREFIX = "cadivor_public_bom_stress_verified:";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function normalizeStressReportId(value: string | null | undefined): string | null {
  const text = String(value || "").trim();
  if (!text || text.length > 64) return null;
  return UUID_RE.test(text) ? text.toLowerCase() : null;
}

async function readError(res: Response): Promise<string> {
  const payload = (await res.json().catch(() => ({}))) as Record<string, unknown>;
  if (typeof payload.detail === "string" && payload.detail.trim()) {
    return payload.detail;
  }
  return `Request failed (${res.status})`;
}

/** Same-origin Next route handlers forward the Cloudflare visitor header. */
export async function fetchPublicBomStatus(
  accessToken?: string | null,
): Promise<PublicBomStatus> {
  const headers: Record<string, string> = {};
  const token = String(accessToken || "").trim();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch("/api/public/bom-stress/status", {
    method: "GET",
    headers,
    cache: "no-store",
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json() as Promise<PublicBomStatus>;
}

export async function runPublicBomAudit(
  file: File,
  options?: { turnstileToken?: string | null; accessToken?: string | null },
): Promise<PublicBomAuditReport> {
  const body = new FormData();
  body.append("file", file, file.name);
  const token = String(options?.turnstileToken || "").trim();
  if (token) body.append("cf-turnstile-response", token);
  const headers: Record<string, string> = {};
  const accessToken = String(options?.accessToken || "").trim();
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  const res = await fetch("/api/public/bom-stress/audit", {
    method: "POST",
    headers,
    body,
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json() as Promise<PublicBomAuditReport>;
}

/** Finish deferred supplier lookups after confirmed email ownership. */
export async function completePublicBomAudit(
  accessToken: string,
  reportId?: string | null,
): Promise<PublicBomVerifiedReport> {
  const res = await fetch("/api/public/bom-stress/complete", {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({
      report_id: normalizeStressReportId(reportId || "") || undefined,
    }),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(await readError(res));
  const payload = (await res.json()) as {
    ok?: boolean;
    report?: PublicBomVerifiedReport;
  };
  if (!payload.report) throw new Error("Verified public audit not found.");
  return payload.report;
}

export function verifiedReportExportHref(
  reportId?: string | null,
  format: "csv" | "xlsx" = "csv",
): string {
  const params = new URLSearchParams({ format });
  const safeId = normalizeStressReportId(reportId || "");
  if (safeId) params.set("report_id", safeId);
  return `/api/public/bom-stress/verified-report/export?${params.toString()}`;
}

export async function requestPublicBomFullReport(input: {
  reportId: string;
  email: string;
  acceptedTerms: boolean;
  source?: string;
}): Promise<{ ok: boolean; email: string; verification_sent: boolean }> {
  const res = await fetch("/api/public/bom-stress/lead", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      report_id: input.reportId,
      email: input.email,
      accepted_terms: input.acceptedTerms,
      source: input.source || "",
    }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json() as Promise<{
    ok: boolean;
    email: string;
    verification_sent: boolean;
  }>;
}

/** Authenticated fetch — ownership comes from the bearer, never a form email. */
export async function fetchVerifiedPublicBomReport(
  accessToken: string,
  reportId?: string | null,
): Promise<PublicBomVerifiedReport> {
  const params = new URLSearchParams();
  const safeId = normalizeStressReportId(reportId || "");
  if (safeId) params.set("report_id", safeId);
  const qs = params.toString() ? `?${params.toString()}` : "";
  const res = await fetch(`/api/public/bom-stress/verified-report${qs}`, {
    method: "GET",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(await readError(res));
  const payload = (await res.json()) as {
    ok?: boolean;
    report?: PublicBomVerifiedReport;
  };
  if (!payload.report) throw new Error("Verified public audit not found.");
  return payload.report;
}

export type StressReportPending = {
  pending: boolean;
  reportId: string | null;
};

export function markStressReportPending(reportId?: string | null): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(PUBLIC_BOM_STRESS_PENDING_KEY, "1");
  const safeId = normalizeStressReportId(reportId || "");
  if (safeId) {
    window.sessionStorage.setItem(PUBLIC_BOM_STRESS_REPORT_ID_KEY, safeId);
  }
}

export function peekStressReportId(): string | null {
  if (typeof window === "undefined") return null;
  return normalizeStressReportId(
    window.sessionStorage.getItem(PUBLIC_BOM_STRESS_REPORT_ID_KEY) ||
      window.localStorage.getItem(PUBLIC_BOM_STRESS_REPORT_ID_KEY),
  );
}

export function rememberStressReportId(reportId: string | null | undefined): void {
  if (typeof window === "undefined") return;
  const safeId = normalizeStressReportId(reportId || "");
  if (!safeId) return;
  window.sessionStorage.setItem(PUBLIC_BOM_STRESS_REPORT_ID_KEY, safeId);
  window.localStorage.setItem(PUBLIC_BOM_STRESS_REPORT_ID_KEY, safeId);
}

export function consumeStressReportPending(): StressReportPending {
  if (typeof window === "undefined") {
    return { pending: false, reportId: null };
  }
  const pending =
    window.sessionStorage.getItem(PUBLIC_BOM_STRESS_PENDING_KEY) === "1";
  const reportId = normalizeStressReportId(
    window.sessionStorage.getItem(PUBLIC_BOM_STRESS_REPORT_ID_KEY),
  );
  if (pending) window.sessionStorage.removeItem(PUBLIC_BOM_STRESS_PENDING_KEY);
  // Keep report id for the Reports handoff URL / reopen; cleared only on success path if needed.
  return { pending, reportId };
}

export function reportsHandoffHref(reportId?: string | null): string {
  const params = new URLSearchParams({ public_bom_stress: "1" });
  const safeId = normalizeStressReportId(reportId || "");
  if (safeId) params.set("report_id", safeId);
  return `/reports?${params.toString()}`;
}

export function cacheVerifiedPublicBomReport(
  identity: string,
  report: PublicBomVerifiedReport,
): void {
  if (typeof window === "undefined" || !identity) return;
  const reportKey = normalizeStressReportId(report.id) || "latest";
  window.localStorage.setItem(
    `${PUBLIC_BOM_STRESS_CACHE_PREFIX}${identity}:${reportKey}`,
    JSON.stringify({ saved_at: new Date().toISOString(), report }),
  );
  // Also keep a "latest opened" pointer for reload without query params.
  window.localStorage.setItem(
    `${PUBLIC_BOM_STRESS_CACHE_PREFIX}${identity}`,
    JSON.stringify({ saved_at: new Date().toISOString(), report }),
  );
  rememberStressReportId(report.id);
}

export function readCachedVerifiedPublicBomReport(
  identity: string,
  reportId?: string | null,
): PublicBomVerifiedReport | null {
  if (typeof window === "undefined" || !identity) return null;
  try {
    const safeId = normalizeStressReportId(reportId || "");
    const keys = safeId
      ? [
          `${PUBLIC_BOM_STRESS_CACHE_PREFIX}${identity}:${safeId}`,
          `${PUBLIC_BOM_STRESS_CACHE_PREFIX}${identity}`,
        ]
      : [`${PUBLIC_BOM_STRESS_CACHE_PREFIX}${identity}`];
    for (const key of keys) {
      const raw = window.localStorage.getItem(key);
      if (!raw) continue;
      const parsed = JSON.parse(raw) as { report?: PublicBomVerifiedReport };
      if (!parsed.report) continue;
      if (safeId && normalizeStressReportId(parsed.report.id) !== safeId) {
        continue;
      }
      return parsed.report;
    }
    return null;
  } catch {
    return null;
  }
}
