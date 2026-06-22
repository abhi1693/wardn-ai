import { NextResponse } from "next/server";

import { backendContentHeaders, selectedWorkspaceMcpPath } from "@/app/api/_lib/workspace";

export async function POST(request: Request) {
  const payload = await request.json();
  const path = await selectedWorkspaceMcpPath(request, "/registry/installed-servers/updates");
  if (!path) {
    return NextResponse.json({ detail: "workspace is not selected" }, { status: 400 });
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
