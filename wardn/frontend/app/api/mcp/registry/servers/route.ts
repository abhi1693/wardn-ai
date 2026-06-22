import { NextResponse } from "next/server";

import {
  backendContentHeaders,
  selectedOrganizationMcpRegistryPath,
} from "@/app/api/_lib/workspace";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const path = await selectedOrganizationMcpRegistryPath(request, `/servers${url.search}`);
  if (!path) {
    return NextResponse.json({ servers: [], metadata: { count: 0, nextCursor: "" } });
  }

  const response = await fetch(path, {
    cache: "no-store",
    headers: {
      cookie: request.headers.get("cookie") ?? "",
    },
  });

  const body = await response.text();
  return new NextResponse(body, {
    status: response.status,
    headers: backendContentHeaders(response),
  });
}

export async function POST(request: Request) {
  const payload = await request.json();
  const path = await selectedOrganizationMcpRegistryPath(request, "/servers");
  if (!path) {
    return NextResponse.json({ detail: "organization is not selected" }, { status: 404 });
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
