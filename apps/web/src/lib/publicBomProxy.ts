import { NextRequest, NextResponse } from "next/server";

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

async function proxyJson(
  upstream: Response,
): Promise<NextResponse> {
  const text = await upstream.text();
  let body: unknown = {};
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = { detail: text || `Upstream error (${upstream.status})` };
  }
  return NextResponse.json(body, { status: upstream.status });
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
  try {
    const form = await request.formData();
    const res = await fetch(`${apiBase()}/public/bom-stress/audit`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "X-Cadivor-Visitor": visitorHeader(request),
      },
      body: form,
      cache: "no-store",
    });
    return proxyJson(res);
  } catch (err) {
    const detail =
      err instanceof Error ? err.message : "Public audit request failed.";
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
