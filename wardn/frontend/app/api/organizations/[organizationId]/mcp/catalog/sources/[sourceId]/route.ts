import { proxyBackend } from "@/app/api/_lib/backend";

type RouteContext = {
  params: Promise<{ organizationId: string; sourceId: string }>;
};

function sourcePath(organizationId: string, sourceId: string) {
  return `/api/v1/organizations/${encodeURIComponent(
    organizationId
  )}/mcp/catalog/sources/${encodeURIComponent(sourceId)}`;
}

export async function GET(request: Request, context: RouteContext) {
  const { organizationId, sourceId } = await context.params;
  return proxyBackend(request, sourcePath(organizationId, sourceId));
}

export async function PATCH(request: Request, context: RouteContext) {
  const { organizationId, sourceId } = await context.params;
  const payload = await request.json();
  return proxyBackend(request, sourcePath(organizationId, sourceId), {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function DELETE(request: Request, context: RouteContext) {
  const { organizationId, sourceId } = await context.params;
  return proxyBackend(request, sourcePath(organizationId, sourceId), {
    method: "DELETE",
  });
}
