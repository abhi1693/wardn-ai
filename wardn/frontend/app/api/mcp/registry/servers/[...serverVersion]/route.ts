import { NextResponse } from "next/server";

const backendUrl = process.env.WARDN_BACKEND_URL ?? "http://127.0.0.1:8000";

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
  const response = await fetch(
    `${backendUrl}/api/v1/mcp/registry/servers/${encodedServerName}/versions/${version}`,
    { cache: "no-store" }
  );

  const body = await response.text();
  return new NextResponse(body, {
    status: response.status,
    headers: {
      "content-type": response.headers.get("content-type") ?? "application/json",
    },
  });
}

export async function PUT(request: Request, context: RouteContext) {
  const payload = await request.json();
  const { serverVersion } = await context.params;
  const { encodedServerName, version } = parsedPath(serverVersion);
  const response = await fetch(
    `${backendUrl}/api/v1/mcp/registry/servers/${encodedServerName}/versions/${version}`,
    {
      method: "PUT",
      headers: {
        "content-type": "application/json",
      },
      body: JSON.stringify(payload),
      cache: "no-store",
    }
  );

  const body = await response.text();
  return new NextResponse(body, {
    status: response.status,
    headers: {
      "content-type": response.headers.get("content-type") ?? "application/json",
    },
  });
}

export async function DELETE(_: Request, context: RouteContext) {
  const { serverVersion } = await context.params;
  const { encodedServerName, version } = parsedPath(serverVersion);
  const response = await fetch(
    `${backendUrl}/api/v1/mcp/registry/servers/${encodedServerName}/versions/${version}`,
    {
      method: "DELETE",
      cache: "no-store",
    }
  );

  if (response.status === 204) {
    return new NextResponse(null, { status: 204 });
  }

  const body = await response.text();
  return new NextResponse(body, {
    status: response.status,
    headers: {
      "content-type": response.headers.get("content-type") ?? "application/json",
    },
  });
}
