import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

const sessionCookieName = process.env.WARDN_SESSION_COOKIE_NAME?.trim() || "wardn_session";
const loginPath = "/login";
const organizationSelectionPath = "/org";

export function proxy(request: NextRequest) {
  const { pathname, search, searchParams } = request.nextUrl;
  const hasSession = Boolean(request.cookies.get(sessionCookieName)?.value);
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-wardn-pathname", `${pathname}${search}`);

  if (pathname === loginPath) {
    if (!hasSession || searchParams.get("reauth") === "1") {
      return NextResponse.next({ request: { headers: requestHeaders } });
    }

    return NextResponse.redirect(new URL(organizationSelectionPath, request.url));
  }

  if (hasSession) {
    return NextResponse.next({ request: { headers: requestHeaders } });
  }

  const loginUrl = new URL(loginPath, request.url);
  loginUrl.searchParams.set("next", `${pathname}${search}`);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ["/((?!api|\\.well-known|_next/static|_next/image|favicon.ico|.*\\..*).*)"],
};
