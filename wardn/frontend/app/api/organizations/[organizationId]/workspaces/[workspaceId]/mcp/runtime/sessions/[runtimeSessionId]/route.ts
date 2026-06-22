import { proxyBackend } from "@/app/api/_lib/backend";

type RouteContext = {
  params: Promise<{
    organizationId: string;
    workspaceId: string;
    runtimeSessionId: string;
  }>;
};

export async function GET(request: Request, context: RouteContext) {
  const { organizationId, workspaceId, runtimeSessionId } = await context.params;
  return proxyBackend(
    request,
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/workspaces/${encodeURIComponent(
      workspaceId
    )}/mcp/runtime/sessions/${encodeURIComponent(runtimeSessionId)}`,
  );
}
