import { NextResponse } from "next/server";

const backendUrl = process.env.WARDN_BACKEND_URL ?? "http://127.0.0.1:8000";

type RouteContext = {
  params: Promise<{
    installationId: string;
  }>;
};

export async function POST(request: Request, context: RouteContext) {
  const payload = await request.json();
  const { installationId } = await context.params;
  const response = await fetch(
    `${backendUrl}/api/v1/mcp/registry/installed-server-configs/${encodeURIComponent(
      installationId
    )}/validate-tool`,
    {
      method: "POST",
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
