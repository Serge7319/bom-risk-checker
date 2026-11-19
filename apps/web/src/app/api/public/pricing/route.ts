import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

function allowedOrigins(): Set<string> {
  const configured = (process.env.CADIVOR_MARKETING_ORIGINS || "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  return new Set([
    "https://cadivor.com",
    "https://www.cadivor.com",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    ...configured,
  ]);
}

function corsHeaders(request: NextRequest): Headers {
  const headers = new Headers({ Vary: "Origin" });
  const origin = request.headers.get("origin") || "";
  if (origin && allowedOrigins().has(origin)) {
    headers.set("Access-Control-Allow-Origin", origin);
    headers.set("Access-Control-Allow-Methods", "GET, OPTIONS");
    headers.set("Access-Control-Max-Age", "600");
  }
  return headers;
}

function apiBase(): string {
  const configured = (
    process.env.CADIVOR_API_BASE || process.env.NEXT_PUBLIC_API_BASE || ""
  )
    .trim()
    .replace(/\/$/, "");
  if (!configured) throw new Error("The Cadivor API is not configured.");
  return configured;
}

export async function OPTIONS(request: NextRequest): Promise<NextResponse> {
  const headers = corsHeaders(request);
  if (request.headers.get("origin") && !headers.has("Access-Control-Allow-Origin")) {
    return new NextResponse(null, { status: 403, headers });
  }
  return new NextResponse(null, { status: 204, headers });
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  const headers = corsHeaders(request);
  if (request.headers.get("origin") && !headers.has("Access-Control-Allow-Origin")) {
    return NextResponse.json({ detail: "Origin is not allowed." }, { status: 403, headers });
  }
  try {
    const upstream = await fetch(`${apiBase()}/billing/public-catalog`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: AbortSignal.timeout(12_000),
    });
    const text = await upstream.text();
    let body: unknown = {};
    try {
      body = text ? JSON.parse(text) : {};
    } catch {
      body = { detail: "Pricing is temporarily unavailable." };
    }
    headers.set("Cache-Control", "public, max-age=300, s-maxage=300");
    return NextResponse.json(body, { status: upstream.status, headers });
  } catch {
    return NextResponse.json(
      { detail: "Pricing is temporarily unavailable." },
      { status: 503, headers },
    );
  }
}
