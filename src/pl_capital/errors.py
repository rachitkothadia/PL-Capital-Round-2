"""Safe public errors: never include SDK request objects or credential values."""


class CapitalError(Exception):
    """An actionable error safe to display in CLI/TUI."""


class DataError(CapitalError):
    pass


class QueryError(CapitalError):
    pass


class ConfigurationError(CapitalError):
    pass


class PlanningError(CapitalError):
    pass


class EntityError(CapitalError):
    pass
