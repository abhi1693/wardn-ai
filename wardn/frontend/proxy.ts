import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

const sessionCookieName = "wardn_session";
const loginPath = "/login";

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const hasSession = Boolean(request.cookies.get(sessionCookieName)?.value);

  if (pathname === loginPath) {
    if (!hasSession) {
      return NextResponse.next();
    }

    return NextResponse.redirect(new URL("/", request.url));
  }

  if (hasSession) {
    return NextResponse.next();
  }

  const loginUrl = new URL(loginPath, request.url);
  loginUrl.searchParams.set("next", `${pathname}${search}`);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|.*\\..*).*)"],
};
