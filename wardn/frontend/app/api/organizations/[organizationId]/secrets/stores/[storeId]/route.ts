import { proxyBackend } from "@/app/api/_lib/backend";

type RouteContext = {
  params: Promise<{ organizationId: string; storeId: string }>;
};

function storePath(organizationId: string, storeId: string) {
  return `/api/v1/organizations/${encodeURIComponent(
    organizationId
  )}/secrets/stores/${encodeURIComponent(storeId)}`;
}

export async function GET(request: Request, context: RouteContext) {
  const { organizationId, storeId } = await context.params;
  return proxyBackend(request, storePath(organizationId, storeId));
}

export async function PATCH(request: Request, context: RouteContext) {
  const { organizationId, storeId } = await context.params;
  const payload = await request.json();
  return proxyBackend(request, storePath(organizationId, storeId), {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function DELETE(request: Request, context: RouteContext) {
  const { organizationId, storeId } = await context.params;
  return proxyBackend(request, storePath(organizationId, storeId), {
    method: "DELETE",
  });
}
