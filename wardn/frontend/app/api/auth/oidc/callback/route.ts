import { NextResponse } from "next/server";

const backendUrl = process.env.WARDN_BACKEND_URL ?? "http://127.0.0.1:8000";

function copySetCookieHeaders(source: Response, target: NextResponse) {
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

export async function GET(request: Request) {
  const { search } = new URL(request.url);
  let response: Response;
  try {
    response = await fetch(`${backendUrl}/api/v1/auth/oidc/callback${search}`, {
      cache: "no-store",
      headers: {
        ...(request.headers.get("cookie") ? { cookie: request.headers.get("cookie") ?? "" } : {}),
      },
      redirect: "manual",
    });
  } catch {
    return NextResponse.redirect(new URL("/login?error=oidc", request.url));
  }

  const location = response.headers.get("location");
  const nextResponse =
    location && response.status >= 300 && response.status < 400
      ? NextResponse.redirect(location, { status: response.status })
      : NextResponse.redirect(new URL("/login?error=oidc", request.url));
  copySetCookieHeaders(response, nextResponse);
  return nextResponse;
}
