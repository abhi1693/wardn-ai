import { proxyBackend } from "@/app/api/_lib/backend";

type RouteContext = {
  params: Promise<{ organizationId: string; priceId: string }>;
};

function pricePath(organizationId: string, priceId: string) {
  return `/api/v1/organizations/${encodeURIComponent(
    organizationId
  )}/observability/llm/model-prices/${encodeURIComponent(priceId)}`;
}

export async function PATCH(request: Request, context: RouteContext) {
  const { organizationId, priceId } = await context.params;
  const payload = await request.json();
  return proxyBackend(request, pricePath(organizationId, priceId), {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function DELETE(request: Request, context: RouteContext) {
  const { organizationId, priceId } = await context.params;
  return proxyBackend(request, pricePath(organizationId, priceId), {
    method: "DELETE",
  });
}

