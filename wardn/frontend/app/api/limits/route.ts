import { proxyBackend } from "@/app/api/_lib/backend";

export async function GET(request: Request) {
  const search = new URL(request.url).search;
  return proxyBackend(request, `/api/v1/limits${search}`);
}

export async function PUT(request: Request) {
  const payload = await request.json();
  return proxyBackend(request, "/api/v1/limits", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}
