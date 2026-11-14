import { NextRequest, NextResponse } from "next/server";
import {
  evaluatePublicBomAuditContentLength,
  MAX_PUBLIC_BOM_REQUEST_BYTES,
  readBodyWithByteLimit,
} from "@/lib/publicBomUploadLimit.js";

/**
 * Server-side API origin for anonymous public-audit proxies.
 * Prefer CADIVOR_API_BASE (server-only). NEXT_PUBLIC_API_BASE is a non-secret
 * public origin fallback for local/dev — never put HMAC/service-role secrets in
 * NEXT_PUBLIC_* variables.
 */
function apiBase(): string {
  const configured = (
    process.env.CADIVOR_API_BASE ||
    process.env.NEXT_PUBLIC_API_BASE ||
    ""
  )
    .trim()
    .replace(/\/$/, "");
  if (!configured) {
    throw new Error(
      "Set CADIVOR_API_BASE (preferred) or NEXT_PUBLIC_API_BASE for public BOM audit proxies.",
    );
  }
  return configured;
}

function visitorHeader(request: NextRequest): string {
  return request.headers.get("x-cadivor-visitor") || "";
}

function forwardQuery(request: NextRequest): string {
  const qs = request.nextUrl.searchParams.toString();
  return qs ? `?${qs}` : "";
}

async function proxyJson(upstream: Response): Promise<NextResponse> {
  const text = await upstream.text();
  let body: unknown = {};
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = { detail: text || `Upstream error (${upstream.status})` };
  }
  return NextResponse.json(body, { status: upstream.status });
}

/**
 * Bound the multipart body before parsing.
 * Content-Length is an early reject when present; otherwise stream with a cap
 * (browsers may omit Content-Length on FormData uploads).
 */
export async function readPublicBomAuditForm(
  request: NextRequest,
): Promise<{ form: FormData } | { response: NextResponse }> {
  const lengthVerdict = evaluatePublicBomAuditContentLength(
    request.headers.get("content-length"),
  );
  if (!lengthVerdict.ok) {
    return {
      response: NextResponse.json(
        { detail: lengthVerdict.detail },
        { status: lengthVerdict.status },
      ),
    };
  }

  if (!lengthVerdict.stream) {
    try {
      return { form: await request.formData() };
    } catch {
      return {
        response: NextResponse.json(
          { detail: "Invalid multipart upload." },
          { status: 400 },
        ),
      };
    }
  }

  const limited = await readBodyWithByteLimit(
    request.body,
    MAX_PUBLIC_BOM_REQUEST_BYTES,
  );
  if (!limited.ok) {
    return {
      response: NextResponse.json(
        { detail: limited.detail },
        { status: limited.status },
      ),
    };
  }

  const contentType = request.headers.get("content-type") || "";
  try {
    // Copy into a standalone ArrayBuffer so BodyInit typing accepts the payload.
    const bytes = limited.buffer;
    const ab = new ArrayBuffer(bytes.byteLength);
    new Uint8Array(ab).set(bytes);
    const reconstructed = new Request(request.url, {
      method: "POST",
      headers: contentType ? { "content-type": contentType } : undefined,
      body: ab,
    });
    return { form: await reconstructed.formData() };
  } catch {
    return {
      response: NextResponse.json(
        { detail: "Invalid multipart upload." },
        { status: 400 },
      ),
    };
  }
}

/** GET /public/bom-stress/status → FastAPI */
export async function proxyPublicBomStatus(
  request: NextRequest,
): Promise<NextResponse> {
  try {
    const res = await fetch(
      `${apiBase()}/public/bom-stress/status${forwardQuery(request)}`,
      {
        method: "GET",
        headers: {
          Accept: "application/json",
          "X-Cadivor-Visitor": visitorHeader(request),
        },
        cache: "no-store",
      },
    );
    return proxyJson(res);
  } catch (err) {
    const detail =
      err instanceof Error ? err.message : "Public audit status unavailable.";
    return NextResponse.json({ detail }, { status: 503 });
  }
}

/** POST multipart audit; preserve Cloudflare visitor HMAC for rate limits. */
export async function proxyPublicBomAudit(
  request: NextRequest,
): Promise<NextResponse> {
  const parsed = await readPublicBomAuditForm(request);
  if ("response" in parsed) return parsed.response;
  try {
    const headers: Record<string, string> = {
      Accept: "application/json",
      "X-Cadivor-Visitor": visitorHeader(request),
    };
    // Forward bearer for server-side QA allowlist only (never a client QA flag).
    const auth = request.headers.get("authorization") || "";
    if (auth.toLowerCase().startsWith("bearer ")) {
      headers.Authorization = auth;
    }
    const res = await fetch(`${apiBase()}/public/bom-stress/audit`, {
      method: "POST",
      headers,
      body: parsed.form,
      cache: "no-store",
    });
    return proxyJson(res);
  } catch (err) {
    const detail =
      err instanceof Error ? err.message : "Public audit request failed.";
    return NextResponse.json({ detail }, { status: 503 });
  }
}

/** POST authenticated remaining-row completion. */
export async function proxyPublicBomComplete(
  request: NextRequest,
): Promise<NextResponse> {
  const auth = request.headers.get("authorization") || "";
  if (!auth.toLowerCase().startsWith("bearer ")) {
    return NextResponse.json({ detail: "Missing bearer token" }, { status: 401 });
  }
  try {
    const body = await request.text();
    const res = await fetch(`${apiBase()}/public/bom-stress/complete`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        Authorization: auth,
      },
      body,
      cache: "no-store",
    });
    return proxyJson(res);
  } catch (err) {
    const detail =
      err instanceof Error ? err.message : "Could not finish the audit.";
    return NextResponse.json({ detail }, { status: 503 });
  }
}

/** POST JSON lead capture + verification email. */
export async function proxyPublicBomLead(
  request: NextRequest,
): Promise<NextResponse> {
  try {
    const body = await request.text();
    const res = await fetch(
      `${apiBase()}/public/bom-stress/lead${forwardQuery(request)}`,
      {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-Cadivor-Visitor": visitorHeader(request),
        },
        body,
        cache: "no-store",
      },
    );
    return proxyJson(res);
  } catch (err) {
    const detail =
      err instanceof Error ? err.message : "Could not request the full report.";
    return NextResponse.json({ detail }, { status: 503 });
  }
}
