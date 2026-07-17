import type { UserRead } from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";

import type { LLMModelPriceRead } from "./types";

type LLMModelPriceListResponse = {
  prices: LLMModelPriceRead[];
};

export async function getModelPrices(organizationId: string) {
  const payload = await backendJson<LLMModelPriceListResponse>(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/observability/llm/model-prices`
  );
  return payload.prices;
}

export function getModelPriceById(prices: LLMModelPriceRead[], priceId: string) {
  return prices.find((price) => price.id === priceId) ?? null;
}

export function canManageModelPrices(
  currentUser: UserRead | null,
  organizationRole: string,
) {
  return (
    Boolean(currentUser?.isSuperuser) ||
    organizationRole === "owner" ||
    organizationRole === "admin"
  );
}
