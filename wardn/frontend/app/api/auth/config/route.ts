import { proxyBackend } from "@/app/api/_lib/backend";

export async function GET(request: Request) {
  return proxyBackend(request, "/api/v1/auth/config");
}
