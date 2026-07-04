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
  const hasBody = ![204, 205, 304].includes(response.status);
  const headers: Record<string, string> = {};
  const contentType = response.headers.get("content-type");
  headers["content-type"] = contentType ?? "application/json";
  for (const headerName of [
    "cache-control",
    "x-accel-buffering",
    "x-vercel-ai-ui-message-stream",
  ]) {
    const value = response.headers.get(headerName);
    if (value) {
      headers[headerName] = value;
    }
  }
  return new NextResponse(hasBody ? response.body : null, {
    status: response.status,
    headers: hasBody ? headers : undefined,
  });
}
