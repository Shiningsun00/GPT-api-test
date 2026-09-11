class AgentWorkflowError(Exception):
    """Base error for the UI-independent core."""


class ConfigurationError(AgentWorkflowError):
    pass


class WorkflowValidationError(AgentWorkflowError):
    pass


class DependencyValidationError(WorkflowValidationError):
    pass


class ProviderError(AgentWorkflowError):
    pass


class RetrievalError(AgentWorkflowError):
    pass


class UnsupportedFileTypeError(RetrievalError):
    pass


class FileExtractionError(RetrievalError):
    pass


class IntegrationError(AgentWorkflowError):
    pass
