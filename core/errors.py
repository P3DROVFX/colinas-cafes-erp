class AppError(Exception):
    """Base error whose message is safe to show to end users."""


class ConfigurationError(AppError):
    pass


class AccessDeniedError(AppError):
    pass


class BusinessRuleError(AppError):
    pass
