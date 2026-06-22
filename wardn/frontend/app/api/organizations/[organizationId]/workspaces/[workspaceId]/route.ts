import { proxyBackend } from "@/app/api/_lib/backend";

type RouteContext = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

export async function GET(request: Request, context: RouteContext) {
  const { organizationId, workspaceId } = await context.params;
  return proxyBackend(
    request,
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/workspaces/${encodeURIComponent(
      workspaceId
    )}`,
  );
}

export async function PUT(request: Request, context: RouteContext) {
  const { organizationId, workspaceId } = await context.params;
  const payload = await request.json();
  return proxyBackend(
    request,
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/workspaces/${encodeURIComponent(
      workspaceId
    )}`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
  );
}
