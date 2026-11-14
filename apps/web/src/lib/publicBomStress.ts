/** Client helpers for the anonymous 5-part BOM audit (no account required). */

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
}): Promise<{ ok: boolean; email: string }> {
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
  return res.json() as Promise<{ ok: boolean; email: string }>;
}
