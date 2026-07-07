class LimitsError(Exception):
    pass


class LimitAccessDeniedError(LimitsError):
    pass


class LimitNotFoundError(LimitsError):
    pass


class InvalidLimitKeyError(LimitsError):
    pass


class LimitExceededError(LimitsError):
    pass


class InvalidLimitScopeError(LimitsError):
    pass
