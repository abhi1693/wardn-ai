class AgentError(Exception):
    pass


class AgentNotFoundError(AgentError):
    pass


class DuplicateAgentError(AgentError):
    pass


class InvalidAgentScopeError(AgentError):
    pass


class InvalidAgentToolAssignmentError(AgentError):
    pass

