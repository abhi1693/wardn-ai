import { NextResponse } from "next/server";

import { backendContentHeaders, selectedWorkspaceMcpPath } from "@/app/api/_lib/workspace";

type RouteContext = {
  params: Promise<{
    serverName: string[];
  }>;
};

export async function PUT(request: Request, context: RouteContext) {
  const payload = await request.json();
  const { serverName } = await context.params;
  const encodedServerName = serverName.map(encodeURIComponent).join("/");
  const path = await selectedWorkspaceMcpPath(
    request,
    `/registry/installed-servers/${encodedServerName}`
  );
  if (!path) {
    return NextResponse.json({ detail: "workspace is not selected" }, { status: 400 });
  }
  const response = await fetch(
    path,
    {
      method: "PUT",
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


export async function DELETE(request: Request, context: RouteContext) {
  const { serverName } = await context.params;
  const encodedServerName = serverName.map(encodeURIComponent).join("/");
  const path = await selectedWorkspaceMcpPath(
    request,
    `/registry/installed-servers/${encodedServerName}`
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
