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


class MembershipNotFoundError(OrganizationError):
    pass


class MembershipRoleError(OrganizationError):
    pass


class DuplicateInvitationError(OrganizationError):
    pass


class InvitationNotFoundError(OrganizationError):
    pass


class InvitationExpiredError(OrganizationError):
    pass


class InvitationEmailMismatchError(OrganizationError):
    pass
