import { proxyBackend } from "@/app/api/_lib/backend";

type RouteContext = {
  params: Promise<{ organizationId: string; sourceId: string }>;
};

export async function POST(request: Request, context: RouteContext) {
  const { organizationId, sourceId } = await context.params;
  return proxyBackend(
    request,
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/mcp/catalog/sources/${encodeURIComponent(sourceId)}/sync`,
    {
      method: "POST",
    }
  );
}
