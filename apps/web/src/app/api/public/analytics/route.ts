import { NextRequest, NextResponse } from "next/server";
import { readBodyWithByteLimit } from "@/lib/publicBomUploadLimit.js";

export const dynamic = "force-dynamic";
const MAX_BODY_BYTES = 4096;

function allowedOrigins(): Set<string> {
  const configured = (process.env.CADIVOR_MARKETING_ORIGINS || "")
    .split(",").map((value) => value.trim()).filter(Boolean);
  return new Set([
    "https://app.cadivor.com", "https://cadivor.com", "https://www.cadivor.com",
    "http://localhost:3000", "http://127.0.0.1:3000", ...configured,
  ]);
}

function corsHeaders(request: NextRequest): Headers {
  const headers = new Headers({ Vary: "Origin" });
  const origin = request.headers.get("origin") || "";
  if (origin && allowedOrigins().has(origin)) {
    headers.set("Access-Control-Allow-Origin", origin);
    headers.set("Access-Control-Allow-Methods", "POST, OPTIONS");
    headers.set("Access-Control-Allow-Headers", "Content-Type");
    headers.set("Access-Control-Max-Age", "600");
  }
  return headers;
}

function apiBase(): string {
  return (process.env.CADIVOR_API_BASE || process.env.NEXT_PUBLIC_API_BASE || "")
    .trim().replace(/\/$/, "");
}

export async function OPTIONS(request: NextRequest): Promise<NextResponse> {
  const headers = corsHeaders(request);
  if (request.headers.get("origin") && !headers.has("Access-Control-Allow-Origin")) {
    return new NextResponse(null, { status: 403, headers });
  }
  return new NextResponse(null, { status: 204, headers });
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const headers = corsHeaders(request);
  if (request.headers.get("origin") && !headers.has("Access-Control-Allow-Origin")) {
    return NextResponse.json({ detail: "Origin is not allowed." }, { status: 403 });
  }
  const length = Number(request.headers.get("content-length") || "0");
  if (Number.isFinite(length) && length > MAX_BODY_BYTES) {
    return NextResponse.json({ detail: "Request is too large." }, { status: 413, headers });
  }
  const limited = await readBodyWithByteLimit(request.body, MAX_BODY_BYTES);
  if (!limited.ok) {
    return NextResponse.json({ detail: "Invalid request." }, { status: limited.status, headers });
  }
  let body: unknown;
  try {
    body = JSON.parse(new TextDecoder().decode(limited.buffer));
  } catch {
    return NextResponse.json({ detail: "Invalid request." }, { status: 400, headers });
  }
  const base = apiBase();
  if (!base) return NextResponse.json({ ok: false, accepted: false }, { status: 202, headers });
  try {
    const forwardHeaders: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "application/json",
    };
    const signedVisitor = request.headers.get("x-cadivor-visitor") || "";
    if (signedVisitor) forwardHeaders["X-Cadivor-Visitor"] = signedVisitor;
    const upstream = await fetch(`${base}/public/analytics`, {
      method: "POST",
      headers: forwardHeaders,
      body: JSON.stringify(body),
      cache: "no-store",
    });
    let responseBody: unknown = {};
    try { responseBody = await upstream.json(); } catch { /* keep response generic */ }
    return NextResponse.json(responseBody, { status: upstream.status, headers });
  } catch {
    return NextResponse.json({ ok: false, accepted: false }, { status: 202, headers });
  }
}
