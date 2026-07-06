import { proxyOauthRequest } from "@/app/api/_lib/mcp-oauth";

type OAuthRouteContext = {
  params: Promise<{ oauth: string[] }> | { oauth: string[] };
};

async function oauthPath(context: OAuthRouteContext) {
  const params = await context.params;
  return `/api/v1/oauth/${params.oauth.map(encodeURIComponent).join("/")}`;
}

export async function GET(request: Request, context: OAuthRouteContext) {
  return proxyOauthRequest(request, await oauthPath(context), { method: "GET" });
}

export async function POST(request: Request, context: OAuthRouteContext) {
  return proxyOauthRequest(request, await oauthPath(context), { method: "POST" });
}
