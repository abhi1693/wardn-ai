import { NextResponse } from "next/server";

import { backendContentHeaders, selectedWorkspaceMcpPath } from "@/app/api/_lib/workspace";

export async function POST(request: Request) {
  const payload = await request.json();
  const path = await selectedWorkspaceMcpPath(request, "/gateway");
  if (!path) {
    return NextResponse.json({
      jsonrpc: "2.0",
      id: typeof payload === "object" && payload && "id" in payload ? payload.id : null,
      error: { code: -32602, message: "workspace is not selected" },
    });
  }
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      cookie: request.headers.get("cookie") ?? "",
    },
    body: JSON.stringify(payload),
    cache: "no-store",
  });

  const body = await response.text();
  return new NextResponse(body, {
    status: response.status,
    headers: backendContentHeaders(response),
  });
}
