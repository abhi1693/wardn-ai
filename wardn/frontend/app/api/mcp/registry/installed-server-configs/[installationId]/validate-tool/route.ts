import { NextResponse } from "next/server";

import { backendContentHeaders, selectedWorkspaceMcpPath } from "@/app/api/_lib/workspace";

type RouteContext = {
  params: Promise<{
    installationId: string;
  }>;
};

export async function POST(request: Request, context: RouteContext) {
  const payload = await request.json();
  const { installationId } = await context.params;
  const path = await selectedWorkspaceMcpPath(
    request,
    `/registry/installed-server-configs/${encodeURIComponent(installationId)}/validate-tool`
  );
  if (!path) {
    return NextResponse.json({ detail: "workspace is not selected" }, { status: 400 });
  }
  const response = await fetch(
    path,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        cookie: request.headers.get("cookie") ?? "",
      },
      body: JSON.stringify(payload),
      cache: "no-store",
    }
  );

  const body = await response.text();
  return new NextResponse(body, {
    status: response.status,
    headers: backendContentHeaders(response),
  });
}
