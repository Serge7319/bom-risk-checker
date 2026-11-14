import type { NextRequest } from "next/server";
import { proxyPublicBomStatus } from "@/lib/publicBomProxy";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  return proxyPublicBomStatus(request);
}
