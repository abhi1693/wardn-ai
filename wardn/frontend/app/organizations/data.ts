import type { SecretStoreListResponse, SecretStoreRead } from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";
import { getWorkspaceContext } from "@/lib/workspace-context";

export async function getSecretStores(organizationId: string, workspaceId?: string) {
  const params = workspaceId ? `?workspaceId=${encodeURIComponent(workspaceId)}` : "";
  const payload = await backendJson<SecretStoreListResponse>(
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/secrets/stores${params}`
  );
  return payload.stores;
}

export async function getSecretStore(organizationId: string, storeId: string) {
  return backendJson<SecretStoreRead>(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/secrets/stores/${encodeURIComponent(storeId)}`
  );
}

export { getWorkspaceContext };
