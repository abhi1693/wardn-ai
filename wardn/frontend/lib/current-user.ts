import type { UserRead } from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";

export function getCurrentUser() {
  return backendJson<UserRead>("/api/v1/auth/me");
}
