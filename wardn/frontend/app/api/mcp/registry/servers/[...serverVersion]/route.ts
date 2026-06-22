import { NextResponse } from "next/server";

import {
  backendContentHeaders,
  selectedOrganizationMcpRegistryPath,
} from "@/app/api/_lib/workspace";

type RouteContext = {
  params: Promise<{
    serverVersion: string[];
  }>;
};

function parsedPath(segments: string[]) {
  const version = segments.at(-1) ?? "";
  const serverName = segments.slice(0, -1);
  return {
    encodedServerName: serverName.map(encodeURIComponent).join("/"),
    version: encodeURIComponent(version),
  };
}

export async function GET(_: Request, context: RouteContext) {
  const { serverVersion } = await context.params;
  const { encodedServerName, version } = parsedPath(serverVersion);
  const path = await selectedOrganizationMcpRegistryPath(
    _,
    `/servers/${encodedServerName}/versions/${version}`
  );
  if (!path) {
    return NextResponse.json({ detail: "organization is not selected" }, { status: 404 });
  }
  const response = await fetch(path, {
    cache: "no-store",
    headers: {
      cookie: _.headers.get("cookie") ?? "",
    },
  });

  const body = await response.text();
  return new NextResponse(body, {
    status: response.status,
    headers: backendContentHeaders(response),
  });
}

export async function PUT(request: Request, context: RouteContext) {
  const payload = await request.json();
  const { serverVersion } = await context.params;
  const { encodedServerName, version } = parsedPath(serverVersion);
  const path = await selectedOrganizationMcpRegistryPath(
    request,
    `/servers/${encodedServerName}/versions/${version}`
  );
  if (!path) {
    return NextResponse.json({ detail: "organization is not selected" }, { status: 404 });
  }
  const response = await fetch(path, {
    method: "PUT",
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

export async function DELETE(request: Request, context: RouteContext) {
  const { serverVersion } = await context.params;
  const { encodedServerName, version } = parsedPath(serverVersion);
  const path = await selectedOrganizationMcpRegistryPath(
    request,
    `/servers/${encodedServerName}/versions/${version}`
  );
  if (!path) {
    return NextResponse.json({ detail: "organization is not selected" }, { status: 404 });
  }
  const response = await fetch(path, {
    method: "DELETE",
    cache: "no-store",
    headers: {
      cookie: request.headers.get("cookie") ?? "",
    },
  });

  if (response.status === 204) {
    return new NextResponse(null, { status: 204 });
  }

  const body = await response.text();
  return new NextResponse(body, {
    status: response.status,
    headers: backendContentHeaders(response),
  });
}
