import { NextResponse } from "next/server";

import { backendContentHeaders, selectedWorkspaceMcpPath } from "@/app/api/_lib/workspace";

export async function GET(request: Request) {
  const path = await selectedWorkspaceMcpPath(request, "/registry/installed-servers");
  if (!path) {
    return NextResponse.json({ installations: [] });
  }
  const response = await fetch(path, {
    cache: "no-store",
    headers: { cookie: request.headers.get("cookie") ?? "" },
  });

  const body = await response.text();
  return new NextResponse(body, {
    status: response.status,
    headers: backendContentHeaders(response),
  });
}
