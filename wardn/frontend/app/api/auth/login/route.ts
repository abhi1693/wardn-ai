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

export async function POST(request: Request) {
  const payload = await request.json();
  let response: Response;
  try {
    response = await fetch(`${backendUrl}/api/v1/auth/login`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
      },
      body: JSON.stringify(payload),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ detail: "sign in unavailable" }, { status: 503 });
  }

  const body = await response.text();
  const nextResponse = new NextResponse(body, {
    status: response.status,
    headers: {
      "content-type": response.headers.get("content-type") ?? "application/json",
    },
  });
  copySetCookieHeaders(response, nextResponse);
  return nextResponse;
}
