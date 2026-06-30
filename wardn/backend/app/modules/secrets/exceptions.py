class SecretsError(Exception):
    pass


class SecretStoreNotFoundError(SecretsError):
    pass


class SecretHandleNotFoundError(SecretsError):
    pass


class DuplicateSecretStoreError(SecretsError):
    pass


class DuplicateSecretHandleError(SecretsError):
    pass


class InvalidSecretStoreError(SecretsError):
    pass


class InvalidSecretHandleError(SecretsError):
    pass


class SecretProviderError(SecretsError):
    pass
