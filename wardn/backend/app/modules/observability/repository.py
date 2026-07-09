from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agents.models import Agent
from app.modules.mcp_runtime.models import MCPToolInvocation
from app.modules.observability.models import LLMModelPrice, LLMTrace, LLMUsageRecord
from app.modules.users.models import User


async def list_mcp_tool_usage(
    session: AsyncSession,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    limit: int,
) -> list[tuple[MCPToolInvocation, User | None, Agent | None]]:
    result = await session.execute(
        select(MCPToolInvocation, User, Agent)
        .outerjoin(User, MCPToolInvocation.user_id == User.id)
        .outerjoin(Agent, MCPToolInvocation.agent_id == Agent.id)
        .where(
            MCPToolInvocation.workspace_id == workspace_id,
        )
        .order_by(desc(MCPToolInvocation.started_at), desc(MCPToolInvocation.created_at))
        .limit(limit)
    )
    return list(result.all())


async def get_model_price(
    session: AsyncSession,
    *,
    provider: str,
    model: str,
) -> LLMModelPrice | None:
    if not hasattr(session, "execute"):
        return None
    result = await session.execute(
        select(LLMModelPrice).where(
            LLMModelPrice.provider == provider,
            LLMModelPrice.model == model,
        )
    )
    return result.scalar_one_or_none()


async def create_llm_usage_record(
    session: AsyncSession,
    *,
    usage_record: LLMUsageRecord,
    trace: LLMTrace,
) -> LLMUsageRecord:
    session.add(trace)
    session.add(usage_record)
    await session.flush()
    return usage_record
