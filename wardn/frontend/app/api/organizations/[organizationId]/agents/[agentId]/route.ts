import { proxyBackend } from "@/app/api/_lib/backend";

type RouteContext = {
  params: Promise<{ organizationId: string; agentId: string }>;
};

function agentPath(organizationId: string, agentId: string) {
  return `/api/v1/organizations/${encodeURIComponent(organizationId)}/agents/${encodeURIComponent(
    agentId
  )}`;
}

export async function PATCH(request: Request, context: RouteContext) {
  const { organizationId, agentId } = await context.params;
  const payload = await request.json();
  return proxyBackend(request, agentPath(organizationId, agentId), {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function DELETE(request: Request, context: RouteContext) {
  const { organizationId, agentId } = await context.params;
  return proxyBackend(request, agentPath(organizationId, agentId), {
    method: "DELETE",
  });
}

