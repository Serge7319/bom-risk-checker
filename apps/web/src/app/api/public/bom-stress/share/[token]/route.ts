import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { proxyPublicBomSharedSummary } from "@/lib/publicBomProxy";

export const dynamic = "force-dynamic";

export async function GET(
  _request: NextRequest,
  context: { params: Promise<{ token: string }> },
) {
  const { token } = await context.params;
  if (!/^[A-Za-z0-9_-]{40,128}$/.test(token)) {
    return NextResponse.json({ detail: "This audit share link is invalid or expired." }, { status: 404 });
  }
  return proxyPublicBomSharedSummary(token);
}
