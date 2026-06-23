import { proxyBackend } from "@/app/api/_lib/backend";

type RouteContext = {
  params: Promise<{ organizationId: string; workspaceId: string; agentId: string }>;
};

export async function POST(request: Request, context: RouteContext) {
  const { organizationId, workspaceId, agentId } = await context.params;
  const payload = await request.json();
  return proxyBackend(
    request,
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/workspaces/${encodeURIComponent(workspaceId)}/agents/${encodeURIComponent(agentId)}/chat`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}
