/** Shared upload-bound constants for the anonymous public BOM audit proxy. */

export const MAX_PUBLIC_BOM_UPLOAD_BYTES = 1_000_000;
/** Multipart envelope overhead above the 1 MB file payload. */
export const MAX_PUBLIC_BOM_MULTIPART_OVERHEAD_BYTES = 65_536;
export const MAX_PUBLIC_BOM_REQUEST_BYTES =
  MAX_PUBLIC_BOM_UPLOAD_BYTES + MAX_PUBLIC_BOM_MULTIPART_OVERHEAD_BYTES;

/**
 * Early reject when Content-Length is present and invalid/oversized.
 * Missing Content-Length is allowed — callers must use bounded streaming.
 * @param {string | null | undefined} header
 * @returns {{ ok: true, length: number | null, stream: boolean } | { ok: false, status: number, detail: string }}
 */
export function evaluatePublicBomAuditContentLength(header) {
  if (header == null || String(header).trim() === "") {
    return { ok: true, length: null, stream: true };
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
  return { ok: true, length, stream: false };
}

/**
 * Read a request body with a hard byte cap (for chunked / missing Content-Length).
 * @param {ReadableStream<Uint8Array> | null | undefined} body
 * @param {number} maxBytes
 * @returns {Promise<{ ok: true, buffer: Uint8Array } | { ok: false, status: number, detail: string }>}
 */
export async function readBodyWithByteLimit(body, maxBytes = MAX_PUBLIC_BOM_REQUEST_BYTES) {
  if (!body || typeof body.getReader !== "function") {
    return { ok: true, buffer: new Uint8Array(0) };
  }
  const reader = body.getReader();
  const chunks = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!value || value.byteLength === 0) continue;
      total += value.byteLength;
      if (total > maxBytes) {
        try {
          await reader.cancel();
        } catch {
          /* ignore cancel errors after limit breach */
        }
        return {
          ok: false,
          status: 413,
          detail: "Upload a CSV or XLSX BOM smaller than 1 MB.",
        };
      }
      chunks.push(value);
    }
  } catch {
    return {
      ok: false,
      status: 400,
      detail: "Invalid multipart upload.",
    };
  }
  const buffer = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    buffer.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return { ok: true, buffer };
}
