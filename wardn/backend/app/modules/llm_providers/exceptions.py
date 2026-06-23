class LLMProviderError(Exception):
    pass


class LLMProviderCredentialNotFoundError(LLMProviderError):
    pass


class DuplicateLLMProviderCredentialError(LLMProviderError):
    pass


class InvalidLLMProviderCredentialScopeError(LLMProviderError):
    pass


class InvalidLLMProviderCredentialAuthError(LLMProviderError):
    pass
