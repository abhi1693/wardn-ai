import { proxyBackend } from "@/app/api/_lib/backend";

type RouteContext = {
  params: Promise<{ organizationId: string }>;
};

export async function GET(request: Request, context: RouteContext) {
  const { organizationId } = await context.params;
  const search = new URL(request.url).search;
  return proxyBackend(
    request,
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/usage/summary${search}`
  );
}
