export type SecretBackendScope = {
  organizationId: string;
  workspaceId?: string;
};

export function secretBackendsPath({ organizationId, workspaceId }: SecretBackendScope) {
  if (workspaceId) {
    return `/org/${organizationId}/workspace/${workspaceId}/secret-backends`;
  }
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
