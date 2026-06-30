export type MCPCatalogSource = {
  id: string;
  organizationId: string;
  name: string;
  provider: string;
  baseUrl: string;
  tenantId: string;
  syncMode: string;
  lastSuccessAt?: string | null;
  lastSyncedUpdatedSince?: string | null;
  lastError: string;
  isEnabled: boolean;
  hasAuthToken: boolean;
  createdAt: string;
  updatedAt: string;
};

export type MCPCatalogSourceListResponse = {
  sources: MCPCatalogSource[];
};
