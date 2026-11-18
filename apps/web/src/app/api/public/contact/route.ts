import { NextRequest, NextResponse } from "next/server";
import { readBodyWithByteLimit } from "@/lib/publicBomUploadLimit.js";

export const dynamic = "force-dynamic";

const MAX_BODY_BYTES = 16 * 1024;

function allowedOrigins(): Set<string> {
  const configured = (process.env.CADIVOR_MARKETING_ORIGINS || "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  const defaults = [
    "https://cadivor.com",
    "https://www.cadivor.com",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
  ];
  return new Set([...defaults, ...configured]);
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
  const configured = (
    process.env.CADIVOR_API_BASE || process.env.NEXT_PUBLIC_API_BASE || ""
  )
    .trim()
    .replace(/\/$/, "");
  if (!configured) {
    throw new Error("The Cadivor API is not configured.");
  }
  return configured;
}

async function jsonResponse(upstream: Response, headers: Headers): Promise<NextResponse> {
  const text = await upstream.text();
  let body: unknown = {};
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = { detail: "The request could not be processed." };
  }
  return NextResponse.json(body, { status: upstream.status, headers });
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

  const contentLength = Number(request.headers.get("content-length") || "0");
  if (Number.isFinite(contentLength) && contentLength > MAX_BODY_BYTES) {
    return NextResponse.json({ detail: "Request is too large." }, { status: 413, headers });
  }
  const limited = await readBodyWithByteLimit(request.body, MAX_BODY_BYTES);
  if (!limited.ok) {
    return NextResponse.json(
      { detail: limited.status === 413 ? "Request is too large." : "Invalid request." },
      { status: limited.status, headers },
    );
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(new TextDecoder().decode(limited.buffer));
  } catch {
    return NextResponse.json({ detail: "Invalid request." }, { status: 400, headers });
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return NextResponse.json({ detail: "Invalid request." }, { status: 400, headers });
  }

  try {
    const forwardHeaders: Record<string, string> = {
      Accept: "application/json",
      "Content-Type": "application/json",
    };
    // The edge-signed visitor identity is validated by the API before it is
    // used for throttling; client-supplied forwarding headers are not trusted.
    const signedVisitor = request.headers.get("x-cadivor-visitor") || "";
    if (signedVisitor) forwardHeaders["X-Cadivor-Visitor"] = signedVisitor;
    const upstream = await fetch(`${apiBase()}/public/contact`, {
      method: "POST",
      headers: forwardHeaders,
      body: JSON.stringify(parsed),
      cache: "no-store",
    });
    return jsonResponse(upstream, headers);
  } catch {
    return NextResponse.json(
      { detail: "Contact requests are temporarily unavailable. Please try again or email info@cadivor.com." },
      { status: 503, headers },
    );
  }
}
