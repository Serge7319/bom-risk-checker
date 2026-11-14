import type { NextRequest } from "next/server";
import { proxyPublicBomLead } from "@/lib/publicBomProxy";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  return proxyPublicBomLead(request);
}
