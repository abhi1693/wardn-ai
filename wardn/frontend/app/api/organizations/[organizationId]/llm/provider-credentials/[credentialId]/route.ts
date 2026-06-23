import { proxyBackend } from "@/app/api/_lib/backend";

type RouteContext = {
  params: Promise<{ organizationId: string; credentialId: string }>;
};

function credentialPath(organizationId: string, credentialId: string) {
  return `/api/v1/organizations/${encodeURIComponent(
    organizationId
  )}/llm/provider-credentials/${encodeURIComponent(credentialId)}`;
}

export async function PATCH(request: Request, context: RouteContext) {
  const { organizationId, credentialId } = await context.params;
  const payload = await request.json();
  return proxyBackend(request, credentialPath(organizationId, credentialId), {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function DELETE(request: Request, context: RouteContext) {
  const { organizationId, credentialId } = await context.params;
  return proxyBackend(request, credentialPath(organizationId, credentialId), {
    method: "DELETE",
  });
}

