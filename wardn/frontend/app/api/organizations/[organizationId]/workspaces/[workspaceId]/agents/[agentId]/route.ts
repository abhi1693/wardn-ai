import { proxyBackend } from "@/app/api/_lib/backend";

type RouteContext = {
  params: Promise<{ organizationId: string; workspaceId: string; agentId: string }>;
};

function agentPath(organizationId: string, workspaceId: string, agentId: string) {
  return `/api/v1/organizations/${encodeURIComponent(
    organizationId
  )}/workspaces/${encodeURIComponent(workspaceId)}/agents/${encodeURIComponent(agentId)}`;
}

export async function PATCH(request: Request, context: RouteContext) {
  const { organizationId, workspaceId, agentId } = await context.params;
  const payload = await request.json();
  return proxyBackend(request, agentPath(organizationId, workspaceId, agentId), {
    method: "PATCH",
    body: JSON.stringify({ ...payload, scope: "workspace", workspaceId }),
  });
}

export async function DELETE(request: Request, context: RouteContext) {
  const { organizationId, workspaceId, agentId } = await context.params;
  return proxyBackend(request, agentPath(organizationId, workspaceId, agentId), {
    method: "DELETE",
  });
}
