from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.modules.organizations import membership_service
from app.modules.organizations.exceptions import (
    InvitationEmailMismatchError,
    MembershipRoleError,
)
from app.modules.organizations.models import (
    MembershipInvitation,
    Organization,
    OrganizationMembership,
    Workspace,
    WorkspaceMembership,
)
from app.modules.organizations.schemas import MembershipRoleUpdate
from app.modules.users.models import User


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flushed = False

    def add(self, instance: object) -> None:
        self.added.append(instance)
        if getattr(instance, "id", None) is None:
            instance.id = uuid4()

    async def flush(self) -> None:
        self.flushed = True


def timestamped_membership(membership):
    membership.created_at = datetime(2026, 8, 11, tzinfo=UTC)
    membership.updated_at = membership.created_at
    return membership


@pytest.mark.asyncio
async def test_organization_admin_cannot_promote_member_to_owner(monkeypatch) -> None:
    organization_id = uuid4()
    actor = User(id=uuid4(), email="admin@example.com", is_superuser=False)
    actor_membership = OrganizationMembership(
        id=uuid4(),
        organization_id=organization_id,
        user_id=actor.id,
        role="admin",
        is_active=True,
    )
    target = timestamped_membership(
        OrganizationMembership(
            id=uuid4(),
            organization_id=organization_id,
            user_id=uuid4(),
            role="member",
            is_active=True,
        )
    )

    async def require_admin(*args, **kwargs):
        return object(), actor_membership

    async def get_membership(*args, **kwargs):
        return target

    monkeypatch.setattr(membership_service, "require_organization_admin", require_admin)
    monkeypatch.setattr(
        membership_service.repository,
        "get_organization_membership_by_id",
        get_membership,
    )

    with pytest.raises(MembershipRoleError, match="only organization owners"):
        await membership_service.update_organization_member(
            FakeSession(),
            actor,
            organization_id,
            target.id,
            MembershipRoleUpdate(role="owner"),
        )


@pytest.mark.asyncio
async def test_last_organization_owner_cannot_be_demoted(monkeypatch) -> None:
    organization_id = uuid4()
    actor = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    owner = timestamped_membership(
        OrganizationMembership(
            id=uuid4(),
            organization_id=organization_id,
            user_id=actor.id,
            role="owner",
            is_active=True,
        )
    )

    async def require_admin(*args, **kwargs):
        return object(), owner

    async def get_membership(*args, **kwargs):
        return owner

    async def lock(*args, **kwargs):
        return None

    async def count_owners(*args, **kwargs):
        return 1

    monkeypatch.setattr(membership_service, "require_organization_admin", require_admin)
    monkeypatch.setattr(
        membership_service.repository,
        "get_organization_membership_by_id",
        get_membership,
    )
    monkeypatch.setattr(
        membership_service.repository,
        "lock_organization_memberships",
        lock,
    )
    monkeypatch.setattr(
        membership_service.repository,
        "count_active_organization_owners",
        count_owners,
    )

    with pytest.raises(MembershipRoleError, match="at least one owner"):
        await membership_service.update_organization_member(
            FakeSession(),
            actor,
            organization_id,
            owner.id,
            MembershipRoleUpdate(role="admin"),
        )


@pytest.mark.asyncio
async def test_organization_admin_cannot_revoke_owner_invitation(monkeypatch) -> None:
    organization_id = uuid4()
    actor = User(id=uuid4(), email="admin@example.com", is_superuser=False)
    actor_membership = OrganizationMembership(
        id=uuid4(),
        organization_id=organization_id,
        user_id=actor.id,
        role="admin",
        is_active=True,
    )
    invitation = MembershipInvitation(
        id=uuid4(),
        organization_id=organization_id,
        scope_type="organization",
        email="owner@example.com",
        role="owner",
        token_hash="hash",
        status="pending",
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )

    async def require_admin(*args, **kwargs):
        return object(), actor_membership

    async def get_invitation(*args, **kwargs):
        return invitation

    monkeypatch.setattr(membership_service, "require_organization_admin", require_admin)
    monkeypatch.setattr(
        membership_service.repository,
        "get_invitation_by_id",
        get_invitation,
    )

    with pytest.raises(MembershipRoleError, match="only organization owners"):
        await membership_service.revoke_invitation(
            FakeSession(),
            actor,
            organization_id,
            None,
            invitation.id,
        )


@pytest.mark.asyncio
async def test_organization_member_removal_protects_sole_workspace_ownership(monkeypatch) -> None:
    organization_id = uuid4()
    actor = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    actor_membership = OrganizationMembership(
        id=uuid4(),
        organization_id=organization_id,
        user_id=actor.id,
        role="owner",
        is_active=True,
    )
    target = OrganizationMembership(
        id=uuid4(),
        organization_id=organization_id,
        user_id=uuid4(),
        role="member",
        is_active=True,
    )

    async def require_admin(*args, **kwargs):
        return object(), actor_membership

    async def get_membership(*args, **kwargs):
        return target

    async def no_op(*args, **kwargs):
        return None

    async def sole_owner(*args, **kwargs):
        return [uuid4()]

    monkeypatch.setattr(membership_service, "require_organization_admin", require_admin)
    monkeypatch.setattr(
        membership_service.repository,
        "get_organization_membership_by_id",
        get_membership,
    )
    monkeypatch.setattr(
        membership_service.repository,
        "lock_organization_memberships",
        no_op,
    )
    monkeypatch.setattr(
        membership_service.repository,
        "lock_workspace_memberships_for_organization",
        no_op,
    )
    monkeypatch.setattr(
        membership_service.repository,
        "list_sole_owned_workspace_ids_for_organization_user",
        sole_owner,
    )

    with pytest.raises(MembershipRoleError, match="transfer ownership"):
        await membership_service.remove_organization_member(
            FakeSession(),
            actor,
            organization_id,
            target.id,
        )

    assert target.is_active is True


@pytest.mark.asyncio
async def test_workspace_members_include_inherited_organization_admins(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    current_user = User(id=uuid4(), email="viewer@example.com", is_superuser=False)
    direct_user = User(
        id=uuid4(),
        email="direct@example.com",
        first_name="Direct",
        last_name="Member",
        is_active=True,
    )
    inherited_user = User(
        id=uuid4(),
        email="owner@example.com",
        first_name="Organization",
        last_name="Owner",
        is_active=True,
    )
    direct_membership = timestamped_membership(
        WorkspaceMembership(
            id=uuid4(),
            workspace_id=workspace_id,
            user_id=direct_user.id,
            role="member",
            is_active=True,
        )
    )
    inherited_membership = timestamped_membership(
        OrganizationMembership(
            id=uuid4(),
            organization_id=organization_id,
            user_id=inherited_user.id,
            role="owner",
            is_active=True,
        )
    )

    async def require_member(*args, **kwargs):
        return (
            object(),
            OrganizationMembership(
                organization_id=organization_id,
                user_id=current_user.id,
                role="member",
                is_active=True,
            ),
            WorkspaceMembership(
                workspace_id=workspace_id,
                user_id=current_user.id,
                role="member",
                is_active=True,
            ),
        )

    async def list_direct(*args, **kwargs):
        return [(direct_membership, direct_user)]

    async def list_admins(*args, **kwargs):
        return [(inherited_membership, inherited_user)]

    monkeypatch.setattr(membership_service, "require_workspace_member", require_member)
    monkeypatch.setattr(membership_service.repository, "list_workspace_members", list_direct)
    monkeypatch.setattr(
        membership_service.repository,
        "list_organization_admin_members",
        list_admins,
    )

    response = await membership_service.list_workspace_members(
        FakeSession(),
        current_user,
        organization_id,
        workspace_id,
    )

    assert [(member.email, member.access_source) for member in response.members] == [
        ("direct@example.com", "workspace"),
        ("owner@example.com", "organization"),
    ]
    inherited = response.members[1]
    assert inherited.membership_id is None
    assert inherited.role == "admin"
    assert inherited.organization_role == "owner"
    assert response.can_manage is False
    assert response.can_manage_owners is False
    assert response.current_user_id == current_user.id


@pytest.mark.asyncio
async def test_workspace_members_preserve_direct_role_for_organization_admin(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    owner = User(
        id=uuid4(),
        email="owner@example.com",
        first_name="Workspace",
        last_name="Owner",
        is_active=True,
    )
    organization_membership = timestamped_membership(
        OrganizationMembership(
            id=uuid4(),
            organization_id=organization_id,
            user_id=owner.id,
            role="admin",
            is_active=True,
        )
    )
    workspace_membership = timestamped_membership(
        WorkspaceMembership(
            id=uuid4(),
            workspace_id=workspace_id,
            user_id=owner.id,
            role="owner",
            is_active=True,
        )
    )

    async def require_member(*args, **kwargs):
        return object(), organization_membership, workspace_membership

    async def list_direct(*args, **kwargs):
        return [(workspace_membership, owner)]

    async def list_admins(*args, **kwargs):
        return [(organization_membership, owner)]

    monkeypatch.setattr(membership_service, "require_workspace_member", require_member)
    monkeypatch.setattr(membership_service.repository, "list_workspace_members", list_direct)
    monkeypatch.setattr(
        membership_service.repository,
        "list_organization_admin_members",
        list_admins,
    )

    response = await membership_service.list_workspace_members(
        FakeSession(),
        owner,
        organization_id,
        workspace_id,
    )

    assert len(response.members) == 1
    member = response.members[0]
    assert member.membership_id == workspace_membership.id
    assert member.role == "owner"
    assert member.access_source == "workspace"
    assert member.organization_role == "admin"
    assert response.can_manage is True
    assert response.can_manage_owners is True


@pytest.mark.asyncio
async def test_accept_workspace_invitation_creates_required_memberships(monkeypatch) -> None:
    now = datetime.now(UTC)
    organization = Organization(
        id=uuid4(),
        name="Platform",
        slug="platform",
        status="active",
    )
    workspace = Workspace(
        id=uuid4(),
        organization_id=organization.id,
        name="Production",
        slug="production",
        status="active",
    )
    invitation = MembershipInvitation(
        id=uuid4(),
        organization_id=organization.id,
        workspace_id=workspace.id,
        scope_type="workspace",
        email="member@example.com",
        role="admin",
        token_hash="hash",
        status="pending",
        expires_at=now + timedelta(days=1),
    )
    user = User(id=uuid4(), email="member@example.com", is_active=True)

    async def active_invitation(*args, **kwargs):
        return invitation, organization, workspace

    async def missing_membership(*args, **kwargs):
        return None

    monkeypatch.setattr(membership_service, "_active_invitation", active_invitation)
    monkeypatch.setattr(
        membership_service.repository,
        "get_organization_membership_any",
        missing_membership,
    )
    monkeypatch.setattr(
        membership_service.repository,
        "get_workspace_membership_any",
        missing_membership,
    )
    session = FakeSession()

    response = await membership_service.accept_invitation(session, "secret", user)

    organization_membership, workspace_membership = session.added
    assert isinstance(organization_membership, OrganizationMembership)
    assert organization_membership.role == "member"
    assert isinstance(workspace_membership, WorkspaceMembership)
    assert workspace_membership.role == "admin"
    assert invitation.status == "accepted"
    assert invitation.accepted_by_id == user.id
    assert response.workspace_id == workspace.id


@pytest.mark.asyncio
async def test_list_pending_invitations_for_user_returns_current_email_invites(monkeypatch) -> None:
    organization = Organization(
        id=uuid4(),
        name="Platform",
        slug="platform",
        status="active",
    )
    workspace = Workspace(
        id=uuid4(),
        organization_id=organization.id,
        name="Production",
        slug="production",
        status="active",
    )
    invitation = MembershipInvitation(
        id=uuid4(),
        organization_id=organization.id,
        workspace_id=workspace.id,
        scope_type="workspace",
        email="member@example.com",
        role="admin",
        token_hash="hash",
        status="pending",
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    user = User(id=uuid4(), email="Member@Example.com", is_active=True)
    seen = {}

    async def list_pending(*args, **kwargs):
        seen.update(kwargs)
        return [(invitation, organization, workspace)]

    monkeypatch.setattr(
        membership_service.repository,
        "list_pending_invitations_for_email",
        list_pending,
    )

    response = await membership_service.list_pending_invitations_for_user(FakeSession(), user)

    assert seen["email"] == "member@example.com"
    assert response.invitations[0].id == invitation.id
    assert response.invitations[0].organization_name == "Platform"
    assert response.invitations[0].workspace_name == "Production"


@pytest.mark.asyncio
async def test_accept_pending_invitation_by_id_uses_current_user_email(monkeypatch) -> None:
    now = datetime.now(UTC)
    organization = Organization(
        id=uuid4(),
        name="Platform",
        slug="platform",
        status="active",
    )
    invitation = MembershipInvitation(
        id=uuid4(),
        organization_id=organization.id,
        scope_type="organization",
        email="member@example.com",
        role="admin",
        token_hash="hash",
        status="pending",
        expires_at=now + timedelta(days=1),
    )
    user = User(id=uuid4(), email="Member@Example.com", is_active=True)
    seen = {}

    async def get_pending(*args, **kwargs):
        seen.update(kwargs)
        return invitation

    async def get_organization(*args, **kwargs):
        return organization

    async def missing_membership(*args, **kwargs):
        return None

    monkeypatch.setattr(
        membership_service.repository,
        "get_pending_invitation_for_email_by_id",
        get_pending,
    )
    monkeypatch.setattr(membership_service.repository, "get_organization_by_id", get_organization)
    monkeypatch.setattr(
        membership_service.repository,
        "get_organization_membership_any",
        missing_membership,
    )
    session = FakeSession()

    response = await membership_service.accept_pending_invitation(session, invitation.id, user)

    assert seen["invitation_id"] == invitation.id
    assert seen["email"] == "member@example.com"
    membership = session.added[0]
    assert isinstance(membership, OrganizationMembership)
    assert membership.role == "admin"
    assert invitation.status == "accepted"
    assert invitation.accepted_by_id == user.id
    assert response.organization_id == organization.id


@pytest.mark.asyncio
async def test_invitation_requires_matching_authenticated_email(monkeypatch) -> None:
    now = datetime.now(UTC)
    organization = Organization(
        id=uuid4(),
        name="Platform",
        slug="platform",
        status="active",
    )
    invitation = MembershipInvitation(
        id=uuid4(),
        organization_id=organization.id,
        scope_type="organization",
        email="invited@example.com",
        role="member",
        token_hash="hash",
        status="pending",
        expires_at=now + timedelta(days=1),
    )

    async def active_invitation(*args, **kwargs):
        return invitation, organization, None

    monkeypatch.setattr(membership_service, "_active_invitation", active_invitation)

    with pytest.raises(InvitationEmailMismatchError, match="sign in with"):
        await membership_service.accept_invitation(
            FakeSession(),
            "secret",
            User(id=uuid4(), email="other@example.com", is_active=True),
        )
