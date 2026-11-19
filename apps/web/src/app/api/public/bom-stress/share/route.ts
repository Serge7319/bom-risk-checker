import type { NextRequest } from "next/server";
import { proxyPublicBomShareCreate } from "@/lib/publicBomProxy";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  return proxyPublicBomShareCreate(request);
}
