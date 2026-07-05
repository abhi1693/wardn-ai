import { proxyBackend } from "@/app/api/_lib/backend";

type RouteContext = {
  params: Promise<{
    agentId: string;
    approvalId: string;
    organizationId: string;
    workspaceId: string;
  }>;
};

export async function POST(request: Request, context: RouteContext) {
  const { agentId, approvalId, organizationId, workspaceId } = await context.params;
  const payload = await request.json();
  return proxyBackend(
    request,
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/workspaces/${encodeURIComponent(workspaceId)}/agents/${encodeURIComponent(
      agentId
    )}/tool-approvals/${encodeURIComponent(approvalId)}`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}
