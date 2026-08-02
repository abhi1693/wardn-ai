class ChatProviderError(Exception):
    pass


class ChatProviderConnectionNotFoundError(ChatProviderError):
    pass


class DuplicateChatProviderConnectionError(ChatProviderError):
    pass


class InvalidChatProviderConnectionError(ChatProviderError):
    pass


class ChatProviderWebhookAuthError(ChatProviderError):
    pass


class ChatProviderDeliveryError(ChatProviderError):
    pass
