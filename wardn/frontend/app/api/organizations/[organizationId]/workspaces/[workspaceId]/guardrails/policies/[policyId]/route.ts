import { proxyBackend } from "@/app/api/_lib/backend";

type RouteContext = {
  params: Promise<{ organizationId: string; workspaceId: string; policyId: string }>;
};

function policyPath(organizationId: string, workspaceId: string, policyId: string) {
  return `/api/v1/organizations/${encodeURIComponent(
    organizationId
  )}/workspaces/${encodeURIComponent(
    workspaceId
  )}/guardrails/policies/${encodeURIComponent(policyId)}`;
}

export async function GET(request: Request, context: RouteContext) {
  const { organizationId, workspaceId, policyId } = await context.params;
  return proxyBackend(request, policyPath(organizationId, workspaceId, policyId), {
    method: "GET",
  });
}

export async function PATCH(request: Request, context: RouteContext) {
  const { organizationId, workspaceId, policyId } = await context.params;
  const payload = await request.json();
  return proxyBackend(request, policyPath(organizationId, workspaceId, policyId), {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function DELETE(request: Request, context: RouteContext) {
  const { organizationId, workspaceId, policyId } = await context.params;
  return proxyBackend(request, policyPath(organizationId, workspaceId, policyId), {
    method: "DELETE",
  });
}
