import type {
  LLMProviderCredentialRead,
  LLMProviderRead,
  OrganizationRead,
  SecretStoreRead,
  UserRead,
  WorkspaceRead,
} from "@/lib/api/generated/model";

export type CredentialAuthMethod = "api_key" | "oauth";
export type CredentialProvider = string;
export type CredentialVisibility = "organization" | "workspace" | "user";
export type CredentialOAuthProvider = "chatgpt";
export type LlmProviderRead = LLMProviderRead;

export type LlmCredentialRead = LLMProviderCredentialRead & {
  authMethod?: CredentialAuthMethod;
  oauthProvider?: string;
  oauthExpiresAt?: string | null;
  oauthScopes?: string[];
  oauthMetadata?: Record<string, unknown>;
};

export type CredentialPayload = {
  name: string;
  provider: string;
  visibility: CredentialVisibility;
  workspaceId?: string | null;
  authMethod: CredentialAuthMethod;
  apiKeySecretStoreId?: string | null;
  apiKey?: string | null;
  oauthProvider?: CredentialOAuthProvider | null;
  oauthExpiresAt?: string | null;
  oauthScopes?: string[];
  oauthMetadata?: Record<string, unknown>;
  baseUrl?: string;
  extraHeaders?: Record<string, string>;
  isActive?: boolean;
};


export type CredentialFormProps = {
  credential?: LlmCredentialRead;
  currentUser: UserRead | null;
  organization: OrganizationRead;
  providers: LlmProviderRead[];
  secretStores: SecretStoreRead[];
  workspaces: WorkspaceRead[];
};
