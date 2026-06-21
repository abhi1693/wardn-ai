import { NextResponse } from "next/server";

const backendUrl = process.env.WARDN_BACKEND_URL ?? "http://127.0.0.1:8000";
const sessionCookieName = process.env.WARDN_SESSION_COOKIE_NAME ?? "wardn_session";

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

export async function POST() {
  let response: Response;
  try {
    response = await fetch(`${backendUrl}/api/v1/auth/logout`, {
      method: "POST",
      cache: "no-store",
    });
  } catch {
    const nextResponse = new NextResponse(null, {
      status: 204,
    });
    nextResponse.cookies.delete(sessionCookieName);
    return nextResponse;
  }

  const nextResponse = new NextResponse(null, {
    status: response.status,
  });
  copySetCookieHeaders(response, nextResponse);
  return nextResponse;
}
