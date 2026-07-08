import { NextResponse } from "next/server";

const configuredSiteUrl = process.env.NEXT_PUBLIC_SITE_URL ?? process.env.WARDN_FRONTEND_BASE_URL;

export const backendUrl = process.env.WARDN_BACKEND_URL ?? "http://127.0.0.1:8000";

export function copySetCookieHeaders(source: Response, target: NextResponse) {
  const headers = source.headers as Headers & {
    getSetCookie?: () => string[];
  };
  const cookies = headers.getSetCookie?.() ?? [];

  if (cookies.length > 0) {
    for (const cookie of cookies) {
      target.headers.append("set-cookie", cookie);
    }
    return;
  }

  const cookie = source.headers.get("set-cookie");
  if (cookie) {
    target.headers.set("set-cookie", cookie);
  }
}

export function publicUrl(path: string, request: Request) {
  const fallbackOrigin = new URL(request.url).origin;
  const baseUrl = configuredSiteUrl?.trim() || fallbackOrigin;

  try {
    return new URL(path, baseUrl);
  } catch {
    return new URL(path, fallbackOrigin);
  }
}

export function oidcErrorRedirect(request: Request) {
  return NextResponse.redirect(publicUrl("/login?error=oidc", request));
}
