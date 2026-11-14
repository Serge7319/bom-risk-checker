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
};

export type PublicBomAuditReport = {
  id: string;
  row_count: number;
  preview: PublicBomPreviewRow[];
  remaining_count: number;
  remaining_high_risk: number;
  remaining_unverified: number;
};

export type PublicBomStatus = {
  ok: boolean;
  enabled: boolean;
  preview_rows: number;
  max_rows: number;
  max_bytes: number;
};

export type PublicBomVerifiedReport = {
  id: string;
  filename?: string;
  row_count?: number;
  results: PublicBomPreviewRow[];
  created_at?: string;
};

export const PUBLIC_BOM_STRESS_FLAG = "cadivor_stress_report";
export const PUBLIC_BOM_STRESS_PENDING_KEY = "cadivor_stress_report_pending";
export const PUBLIC_BOM_STRESS_CACHE_PREFIX = "cadivor_public_bom_stress_verified:";

async function readError(res: Response): Promise<string> {
  const payload = (await res.json().catch(() => ({}))) as Record<string, unknown>;
  if (typeof payload.detail === "string" && payload.detail.trim()) {
    return payload.detail;
  }
  return `Request failed (${res.status})`;
}

/** Same-origin Next route handlers forward the Cloudflare visitor header. */
export async function fetchPublicBomStatus(): Promise<PublicBomStatus> {
  const res = await fetch("/api/public/bom-stress/status", { method: "GET" });
  if (!res.ok) throw new Error(await readError(res));
  return res.json() as Promise<PublicBomStatus>;
}

export async function runPublicBomAudit(
  file: File,
): Promise<PublicBomAuditReport> {
  const body = new FormData();
  body.append("file", file, file.name);
  const res = await fetch("/api/public/bom-stress/audit", {
    method: "POST",
    body,
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json() as Promise<PublicBomAuditReport>;
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
  reportId?: string,
): Promise<PublicBomVerifiedReport> {
  const params = new URLSearchParams();
  if (reportId) params.set("report_id", reportId);
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

export function stressReportPendingKey(): string {
  return PUBLIC_BOM_STRESS_PENDING_KEY;
}

export function markStressReportPending(): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(PUBLIC_BOM_STRESS_PENDING_KEY, "1");
}

export function consumeStressReportPending(): boolean {
  if (typeof window === "undefined") return false;
  const pending =
    window.sessionStorage.getItem(PUBLIC_BOM_STRESS_PENDING_KEY) === "1";
  if (pending) window.sessionStorage.removeItem(PUBLIC_BOM_STRESS_PENDING_KEY);
  return pending;
}

export function cacheVerifiedPublicBomReport(
  identity: string,
  report: PublicBomVerifiedReport,
): void {
  if (typeof window === "undefined" || !identity) return;
  window.localStorage.setItem(
    `${PUBLIC_BOM_STRESS_CACHE_PREFIX}${identity}`,
    JSON.stringify({ saved_at: new Date().toISOString(), report }),
  );
}

export function readCachedVerifiedPublicBomReport(
  identity: string,
): PublicBomVerifiedReport | null {
  if (typeof window === "undefined" || !identity) return null;
  try {
    const raw = window.localStorage.getItem(
      `${PUBLIC_BOM_STRESS_CACHE_PREFIX}${identity}`,
    );
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { report?: PublicBomVerifiedReport };
    return parsed.report || null;
  } catch {
    return null;
  }
}
