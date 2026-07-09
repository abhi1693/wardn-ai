import { protectedResourceMetadata } from "@/app/api/_lib/mcp-oauth";

type ResourceRouteContext = {
  params: Promise<{ resource: string[] }> | { resource: string[] };
};

export async function GET(request: Request, context: ResourceRouteContext) {
  const params = await context.params;
  return protectedResourceMetadata(request, params.resource);
}
