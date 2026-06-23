import { proxyBackend } from "@/app/api/_lib/backend";

type RouteContext = {
  params: Promise<{ organizationId: string; agentId: string }>;
};

export async function POST(request: Request, context: RouteContext) {
  const { organizationId, agentId } = await context.params;
  const payload = await request.json();
  return proxyBackend(
    request,
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/agents/${encodeURIComponent(
      agentId
    )}/chat`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}
