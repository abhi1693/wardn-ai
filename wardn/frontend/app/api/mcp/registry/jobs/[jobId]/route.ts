import { NextResponse } from "next/server";

import { backendContentHeaders, selectedWorkspaceMcpPath } from "@/app/api/_lib/workspace";

type RouteContext = {
  params: Promise<{ jobId: string }>;
};

export async function GET(request: Request, context: RouteContext) {
  const { jobId } = await context.params;
  const path = await selectedWorkspaceMcpPath(
    request,
    `/registry/jobs/${encodeURIComponent(jobId)}`
  );
  if (!path) {
    return NextResponse.json({ detail: "workspace is not selected" }, { status: 400 });
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
