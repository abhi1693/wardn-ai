import { proxyBackend } from "@/app/api/_lib/backend";

export async function GET(request: Request) {
  return proxyBackend(request, "/api/v1/organizations");
}

export async function POST(request: Request) {
  const payload = await request.json();
  return proxyBackend(request, "/api/v1/organizations", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
