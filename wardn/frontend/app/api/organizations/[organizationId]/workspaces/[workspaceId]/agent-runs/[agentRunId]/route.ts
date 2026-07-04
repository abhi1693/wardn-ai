import { proxyBackend } from "@/app/api/_lib/backend";

type RouteContext = {
  params: Promise<{ organizationId: string; workspaceId: string; agentRunId: string }>;
};

export async function GET(request: Request, context: RouteContext) {
  const { organizationId, workspaceId, agentRunId } = await context.params;
  return proxyBackend(
    request,
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/workspaces/${encodeURIComponent(workspaceId)}/agent-runs/${encodeURIComponent(agentRunId)}`
  );
}
