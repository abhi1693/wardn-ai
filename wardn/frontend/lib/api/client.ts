import { ApiError, readApiResponseBody } from "./errors";

export { ApiError, apiErrorMessage } from "./errors";

const defaultTimeoutMs = 30_000;

declare global {
  interface Window {
    __WARDN_API_BASE_URL__?: string;
  }
}

export type ApiRequestOptions = RequestInit & {
  timeoutMs?: number;
};

function configuredApiBaseUrl() {
  if (typeof window !== "undefined") {
    const runtimeValue = window.__WARDN_API_BASE_URL__?.trim();
    if (runtimeValue) {
      return runtimeValue;
    }
  }
  return process.env.NEXT_PUBLIC_API_BASE_URL?.trim() ?? "";
}

export function apiBaseUrl() {
  return configuredApiBaseUrl().replace(/\/+$/, "");
}

export function apiUrl(path: string) {
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${apiBaseUrl()}${normalizedPath}`;
}

function requestSignal(signal: AbortSignal | null | undefined, timeoutMs: number) {
  const timeoutSignal = AbortSignal.timeout(timeoutMs);
  return signal ? AbortSignal.any([signal, timeoutSignal]) : timeoutSignal;
}

function redirectBrowserOnUnauthorized(response: Response) {
  if (
    response.status !== 401 ||
    typeof window === "undefined" ||
    window.location.pathname === "/login"
  ) {
    return;
  }
  const next = `${window.location.pathname}${window.location.search}`;
  window.location.assign(`/login?reauth=1&next=${encodeURIComponent(next)}`);
}

export async function apiRawFetch(path: string, options: ApiRequestOptions = {}) {
  const { timeoutMs = defaultTimeoutMs, ...init } = options;
  try {
    const response = await fetch(apiUrl(path), {
      cache: "no-store",
      credentials: "include",
      ...init,
      signal: requestSignal(init.signal, timeoutMs),
    });
    redirectBrowserOnUnauthorized(response);
    return response;
  } catch (cause) {
    throw new ApiError(0, undefined, "Wardn API is unavailable.", { cause });
  }
}

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  let response: Response;
  try {
    response = await apiRawFetch(path, options);
  } catch (cause) {
    if (cause instanceof ApiError) {
      throw cause;
    }
    throw new ApiError(0, undefined, "Wardn API is unavailable.", { cause });
  }
  const body = await readApiResponseBody(response);
  if (!response.ok) {
    throw new ApiError(response.status, body, `API request failed (${response.status})`);
  }
  return body as T;
}

export async function apiStreamFetch(input: RequestInfo | URL, init?: RequestInit) {
  const inputUrl =
    typeof input === "string"
      ? apiUrl(input)
      : input instanceof URL
        ? apiUrl(input.toString())
        : input;
  try {
    const response = await fetch(inputUrl, {
      credentials: "include",
      ...init,
    });
    redirectBrowserOnUnauthorized(response);
    return response;
  } catch (cause) {
    throw new ApiError(0, undefined, "Wardn API is unavailable.", { cause });
  }
}
