import type { NextRequest } from "next/server";
import { proxyPublicBomAudit } from "@/lib/publicBomProxy";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  return proxyPublicBomAudit(request);
}
