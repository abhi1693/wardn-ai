import { proxyBackend } from "@/app/api/_lib/backend";

type RouteContext = {
  params: Promise<{ organizationId: string; storeId: string }>;
};

export async function POST(request: Request, context: RouteContext) {
  const { organizationId, storeId } = await context.params;
  return proxyBackend(
    request,
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/secrets/stores/${encodeURIComponent(storeId)}/validate`,
    {
      method: "POST",
    }
  );
}
