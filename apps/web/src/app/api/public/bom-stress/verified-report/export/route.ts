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

/** Authenticated export proxy — ownership from bearer only. */
export async function GET(request: NextRequest) {
  const auth = request.headers.get("authorization") || "";
  if (!auth.toLowerCase().startsWith("bearer ")) {
    return NextResponse.json({ detail: "Missing bearer token" }, { status: 401 });
  }
  const params = new URLSearchParams(request.nextUrl.searchParams);
  params.delete("email");
  const suffix = params.toString() ? `?${params.toString()}` : "";
  try {
    const res = await fetch(
      `${apiBase()}/public/bom-stress/verified-report/export${suffix}`,
      {
        method: "GET",
        headers: {
          Accept: "*/*",
          Authorization: auth,
        },
        cache: "no-store",
      },
    );
    const contentType = res.headers.get("content-type") || "application/octet-stream";
    if (!contentType.includes("json") && res.ok) {
      const body = await res.arrayBuffer();
      return new NextResponse(body, {
        status: res.status,
        headers: {
          "Content-Type": contentType,
          "Content-Disposition":
            res.headers.get("content-disposition") || "attachment",
          "Cache-Control": "no-store",
        },
      });
    }
    const text = await res.text();
    let payload: unknown = {};
    try {
      payload = text ? JSON.parse(text) : {};
    } catch {
      payload = { detail: text || `Upstream error (${res.status})` };
    }
    return NextResponse.json(payload, { status: res.status });
  } catch (err) {
    const detail = err instanceof Error ? err.message : "Export unavailable.";
    return NextResponse.json({ detail }, { status: 503 });
  }
}
