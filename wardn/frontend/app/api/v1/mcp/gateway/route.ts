import { NextResponse } from "next/server";

import { bearerChallenge, proxyOauthRequest } from "@/app/api/_lib/mcp-oauth";

export async function GET(request: Request) {
  return NextResponse.json(
    { detail: "gateway bearer token required" },
    {
      status: 401,
      headers: {
        "WWW-Authenticate": bearerChallenge(request),
      },
    },
  );
}

export async function POST(request: Request) {
  return proxyOauthRequest(request, "/api/v1/mcp/gateway", {
    method: "POST",
    rewriteAuthenticate: true,
  });
}
