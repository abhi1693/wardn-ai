import type { UserRead } from "@/lib/api/generated/model";
import { backendCookieHeader, backendPath } from "@/lib/workspace-context";

export type LLMModelPriceRead = {
  id: string;
  provider: string;
  model: string;
  inputUsdPer1mTokens: string | number;
  outputUsdPer1mTokens: string | number;
  cacheReadUsdPer1mTokens: string | number | null;
  cacheWriteUsdPer1mTokens: string | number | null;
  createdAt: string;
  updatedAt: string;
};

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

