import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

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

/** Authenticated proxy: forward bearer only; never a client-supplied email. */
export async function GET(request: NextRequest) {
  const auth = request.headers.get("authorization") || "";
  if (!auth.toLowerCase().startsWith("bearer ")) {
    return NextResponse.json({ detail: "Missing bearer token" }, { status: 401 });
  }
  const qs = request.nextUrl.searchParams.toString();
  // Drop any client email param so ownership stays token-derived upstream.
  const params = new URLSearchParams(qs);
  params.delete("email");
  const suffix = params.toString() ? `?${params.toString()}` : "";
  try {
    const res = await fetch(
      `${apiBase()}/public/bom-stress/verified-report${suffix}`,
      {
        method: "GET",
        headers: {
          Accept: "application/json",
          Authorization: auth,
        },
        cache: "no-store",
      },
    );
    const text = await res.text();
    let body: unknown = {};
    try {
      body = text ? JSON.parse(text) : {};
    } catch {
      body = { detail: text || `Upstream error (${res.status})` };
    }
    return NextResponse.json(body, { status: res.status });
  } catch (err) {
    const detail =
      err instanceof Error ? err.message : "Verified public audit unavailable.";
    return NextResponse.json({ detail }, { status: 503 });
  }
}
