import { proxyBackend } from "@/app/api/_lib/backend";

export async function GET(request: Request) {
  const search = new URL(request.url).search;
  return proxyBackend(request, `/api/v1/me/usage${search}`);
}
