export type SecretBackendScope = {
  organizationId: string;
  workspaceId?: string;
};

export function secretBackendsPath({ organizationId }: SecretBackendScope) {
  return `/org/${organizationId}/secret-backends`;
}

export function newSecretBackendPath(scope: SecretBackendScope) {
  return `${secretBackendsPath(scope)}/new`;
}

export function editSecretBackendPath(scope: SecretBackendScope, storeId: string) {
  return `${secretBackendsPath(scope)}/${storeId}/edit`;
}

export function deleteSecretBackendPath(scope: SecretBackendScope, storeId: string) {
  return `${secretBackendsPath(scope)}/${storeId}/delete`;
}
