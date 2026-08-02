import { NextRequest } from "next/server";

import { backendPath } from "@/lib/api/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const requestHeaderBlocklist = new Set([
  "connection",
  "content-length",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

const responseHeaderBlocklist = new Set([
  "connection",
  "content-encoding",
  "content-length",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

type ResponseHeadersWithCookies = Headers & {
  getSetCookie?: () => string[];
};

function forwardedRequestHeaders(request: NextRequest) {
  const headers = new Headers(request.headers);
  for (const name of requestHeaderBlocklist) {
    headers.delete(name);
  }
  headers.set("x-forwarded-host", request.nextUrl.host);
  headers.set("x-forwarded-proto", request.nextUrl.protocol.replace(":", ""));
  return headers;
}

function forwardedResponseHeaders(response: Response) {
  const headers = new Headers(response.headers);
  for (const name of responseHeaderBlocklist) {
    headers.delete(name);
  }

  const setCookieHeaders = (response.headers as ResponseHeadersWithCookies).getSetCookie?.();
  if (setCookieHeaders?.length) {
    headers.delete("set-cookie");
    for (const cookie of setCookieHeaders) {
      headers.append("set-cookie", cookie);
    }
  }
  return headers;
}

function backendProxyUrl(request: NextRequest) {
  return backendPath(`${request.nextUrl.pathname}${request.nextUrl.search}`);
}

async function proxyBackendRequest(request: NextRequest) {
  const method = request.method.toUpperCase();
  const response = await fetch(backendProxyUrl(request), {
    body: method === "GET" || method === "HEAD" ? undefined : request.body,
    cache: "no-store",
    duplex: "half",
    headers: forwardedRequestHeaders(request),
    method,
    redirect: "manual",
  } as RequestInit & { duplex: "half" });

  return new Response(method === "HEAD" ? null : response.body, {
    headers: forwardedResponseHeaders(response),
    status: response.status,
    statusText: response.statusText,
  });
}

export async function GET(request: NextRequest) {
  return proxyBackendRequest(request);
}

export async function HEAD(request: NextRequest) {
  return proxyBackendRequest(request);
}

export async function POST(request: NextRequest) {
  return proxyBackendRequest(request);
}

export async function PUT(request: NextRequest) {
  return proxyBackendRequest(request);
}

export async function PATCH(request: NextRequest) {
  return proxyBackendRequest(request);
}

export async function DELETE(request: NextRequest) {
  return proxyBackendRequest(request);
}
