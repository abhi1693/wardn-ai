import { proxyOauthRequest } from "@/app/api/_lib/mcp-oauth";

export async function POST(request: Request) {
  return proxyOauthRequest(request, "/api/v1/mcp/gateway", {
    method: "POST",
    rewriteAuthenticate: true,
  });
}
