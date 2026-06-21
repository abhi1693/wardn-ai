import { NextResponse } from "next/server";

const backendUrl = process.env.WARDN_BACKEND_URL ?? "http://127.0.0.1:8000";

export async function GET() {
  const response = await fetch(`${backendUrl}/api/v1/mcp/registry/installed-servers`, {
    cache: "no-store",
  });

  const body = await response.text();
  return new NextResponse(body, {
    status: response.status,
    headers: {
      "content-type": response.headers.get("content-type") ?? "application/json",
    },
  });
}
