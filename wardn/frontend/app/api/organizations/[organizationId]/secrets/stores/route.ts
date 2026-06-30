import { proxyBackend } from "@/app/api/_lib/backend";

type RouteContext = {
  params: Promise<{ organizationId: string }>;
};

function storesPath(request: Request, organizationId: string) {
  const url = new URL(request.url);
  return `/api/v1/organizations/${encodeURIComponent(organizationId)}/secrets/stores${url.search}`;
}

export async function GET(request: Request, context: RouteContext) {
  const { organizationId } = await context.params;
  return proxyBackend(request, storesPath(request, organizationId));
}

export async function POST(request: Request, context: RouteContext) {
  const { organizationId } = await context.params;
  const payload = await request.json();
  return proxyBackend(request, storesPath(request, organizationId), {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
