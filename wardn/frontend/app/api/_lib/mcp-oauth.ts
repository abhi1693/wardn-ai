import { NextResponse } from "next/server";

const backendUrl = process.env.WARDN_BACKEND_URL ?? "http://127.0.0.1:8000";
const oauthScope = "mcp:tools";

type HeadersWithSetCookie = Headers & {
  getSetCookie?: () => string[];
};

function copySetCookieHeaders(source: Response, target: Headers) {
  const headers = source.headers as HeadersWithSetCookie;
  const cookies = headers.getSetCookie?.() ?? [];

  if (cookies.length > 0) {
    for (const cookie of cookies) {
      target.append("set-cookie", cookie);
    }
    return;
  }

  const cookie = source.headers.get("set-cookie");
  if (cookie) {
    target.set("set-cookie", cookie);
  }
}

function backendApiUrl(path: string, requestUrl: string) {
  const url = new URL(path, backendUrl);
  url.search = new URL(requestUrl).search;
  return url;
}

function forwardedHeaders(request: Request) {
  const headers: Record<string, string> = {};
  for (const name of ["accept", "authorization", "content-type", "cookie"]) {
    const value = request.headers.get(name);
    if (value) {
      headers[name] = value;
    }
  }
  const url = new URL(request.url);
  headers["x-forwarded-host"] = url.host;
  headers["x-forwarded-proto"] = url.protocol.replace(":", "");
  return headers;
}

function frontendOrigin(request: Request) {
  return new URL(request.url).origin;
}

function rewriteBearerChallenge(value: string, request: Request) {
  const backendOrigin = new URL(backendUrl).origin;
  return value.replace(
    `${backendOrigin}/.well-known/oauth-protected-resource`,
    `${frontendOrigin(request)}/.well-known/oauth-protected-resource`,
  );
}

export function protectedResourceMetadata(request: Request) {
  const origin = frontendOrigin(request);
  return NextResponse.json({
    resource: `${origin}/api/v1/mcp/gateway`,
    authorization_servers: [origin],
    scopes_supported: [oauthScope],
    bearer_methods_supported: ["header"],
  });
}

export function authorizationServerMetadata(request: Request) {
  const origin = frontendOrigin(request);
  return NextResponse.json({
    issuer: origin,
    authorization_endpoint: `${origin}/api/v1/oauth/authorize`,
    token_endpoint: `${origin}/api/v1/oauth/token`,
    registration_endpoint: `${origin}/api/v1/oauth/register`,
    response_types_supported: ["code"],
    grant_types_supported: ["authorization_code"],
    code_challenge_methods_supported: ["S256"],
    token_endpoint_auth_methods_supported: ["none"],
    scopes_supported: [oauthScope],
    resource_parameter_supported: true,
  });
}

export async function proxyOauthRequest(
  request: Request,
  path: string,
  init: { method: "GET" | "POST"; rewriteAuthenticate?: boolean },
) {
  let response: Response;
  try {
    response = await fetch(backendApiUrl(path, request.url), {
      method: init.method,
      headers: forwardedHeaders(request),
      body: init.method === "POST" ? await request.text() : undefined,
      cache: "no-store",
      redirect: "manual",
    });
  } catch {
    return NextResponse.json({ detail: "MCP OAuth service unavailable" }, { status: 503 });
  }

  const headers = new Headers();
  for (const name of ["cache-control", "content-type", "location"]) {
    const value = response.headers.get(name);
    if (value) {
      headers.set(name, value);
    }
  }

  const authenticate = response.headers.get("www-authenticate");
  if (authenticate) {
    headers.set(
      "www-authenticate",
      init.rewriteAuthenticate ? rewriteBearerChallenge(authenticate, request) : authenticate,
    );
  }

  copySetCookieHeaders(response, headers);
  const hasBody = ![204, 205, 304].includes(response.status);
  return new NextResponse(hasBody ? await response.text() : null, {
    status: response.status,
    headers,
  });
}
