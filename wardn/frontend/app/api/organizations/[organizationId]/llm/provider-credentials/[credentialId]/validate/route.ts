import { proxyBackend } from "@/app/api/_lib/backend";

type RouteContext = {
  params: Promise<{ organizationId: string; credentialId: string }>;
};

export async function POST(request: Request, context: RouteContext) {
  const { organizationId, credentialId } = await context.params;
  return proxyBackend(
    request,
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/llm/provider-credentials/${encodeURIComponent(credentialId)}/validate`,
    { method: "POST" }
  );
}
