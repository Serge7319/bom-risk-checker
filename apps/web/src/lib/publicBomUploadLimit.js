/** Shared upload-bound constants for the anonymous public BOM audit proxy. */

export const MAX_PUBLIC_BOM_UPLOAD_BYTES = 1_000_000;
/** Multipart envelope overhead above the 1 MB file payload. */
export const MAX_PUBLIC_BOM_MULTIPART_OVERHEAD_BYTES = 65_536;
export const MAX_PUBLIC_BOM_REQUEST_BYTES =
  MAX_PUBLIC_BOM_UPLOAD_BYTES + MAX_PUBLIC_BOM_MULTIPART_OVERHEAD_BYTES;

/**
 * Fail closed before buffering multipart bodies.
 * @param {string | null | undefined} header
 * @returns {{ ok: true, length: number } | { ok: false, status: number, detail: string }}
 */
export function evaluatePublicBomAuditContentLength(header) {
  if (header == null || String(header).trim() === "") {
    return { ok: false, status: 411, detail: "Content-Length is required." };
  }
  const raw = String(header).trim();
  if (!/^\d+$/.test(raw)) {
    return { ok: false, status: 400, detail: "Invalid Content-Length." };
  }
  const length = Number(raw);
  if (length > MAX_PUBLIC_BOM_REQUEST_BYTES) {
    return {
      ok: false,
      status: 413,
      detail: "Upload a CSV or XLSX BOM smaller than 1 MB.",
    };
  }
  return { ok: true, length };
}
