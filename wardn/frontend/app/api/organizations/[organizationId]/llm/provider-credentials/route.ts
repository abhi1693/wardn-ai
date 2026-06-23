import { proxyBackend } from "@/app/api/_lib/backend";

type RouteContext = {
  params: Promise<{ organizationId: string }>;
};

export async function GET(request: Request, context: RouteContext) {
  const { organizationId } = await context.params;
  return proxyBackend(
    request,
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/llm/provider-credentials`
  );
}

export async function POST(request: Request, context: RouteContext) {
  const { organizationId } = await context.params;
  const payload = await request.json();
  return proxyBackend(
    request,
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/llm/provider-credentials`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

