import { NextResponse } from "next/server";

import { backendUrl, copySetCookieHeaders, oidcErrorRedirect } from "../_lib";

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
    return oidcErrorRedirect(request);
  }

  const location = response.headers.get("location");
  const nextResponse =
    location && response.status >= 300 && response.status < 400
      ? NextResponse.redirect(location, { status: response.status })
      : oidcErrorRedirect(request);
  copySetCookieHeaders(response, nextResponse);
  return nextResponse;
}
