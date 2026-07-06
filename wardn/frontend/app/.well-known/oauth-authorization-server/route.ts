import { authorizationServerMetadata } from "@/app/api/_lib/mcp-oauth";

export function GET(request: Request) {
  return authorizationServerMetadata(request);
}
