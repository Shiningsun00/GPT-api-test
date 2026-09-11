class GraphError(Exception):
    """Base error for durable graph orchestration."""


class GraphStateValidationError(GraphError):
    pass


class GraphLifecycleError(GraphError):
    pass


class UnknownStageError(GraphError):
    pass
