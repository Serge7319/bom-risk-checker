import { NextRequest, NextResponse } from "next/server";

/**
 * Marketing iframe and direct links still use `/?public=stress`.
 * Redirect to the Next.js public audit page before the authenticated home gate.
 */
export function middleware(request: NextRequest) {
  const { pathname, searchParams } = request.nextUrl;
  if (pathname !== "/") return NextResponse.next();
  if ((searchParams.get("public") || "").trim().toLowerCase() !== "stress") {
    return NextResponse.next();
  }

  const target = request.nextUrl.clone();
  target.pathname = "/public-bom-audit";
  target.searchParams.delete("public");
  return NextResponse.redirect(target);
}

export const config = {
  matcher: ["/"],
};
