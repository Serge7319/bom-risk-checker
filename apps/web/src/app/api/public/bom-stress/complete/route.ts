import type { NextRequest } from "next/server";
import { proxyPublicBomComplete } from "@/lib/publicBomProxy";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  return proxyPublicBomComplete(request);
}
