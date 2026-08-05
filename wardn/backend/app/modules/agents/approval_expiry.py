from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.modules.agents.models import AgentToolApproval


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_agent_tool_approval_expires_at(now: datetime | None = None) -> datetime:
    return (now or utc_now()) + timedelta(
        seconds=get_settings().agent_tool_approval_expiry_seconds
    )


def agent_tool_approval_expires_at(
    approval: AgentToolApproval,
    *,
    now: datetime | None = None,
) -> datetime:
    if approval.expires_at is not None:
        expires_at = approval.expires_at
        if expires_at.tzinfo is None:
            return expires_at.replace(tzinfo=UTC)
        return expires_at.astimezone(UTC)
    created_at = approval.created_at
    if created_at is None:
        return new_agent_tool_approval_expires_at(now=now)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return created_at.astimezone(UTC) + timedelta(
        seconds=get_settings().agent_tool_approval_expiry_seconds
    )


def agent_tool_approval_is_expired(
    approval: AgentToolApproval,
    *,
    now: datetime | None = None,
) -> bool:
    return agent_tool_approval_expires_at(approval, now=now) <= (now or utc_now())
