import type {
  LLMProviderCredentialListResponse,
  LLMProviderListResponse,
} from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";

import type { LlmCredentialRead, LlmProviderRead } from "./types";

export async function getLlmCredentials(organizationId: string) {
  const payload = await backendJson<LLMProviderCredentialListResponse>(
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/llm/provider-credentials`
  );
  return payload.credentials as LlmCredentialRead[];
}

export async function getLlmProviders(organizationId: string) {
  const payload = await backendJson<LLMProviderListResponse>(
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/llm/providers`
  );
  return payload.providers as LlmProviderRead[];
}
