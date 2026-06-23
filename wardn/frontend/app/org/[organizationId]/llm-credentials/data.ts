import type { LLMProviderCredentialListResponse } from "@/lib/api/generated/model";
import { backendCookieHeader, backendPath } from "@/lib/workspace-context";

import type { LlmCredentialRead } from "./types";

export async function getLlmCredentials(organizationId: string) {
  const cookie = await backendCookieHeader();
  try {
    const response = await fetch(
      backendPath(
        `/api/v1/organizations/${encodeURIComponent(organizationId)}/llm/provider-credentials`
      ),
      {
        cache: "no-store",
        headers: cookie ? { cookie } : {},
      }
    );
    if (!response.ok) {
      return [];
    }
    const payload = (await response.json()) as LLMProviderCredentialListResponse;
    return payload.credentials as LlmCredentialRead[];
  } catch {
    return [];
  }
}
