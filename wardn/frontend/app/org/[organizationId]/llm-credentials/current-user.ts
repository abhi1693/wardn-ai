import type { UserRead } from "@/lib/api/generated/model";
import { backendCookieHeader, backendPath } from "@/lib/workspace-context";

export async function getCurrentUser() {
  const cookie = await backendCookieHeader();
  try {
    const response = await fetch(backendPath("/api/v1/auth/me"), {
      cache: "no-store",
      headers: cookie ? { cookie } : {},
    });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as UserRead;
  } catch {
    return null;
  }
}
