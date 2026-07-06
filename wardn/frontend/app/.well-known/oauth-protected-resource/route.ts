import { protectedResourceMetadata } from "@/app/api/_lib/mcp-oauth";

export function GET(request: Request) {
  return protectedResourceMetadata(request);
}
