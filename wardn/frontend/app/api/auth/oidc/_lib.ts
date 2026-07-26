import { NextResponse } from "next/server";

const configuredSiteUrl = process.env.NEXT_PUBLIC_SITE_URL;

export const backendUrl = (process.env.WARDN_BACKEND_URL ?? "http://127.0.0.1:8000").replace(
  /\/+$/,
  ""
);

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

function requestPublicOrigin(request: Request) {
  const forwardedHost = request.headers.get("x-forwarded-host")?.split(",", 1)[0]?.trim();
  const forwardedProtocol = request.headers.get("x-forwarded-proto")?.split(",", 1)[0]?.trim();

  if (forwardedHost && (forwardedProtocol === "http" || forwardedProtocol === "https")) {
    try {
      return new URL(`${forwardedProtocol}://${forwardedHost}`).origin;
    } catch {
      // Fall back to the URL reconstructed by Next.js.
    }
  }
  return new URL(request.url).origin;
}

export function canonicalPublicUrl(path: string, request: Request) {
  if (!configuredSiteUrl?.trim()) {
    return null;
  }

  try {
    const target = new URL(path, configuredSiteUrl);
    return target.origin === requestPublicOrigin(request) ? null : target;
  } catch {
    return null;
  }
}

export function oidcErrorRedirect(request: Request) {
  return NextResponse.redirect(publicUrl("/login?error=oidc", request));
}
