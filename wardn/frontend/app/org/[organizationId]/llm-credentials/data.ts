import type { LLMProviderCredentialListResponse } from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";

import type { LlmCredentialRead } from "./types";

export async function getLlmCredentials(organizationId: string) {
  const payload = await backendJson<LLMProviderCredentialListResponse>(
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/llm/provider-credentials`
  );
  return payload.credentials as LlmCredentialRead[];
}
