class OrganizationError(Exception):
    pass


class OrganizationNotFoundError(OrganizationError):
    pass


class OrganizationAccessDeniedError(OrganizationError):
    pass


class DuplicateOrganizationError(OrganizationError):
    pass


class WorkspaceNotFoundError(OrganizationError):
    pass


class WorkspaceAccessDeniedError(OrganizationError):
    pass


class DuplicateWorkspaceError(OrganizationError):
    pass
