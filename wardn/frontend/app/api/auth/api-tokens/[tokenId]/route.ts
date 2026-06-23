import { proxyBackend } from "@/app/api/_lib/backend";

type RouteContext = {
  params: Promise<{ tokenId: string }>;
};

export async function PATCH(request: Request, context: RouteContext) {
  const { tokenId } = await context.params;
  const payload = await request.json();
  return proxyBackend(request, `/api/v1/auth/api-tokens/${encodeURIComponent(tokenId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function DELETE(request: Request, context: RouteContext) {
  const { tokenId } = await context.params;
  return proxyBackend(request, `/api/v1/auth/api-tokens/${encodeURIComponent(tokenId)}`, {
    method: "DELETE",
  });
}
