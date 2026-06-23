import { proxyBackend } from "@/app/api/_lib/backend";

type RouteContext = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

function agentsPath(organizationId: string, workspaceId: string) {
  return `/api/v1/organizations/${encodeURIComponent(
    organizationId
  )}/workspaces/${encodeURIComponent(workspaceId)}/agents`;
}

export async function GET(request: Request, context: RouteContext) {
  const { organizationId, workspaceId } = await context.params;
  return proxyBackend(request, agentsPath(organizationId, workspaceId), {
    method: "GET",
  });
}

export async function POST(request: Request, context: RouteContext) {
  const { organizationId, workspaceId } = await context.params;
  const payload = await request.json();
  return proxyBackend(request, agentsPath(organizationId, workspaceId), {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
