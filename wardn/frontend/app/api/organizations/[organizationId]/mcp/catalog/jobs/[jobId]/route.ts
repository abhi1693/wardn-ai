import { proxyBackend } from "@/app/api/_lib/backend";

type RouteContext = {
  params: Promise<{ organizationId: string; jobId: string }>;
};

export async function GET(request: Request, context: RouteContext) {
  const { organizationId, jobId } = await context.params;
  return proxyBackend(
    request,
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/mcp/catalog/jobs/${encodeURIComponent(jobId)}`
  );
}
