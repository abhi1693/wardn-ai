class UserModuleError(Exception):
    """Base exception for user module failures."""


class DuplicateUserError(UserModuleError):
    pass


class BootstrapUserExistsError(UserModuleError):
    pass


class UserNotFoundError(UserModuleError):
    pass


class UserAPITokenNotFoundError(UserModuleError):
    pass


class InvalidLoginError(UserModuleError):
    pass


class InvalidAPITokenScopeError(UserModuleError):
    pass


class OIDCConfigurationError(UserModuleError):
    pass


class OIDCAuthenticationError(UserModuleError):
    pass
