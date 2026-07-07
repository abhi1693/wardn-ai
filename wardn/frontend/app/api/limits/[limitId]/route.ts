import { proxyBackend } from "@/app/api/_lib/backend";

type LimitRouteContext = {
  params: Promise<{ limitId: string }> | { limitId: string };
};

export async function DELETE(request: Request, context: LimitRouteContext) {
  const { limitId } = await context.params;
  return proxyBackend(request, `/api/v1/limits/${encodeURIComponent(limitId)}`, {
    method: "DELETE",
  });
}
