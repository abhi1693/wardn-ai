import { NextResponse } from "next/server";

const backendUrl = process.env.WARDN_BACKEND_URL ?? "http://127.0.0.1:8000";

type RouteContext = {
  params: Promise<{
    installationId: string;
  }>;
};

export async function DELETE(_: Request, context: RouteContext) {
  const { installationId } = await context.params;
  const response = await fetch(
    `${backendUrl}/api/v1/mcp/registry/installed-server-configs/${encodeURIComponent(installationId)}`,
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
