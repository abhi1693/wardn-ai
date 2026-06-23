import { NextResponse } from "next/server";

const backendUrl = process.env.WARDN_BACKEND_URL ?? "http://127.0.0.1:8000";

export function backendApiPath(path: string) {
  return `${backendUrl}${path}`;
}

export async function proxyBackend(
  request: Request,
  path: string,
  init: RequestInit = {},
) {
  const response = await fetch(backendApiPath(path), {
    ...init,
    cache: "no-store",
    headers: {
      ...(request.headers.get("cookie") ? { cookie: request.headers.get("cookie") ?? "" } : {}),
      ...(init.body ? { "content-type": "application/json" } : {}),
      ...init.headers,
    },
  });
  const body = await response.text();
  const hasBody = ![204, 205, 304].includes(response.status);
  return new NextResponse(hasBody ? body : null, {
    status: response.status,
    headers: hasBody
      ? {
          "content-type": response.headers.get("content-type") ?? "application/json",
        }
      : undefined,
  });
}
