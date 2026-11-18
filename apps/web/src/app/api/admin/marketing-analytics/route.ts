import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

function apiBase(): string {
  return (process.env.CADIVOR_API_BASE || process.env.NEXT_PUBLIC_API_BASE || "")
    .trim().replace(/\/$/, "");
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  const authorization = request.headers.get("authorization") || "";
  if (!/^Bearer\s+\S+/i.test(authorization)) {
    return NextResponse.json({ detail: "Sign in as a platform administrator." }, { status: 401 });
  }
  const base = apiBase();
  if (!base) return NextResponse.json({ detail: "The Cadivor API is not configured." }, { status: 503 });
  const days = request.nextUrl.searchParams.get("days") || "30";
  try {
    const upstream = await fetch(`${base}/admin/marketing-analytics?days=${encodeURIComponent(days)}`, {
      headers: { Accept: "application/json", Authorization: authorization },
      cache: "no-store",
    });
    let body: unknown = {};
    try { body = await upstream.json(); } catch { body = { detail: "Analytics response was invalid." }; }
    return NextResponse.json(body, { status: upstream.status, headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ detail: "Could not reach the Cadivor API." }, { status: 503 });
  }
}
