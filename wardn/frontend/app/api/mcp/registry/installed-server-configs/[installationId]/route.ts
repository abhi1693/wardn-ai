import { NextResponse } from "next/server";

import { backendContentHeaders, selectedWorkspaceMcpPath } from "@/app/api/_lib/workspace";

type RouteContext = {
  params: Promise<{
    installationId: string;
  }>;
};

export async function DELETE(request: Request, context: RouteContext) {
  const { installationId } = await context.params;
  const path = await selectedWorkspaceMcpPath(
    request,
    `/registry/installed-server-configs/${encodeURIComponent(installationId)}`
  );
  if (!path) {
    return NextResponse.json({ detail: "workspace is not selected" }, { status: 400 });
  }
  const response = await fetch(
    path,
    {
      method: "DELETE",
      headers: { cookie: request.headers.get("cookie") ?? "" },
      cache: "no-store",
    }
  );

  if (response.status === 204) {
    return new NextResponse(null, { status: 204 });
  }

  const body = await response.text();
  return new NextResponse(body, {
    status: response.status,
    headers: backendContentHeaders(response),
  });
}
