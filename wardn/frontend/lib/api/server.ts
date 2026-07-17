import { cookies, headers } from "next/headers";
import { forbidden, notFound, redirect } from "next/navigation";
import { cache } from "react";

import { ApiError, readApiResponseBody } from "./errors";

const backendUrl = process.env.WARDN_BACKEND_URL ?? "http://127.0.0.1:8000";
const defaultTimeoutMs = 30_000;

export type BackendRequestOptions = RequestInit & {
  timeoutMs?: number;
};

export function backendPath(path: string) {
  return `${backendUrl}${path}`;
}

const cachedBackendCookieHeader = cache(async () => {
  const cookieStore = await cookies();
  return cookieStore
    .getAll()
    .map((cookie) => `${cookie.name}=${cookie.value}`)
    .join("; ");
});

export async function backendCookieHeader() {
  return cachedBackendCookieHeader();
}

async function loginPath() {
  const requestHeaders = await headers();
  const next = requestHeaders.get("x-wardn-pathname") || "/org";
  return `/login?reauth=1&next=${encodeURIComponent(next)}`;
}

export async function backendFetch(path: string, options: BackendRequestOptions = {}) {
  const { timeoutMs = defaultTimeoutMs, ...init } = options;
  const cookieHeader = await backendCookieHeader();
  const requestHeaders = new Headers(init.headers);
  if (cookieHeader && !requestHeaders.has("cookie")) {
    requestHeaders.set("cookie", cookieHeader);
  }
  let response: Response;
  try {
    response = await fetch(backendPath(path), {
      cache: "no-store",
      ...init,
      headers: requestHeaders,
      signal: init.signal
        ? AbortSignal.any([init.signal, AbortSignal.timeout(timeoutMs)])
        : AbortSignal.timeout(timeoutMs),
    });
  } catch (cause) {
    throw new ApiError(0, undefined, "Wardn API is unavailable.", { cause });
  }

  if (response.status === 401) {
    redirect(await loginPath());
  }
  if (response.status === 403) {
    forbidden();
  }
  if (response.status === 404) {
    notFound();
  }
  return response;
}

export async function backendJson<T>(path: string, options: BackendRequestOptions = {}): Promise<T> {
  const response = await backendFetch(path, options);
  const body = await readApiResponseBody(response);
  if (!response.ok) {
    throw new ApiError(response.status, body, `Wardn API request failed (${response.status}).`);
  }
  if (body === undefined) {
    throw new ApiError(502, body, "Wardn API returned an empty response.");
  }
  return body as T;
}
