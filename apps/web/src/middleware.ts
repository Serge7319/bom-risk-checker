import { NextRequest, NextResponse } from "next/server";

/**
 * Legacy marketing links used `/?public=stress` (authenticated home + query).
 * Prefer `/public-bom-audit` directly; this redirect keeps old embeds working
 * before the signed-in workspace home gate.
 */
export function middleware(request: NextRequest) {
  const { pathname, searchParams } = request.nextUrl;
  if (pathname !== "/") return NextResponse.next();

  // OTP / signup confirmation must reach /login before the authenticated home gate.
  const confirmMarker = (searchParams.get("cadivor_signup_confirm") || "")
    .trim()
    .toLowerCase();
  const hasTokenHash = Boolean((searchParams.get("token_hash") || "").trim());
  if (confirmMarker === "1" || confirmMarker === "true" || hasTokenHash) {
    const login = request.nextUrl.clone();
    login.pathname = "/login";
    return NextResponse.redirect(login);
  }

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
