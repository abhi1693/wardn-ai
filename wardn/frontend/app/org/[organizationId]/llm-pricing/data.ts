import type { UserRead } from "@/lib/api/generated/model";
import { backendCookieHeader, backendPath } from "@/lib/workspace-context";

import type { LLMModelPriceRead } from "./types";

type LLMModelPriceListResponse = {
  prices: LLMModelPriceRead[];
};

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

export async function getModelPrices(organizationId: string) {
  const cookie = await backendCookieHeader();
  try {
    const response = await fetch(
      backendPath(
        `/api/v1/organizations/${encodeURIComponent(
          organizationId
        )}/observability/llm/model-prices`
      ),
      {
        cache: "no-store",
        headers: cookie ? { cookie } : {},
      }
    );
    if (!response.ok) {
      return [] as LLMModelPriceRead[];
    }
    const payload = (await response.json()) as LLMModelPriceListResponse;
    return payload.prices;
  } catch {
    return [] as LLMModelPriceRead[];
  }
}

export function getModelPriceById(prices: LLMModelPriceRead[], priceId: string) {
  return prices.find((price) => price.id === priceId) ?? null;
}

export function canManageModelPrices(
  currentUser: UserRead | null,
  organizationRole: string,
) {
  return (
    Boolean(currentUser?.is_superuser) ||
    organizationRole === "owner" ||
    organizationRole === "admin"
  );
}
