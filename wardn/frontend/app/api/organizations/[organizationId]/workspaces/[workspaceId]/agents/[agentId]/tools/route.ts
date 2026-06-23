import { proxyBackend } from "@/app/api/_lib/backend";

type RouteContext = {
  params: Promise<{ organizationId: string; workspaceId: string; agentId: string }>;
};

function toolsPath(organizationId: string, workspaceId: string, agentId: string) {
  return `/api/v1/organizations/${encodeURIComponent(
    organizationId
  )}/workspaces/${encodeURIComponent(workspaceId)}/agents/${encodeURIComponent(agentId)}/tools`;
}

export async function GET(request: Request, context: RouteContext) {
  const { organizationId, workspaceId, agentId } = await context.params;
  return proxyBackend(request, toolsPath(organizationId, workspaceId, agentId), {
    method: "GET",
  });
}

export async function PUT(request: Request, context: RouteContext) {
  const { organizationId, workspaceId, agentId } = await context.params;
  const payload = await request.json();
  return proxyBackend(request, toolsPath(organizationId, workspaceId, agentId), {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}
