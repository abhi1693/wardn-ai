from app.modules.secrets.exceptions import SecretProviderError
from app.modules.secrets.provider import SecretStoreProvider
from app.modules.secrets.providers.openbao import OpenBaoSecretProvider

_PROVIDERS: dict[str, SecretStoreProvider] = {
    OpenBaoSecretProvider.name: OpenBaoSecretProvider(),
}


def get_secret_provider(name: str) -> SecretStoreProvider:
    provider = _PROVIDERS.get(name.strip().casefold())
    if provider is None:
        raise SecretProviderError(f"unsupported secret store provider: {name}")
    return provider


def supported_secret_providers() -> list[str]:
    return sorted(_PROVIDERS)
