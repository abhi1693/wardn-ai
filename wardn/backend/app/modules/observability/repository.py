from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, case, desc, func, literal, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agents.models import Agent
from app.modules.limits.models import ResourceLimit, UsageBudget
from app.modules.llm_providers.models import LLMProviderCredential
from app.modules.mcp_registry.models import (
    MCPCatalogSource,
    MCPServerInstallation,
    MCPServerToolSchema,
    MCPServerVersion,
)
from app.modules.mcp_runtime.models import MCPRuntimeSession, MCPToolInvocation
from app.modules.observability.models import LLMModelPrice, LLMTrace, LLMUsageRecord
from app.modules.organizations.models import OrganizationMembership, Workspace
from app.modules.users.models import User

ACTIVE_RUNTIME_SESSION_STATUSES = ("pending", "starting", "running", "idle")
ATTENTION_RUNTIME_SESSION_STATUSES = ("failed", "error")


def count_if(condition):
    return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)


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


async def list_llm_usage(
    session: AsyncSession,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    limit: int,
) -> list[tuple[LLMUsageRecord, User | None, Agent | None]]:
    result = await session.execute(
        select(LLMUsageRecord, User, Agent)
        .outerjoin(User, LLMUsageRecord.user_id == User.id)
        .outerjoin(Agent, LLMUsageRecord.agent_id == Agent.id)
        .where(
            LLMUsageRecord.organization_id == organization_id,
            LLMUsageRecord.workspace_id == workspace_id,
        )
        .order_by(desc(LLMUsageRecord.started_at), desc(LLMUsageRecord.created_at))
        .limit(limit)
    )
    return list(result.all())


def llm_usage_scope_filters(
    *,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
    agent_run_id: UUID | None = None,
    started_at_from: datetime | None = None,
    started_at_to: datetime | None = None,
):
    filters = []
    if organization_id is not None:
        filters.append(LLMUsageRecord.organization_id == organization_id)
    if workspace_id is not None:
        filters.append(LLMUsageRecord.workspace_id == workspace_id)
    if user_id is not None:
        filters.append(LLMUsageRecord.user_id == user_id)
    if agent_run_id is not None:
        filters.append(LLMUsageRecord.agent_run_id == agent_run_id)
    if started_at_from is not None:
        filters.append(LLMUsageRecord.started_at >= started_at_from)
    if started_at_to is not None:
        filters.append(LLMUsageRecord.started_at < started_at_to)
    return filters


def mcp_tool_scope_filters(
    *,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
    agent_run_id: UUID | None = None,
    started_at_from: datetime | None = None,
    started_at_to: datetime | None = None,
):
    filters = []
    if organization_id is not None:
        filters.append(MCPToolInvocation.organization_id == organization_id)
    if workspace_id is not None:
        filters.append(MCPToolInvocation.workspace_id == workspace_id)
    if user_id is not None:
        filters.append(MCPToolInvocation.user_id == user_id)
    if agent_run_id is not None:
        filters.append(MCPToolInvocation.agent_run_id == agent_run_id)
    if started_at_from is not None:
        filters.append(MCPToolInvocation.started_at >= started_at_from)
    if started_at_to is not None:
        filters.append(MCPToolInvocation.started_at < started_at_to)
    return filters


def llm_usage_aggregate_columns():
    return (
        func.count(LLMUsageRecord.id).label("requests"),
        func.coalesce(
            func.sum(case((LLMUsageRecord.status == "succeeded", 1), else_=0)),
            0,
        ).label("succeeded"),
        func.coalesce(
            func.sum(case((LLMUsageRecord.status == "failed", 1), else_=0)),
            0,
        ).label("failed"),
        func.coalesce(
            func.sum(case((LLMUsageRecord.status == "running", 1), else_=0)),
            0,
        ).label("running"),
        func.coalesce(func.sum(LLMUsageRecord.input_tokens), 0).label("input_tokens"),
        func.coalesce(func.sum(LLMUsageRecord.output_tokens), 0).label("output_tokens"),
        func.coalesce(func.sum(LLMUsageRecord.cost_usd), 0).label("cost_usd"),
    )


async def llm_usage_totals(
    session: AsyncSession,
    *,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
    agent_run_id: UUID | None = None,
):
    result = await session.execute(
        select(*llm_usage_aggregate_columns()).where(
            *llm_usage_scope_filters(
                organization_id=organization_id,
                workspace_id=workspace_id,
                user_id=user_id,
                agent_run_id=agent_run_id,
            )
        )
    )
    return result.one()


async def llm_usage_totals_by_agent_run(
    session: AsyncSession,
    *,
    agent_run_ids: list[UUID],
):
    if not agent_run_ids:
        return []
    result = await session.execute(
        select(LLMUsageRecord.agent_run_id, *llm_usage_aggregate_columns())
        .where(LLMUsageRecord.agent_run_id.in_(agent_run_ids))
        .group_by(LLMUsageRecord.agent_run_id)
    )
    return list(result.all())


async def mcp_tool_call_count(
    session: AsyncSession,
    *,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
    agent_run_id: UUID | None = None,
) -> int:
    result = await session.execute(
        select(func.count(MCPToolInvocation.id)).where(
            *mcp_tool_scope_filters(
                organization_id=organization_id,
                workspace_id=workspace_id,
                user_id=user_id,
                agent_run_id=agent_run_id,
            )
        )
    )
    return int(result.scalar_one() or 0)


async def mcp_tool_call_counts_by_agent_run(
    session: AsyncSession,
    *,
    agent_run_ids: list[UUID],
):
    if not agent_run_ids:
        return []
    result = await session.execute(
        select(MCPToolInvocation.agent_run_id, func.count(MCPToolInvocation.id).label("tool_calls"))
        .where(MCPToolInvocation.agent_run_id.in_(agent_run_ids))
        .group_by(MCPToolInvocation.agent_run_id)
    )
    return list(result.all())


async def organization_dashboard_control_counts(
    session: AsyncSession,
    *,
    organization_id: UUID,
    catalog_stale_before: datetime,
):
    workspace_ids = select(Workspace.id).where(Workspace.organization_id == organization_id)
    latest_versions = (
        select(
            MCPServerVersion.name.label("server_name"),
            MCPServerVersion.version.label("latest_version"),
        )
        .where(
            MCPServerVersion.organization_id == organization_id,
            MCPServerVersion.is_latest.is_(True),
            MCPServerVersion.status != "deleted",
        )
        .subquery()
    )
    installation_update_condition = and_(
        latest_versions.c.latest_version.is_not(None),
        latest_versions.c.latest_version != MCPServerInstallation.installed_version,
    )
    installation_attention_condition = or_(
        MCPServerInstallation.status != "enabled",
        MCPServerInstallation.install_error != "",
    )
    runtime_attention_condition = or_(
        MCPRuntimeSession.status.in_(ATTENTION_RUNTIME_SESSION_STATUSES),
        MCPRuntimeSession.failure_count > 0,
        MCPRuntimeSession.last_error != "",
    )
    stale_catalog_condition = and_(
        MCPCatalogSource.is_enabled.is_(True),
        or_(
            MCPCatalogSource.last_success_at.is_(None),
            MCPCatalogSource.last_success_at < catalog_stale_before,
        ),
    )

    workspace_result = await session.execute(
        select(
            func.count(Workspace.id).label("workspaces"),
            count_if(Workspace.status == "active").label("active_workspaces"),
        ).where(Workspace.organization_id == organization_id)
    )
    member_result = await session.execute(
        select(
            func.count(OrganizationMembership.id).label("members"),
            count_if(OrganizationMembership.is_active.is_(True)).label("active_members"),
        ).where(OrganizationMembership.organization_id == organization_id)
    )
    agent_result = await session.execute(
        select(
            func.count(Agent.id).label("agents"),
            count_if(Agent.is_active.is_(True)).label("active_agents"),
        ).where(Agent.organization_id == organization_id)
    )
    installation_result = await session.execute(
        select(
            func.count(MCPServerInstallation.id).label("installed_servers"),
            count_if(MCPServerInstallation.status == "enabled").label("enabled_servers"),
            count_if(installation_attention_condition).label("servers_needing_attention"),
            count_if(installation_update_condition).label("server_updates"),
        )
        .select_from(MCPServerInstallation)
        .join(Workspace, Workspace.id == MCPServerInstallation.workspace_id)
        .outerjoin(
            latest_versions,
            latest_versions.c.server_name == MCPServerInstallation.server_name,
        )
        .where(Workspace.organization_id == organization_id)
    )
    tool_schema_result = await session.execute(
        select(func.count(MCPServerToolSchema.id).label("tools"))
        .select_from(MCPServerToolSchema)
        .join(Workspace, Workspace.id == MCPServerToolSchema.workspace_id)
        .where(
            Workspace.organization_id == organization_id,
            MCPServerToolSchema.is_active.is_(True),
        )
    )
    runtime_result = await session.execute(
        select(
            func.count(MCPRuntimeSession.id).label("runtime_sessions"),
            count_if(MCPRuntimeSession.status.in_(ACTIVE_RUNTIME_SESSION_STATUSES)).label(
                "active_runtime_sessions"
            ),
            count_if(runtime_attention_condition).label(
                "runtime_sessions_needing_attention"
            ),
        )
        .select_from(MCPRuntimeSession)
        .outerjoin(Workspace, Workspace.id == MCPRuntimeSession.workspace_id)
        .where(
            or_(
                MCPRuntimeSession.organization_id == organization_id,
                Workspace.organization_id == organization_id,
            )
        )
    )
    catalog_result = await session.execute(
        select(
            func.count(MCPCatalogSource.id).label("catalog_sources"),
            count_if(MCPCatalogSource.is_enabled.is_(True)).label("enabled_catalog_sources"),
            count_if(MCPCatalogSource.last_success_at.is_not(None)).label(
                "synced_catalog_sources"
            ),
            count_if(MCPCatalogSource.last_error != "").label("catalog_errors"),
            count_if(stale_catalog_condition).label("stale_catalog_sources"),
        ).where(MCPCatalogSource.organization_id == organization_id)
    )
    credential_result = await session.execute(
        select(
            func.count(LLMProviderCredential.id).label("provider_credentials"),
            count_if(LLMProviderCredential.is_active.is_(True)).label(
                "active_provider_credentials"
            ),
        ).where(LLMProviderCredential.organization_id == organization_id)
    )
    limit_result = await session.execute(
        select(func.count(ResourceLimit.id).label("resource_limits")).where(
            or_(
                and_(
                    ResourceLimit.scope_type == "organization",
                    ResourceLimit.scope_id == organization_id,
                ),
                and_(
                    ResourceLimit.scope_type == "workspace",
                    ResourceLimit.scope_id.in_(workspace_ids),
                ),
            )
        )
    )
    budget_result = await session.execute(
        select(func.count(UsageBudget.id).label("usage_budgets")).where(
            or_(
                and_(
                    UsageBudget.scope_type == "organization",
                    UsageBudget.scope_id == organization_id,
                ),
                and_(
                    UsageBudget.scope_type == "workspace",
                    UsageBudget.scope_id.in_(workspace_ids),
                ),
            )
        )
    )
    monthly_budget_result = await session.execute(
        select(func.coalesce(func.sum(UsageBudget.value), 0).label("monthly_budget_usd")).where(
            UsageBudget.scope_type == "organization",
            UsageBudget.scope_id == organization_id,
            UsageBudget.unit == "cost_usd",
            UsageBudget.period == "month",
        )
    )
    return {
        **workspace_result.mappings().one(),
        **member_result.mappings().one(),
        **agent_result.mappings().one(),
        **installation_result.mappings().one(),
        "tools": int(tool_schema_result.scalar_one() or 0),
        **runtime_result.mappings().one(),
        **catalog_result.mappings().one(),
        **credential_result.mappings().one(),
        "resource_limits": int(limit_result.scalar_one() or 0),
        "usage_budgets": int(budget_result.scalar_one() or 0),
        "monthly_budget_usd": monthly_budget_result.scalar_one(),
    }


async def organization_dashboard_tool_usage_totals(
    session: AsyncSession,
    *,
    organization_id: UUID,
    started_at_from: datetime,
    started_at_to: datetime,
):
    result = await session.execute(
        select(
            func.count(MCPToolInvocation.id).label("tool_calls"),
            count_if(
                or_(
                    MCPToolInvocation.status == "failed",
                    MCPToolInvocation.is_error.is_(True),
                )
            ).label("failed_tool_calls"),
            count_if(MCPToolInvocation.status == "running").label("running_tool_calls"),
            func.avg(MCPToolInvocation.duration_ms).label("average_tool_duration_ms"),
        ).where(
            *mcp_tool_scope_filters(
                organization_id=organization_id,
                started_at_from=started_at_from,
                started_at_to=started_at_to,
            )
        )
    )
    return result.mappings().one()


async def organization_dashboard_workspace_rows(
    session: AsyncSession,
    *,
    organization_id: UUID,
    started_at_from: datetime,
    started_at_to: datetime,
    limit: int,
):
    latest_versions = (
        select(
            MCPServerVersion.name.label("server_name"),
            MCPServerVersion.version.label("latest_version"),
        )
        .where(
            MCPServerVersion.organization_id == organization_id,
            MCPServerVersion.is_latest.is_(True),
            MCPServerVersion.status != "deleted",
        )
        .subquery()
    )
    llm_usage = (
        select(
            LLMUsageRecord.workspace_id.label("workspace_id"),
            func.count(LLMUsageRecord.id).label("requests"),
            count_if(LLMUsageRecord.status == "failed").label("failed_requests"),
            func.coalesce(func.sum(LLMUsageRecord.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(LLMUsageRecord.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(LLMUsageRecord.cost_usd), 0).label("cost_usd"),
            func.max(LLMUsageRecord.started_at).label("latest_llm_activity_at"),
        )
        .where(
            *llm_usage_scope_filters(
                organization_id=organization_id,
                started_at_from=started_at_from,
                started_at_to=started_at_to,
            )
        )
        .group_by(LLMUsageRecord.workspace_id)
        .subquery()
    )
    tool_usage = (
        select(
            MCPToolInvocation.workspace_id.label("workspace_id"),
            func.count(MCPToolInvocation.id).label("tool_calls"),
            count_if(
                or_(
                    MCPToolInvocation.status == "failed",
                    MCPToolInvocation.is_error.is_(True),
                )
            ).label("failed_tool_calls"),
            func.max(MCPToolInvocation.started_at).label("latest_tool_activity_at"),
        )
        .where(
            *mcp_tool_scope_filters(
                organization_id=organization_id,
                started_at_from=started_at_from,
                started_at_to=started_at_to,
            )
        )
        .group_by(MCPToolInvocation.workspace_id)
        .subquery()
    )
    agent_counts = (
        select(
            Agent.workspace_id.label("workspace_id"),
            func.count(Agent.id).label("agents"),
            count_if(Agent.is_active.is_(True)).label("active_agents"),
        )
        .where(Agent.organization_id == organization_id)
        .group_by(Agent.workspace_id)
        .subquery()
    )
    installation_counts = (
        select(
            MCPServerInstallation.workspace_id.label("workspace_id"),
            func.count(MCPServerInstallation.id).label("installations"),
            count_if(MCPServerInstallation.status == "enabled").label("enabled_installations"),
            count_if(
                or_(
                    MCPServerInstallation.status != "enabled",
                    MCPServerInstallation.install_error != "",
                )
            ).label("servers_needing_attention"),
            count_if(
                and_(
                    latest_versions.c.latest_version.is_not(None),
                    latest_versions.c.latest_version
                    != MCPServerInstallation.installed_version,
                )
            ).label("server_updates"),
        )
        .select_from(MCPServerInstallation)
        .join(Workspace, Workspace.id == MCPServerInstallation.workspace_id)
        .outerjoin(
            latest_versions,
            latest_versions.c.server_name == MCPServerInstallation.server_name,
        )
        .where(Workspace.organization_id == organization_id)
        .group_by(MCPServerInstallation.workspace_id)
        .subquery()
    )
    tool_counts = (
        select(
            MCPServerToolSchema.workspace_id.label("workspace_id"),
            func.count(MCPServerToolSchema.id).label("tool_count"),
        )
        .select_from(MCPServerToolSchema)
        .join(Workspace, Workspace.id == MCPServerToolSchema.workspace_id)
        .where(
            Workspace.organization_id == organization_id,
            MCPServerToolSchema.is_active.is_(True),
        )
        .group_by(MCPServerToolSchema.workspace_id)
        .subquery()
    )
    runtime_counts = (
        select(
            MCPRuntimeSession.workspace_id.label("workspace_id"),
            func.count(MCPRuntimeSession.id).label("runtime_sessions"),
            count_if(MCPRuntimeSession.status.in_(ACTIVE_RUNTIME_SESSION_STATUSES)).label(
                "active_runtime_sessions"
            ),
            count_if(
                or_(
                    MCPRuntimeSession.status.in_(ATTENTION_RUNTIME_SESSION_STATUSES),
                    MCPRuntimeSession.failure_count > 0,
                    MCPRuntimeSession.last_error != "",
                )
            ).label("runtime_sessions_needing_attention"),
        )
        .select_from(MCPRuntimeSession)
        .outerjoin(Workspace, Workspace.id == MCPRuntimeSession.workspace_id)
        .where(
            or_(
                MCPRuntimeSession.organization_id == organization_id,
                Workspace.organization_id == organization_id,
            )
        )
        .group_by(MCPRuntimeSession.workspace_id)
        .subquery()
    )

    result = await session.execute(
        select(
            Workspace.id,
            Workspace.name,
            Workspace.slug,
            Workspace.status,
            func.coalesce(llm_usage.c.requests, 0).label("requests"),
            func.coalesce(llm_usage.c.failed_requests, 0).label("failed_requests"),
            (
                func.coalesce(llm_usage.c.input_tokens, 0)
                + func.coalesce(llm_usage.c.output_tokens, 0)
            ).label("total_tokens"),
            func.coalesce(llm_usage.c.cost_usd, 0).label("cost_usd"),
            func.coalesce(tool_usage.c.tool_calls, 0).label("tool_calls"),
            func.coalesce(tool_usage.c.failed_tool_calls, 0).label("failed_tool_calls"),
            func.coalesce(agent_counts.c.agents, 0).label("agents"),
            func.coalesce(agent_counts.c.active_agents, 0).label("active_agents"),
            func.coalesce(installation_counts.c.installations, 0).label("installations"),
            func.coalesce(installation_counts.c.enabled_installations, 0).label(
                "enabled_installations"
            ),
            func.coalesce(installation_counts.c.servers_needing_attention, 0).label(
                "servers_needing_attention"
            ),
            func.coalesce(installation_counts.c.server_updates, 0).label("server_updates"),
            func.coalesce(tool_counts.c.tool_count, 0).label("tool_count"),
            func.coalesce(runtime_counts.c.runtime_sessions, 0).label("runtime_sessions"),
            func.coalesce(runtime_counts.c.active_runtime_sessions, 0).label(
                "active_runtime_sessions"
            ),
            func.coalesce(
                runtime_counts.c.runtime_sessions_needing_attention,
                0,
            ).label("runtime_sessions_needing_attention"),
            func.greatest(
                func.coalesce(
                    llm_usage.c.latest_llm_activity_at,
                    tool_usage.c.latest_tool_activity_at,
                ),
                func.coalesce(
                    tool_usage.c.latest_tool_activity_at,
                    llm_usage.c.latest_llm_activity_at,
                ),
            ).label("latest_activity_at"),
        )
        .select_from(Workspace)
        .outerjoin(llm_usage, llm_usage.c.workspace_id == Workspace.id)
        .outerjoin(tool_usage, tool_usage.c.workspace_id == Workspace.id)
        .outerjoin(agent_counts, agent_counts.c.workspace_id == Workspace.id)
        .outerjoin(
            installation_counts,
            installation_counts.c.workspace_id == Workspace.id,
        )
        .outerjoin(tool_counts, tool_counts.c.workspace_id == Workspace.id)
        .outerjoin(runtime_counts, runtime_counts.c.workspace_id == Workspace.id)
        .where(Workspace.organization_id == organization_id)
        .order_by(
            desc(func.coalesce(llm_usage.c.cost_usd, 0)),
            desc(func.coalesce(tool_usage.c.tool_calls, 0)),
            Workspace.name.asc(),
        )
        .limit(limit)
    )
    return list(result.mappings().all())


async def organization_dashboard_runtime_rows(
    session: AsyncSession,
    *,
    organization_id: UUID,
):
    result = await session.execute(
        select(
            MCPServerInstallation.install_type.label("runtime"),
            func.count(MCPServerInstallation.id).label("total"),
            count_if(MCPServerInstallation.status == "enabled").label("enabled"),
            count_if(
                or_(
                    MCPServerInstallation.status != "enabled",
                    MCPServerInstallation.install_error != "",
                )
            ).label("attention"),
        )
        .select_from(MCPServerInstallation)
        .join(Workspace, Workspace.id == MCPServerInstallation.workspace_id)
        .where(Workspace.organization_id == organization_id)
        .group_by(MCPServerInstallation.install_type)
        .order_by(desc("total"), MCPServerInstallation.install_type.asc())
    )
    return list(result.mappings().all())


async def organization_dashboard_provider_rows(
    session: AsyncSession,
    *,
    organization_id: UUID,
):
    result = await session.execute(
        select(
            LLMProviderCredential.provider,
            func.count(LLMProviderCredential.id).label("total"),
            count_if(LLMProviderCredential.is_active.is_(True)).label("active"),
            count_if(LLMProviderCredential.auth_method == "api_key").label("api_key"),
            count_if(LLMProviderCredential.auth_method == "oauth").label("oauth"),
        )
        .where(LLMProviderCredential.organization_id == organization_id)
        .group_by(LLMProviderCredential.provider)
        .order_by(desc("active"), desc("total"), LLMProviderCredential.provider.asc())
    )
    return list(result.mappings().all())


async def organization_dashboard_top_tool_rows(
    session: AsyncSession,
    *,
    organization_id: UUID,
    started_at_from: datetime,
    started_at_to: datetime,
    limit: int,
):
    failed_calls = count_if(
        or_(
            MCPToolInvocation.status == "failed",
            MCPToolInvocation.is_error.is_(True),
        )
    )
    call_count = func.count(MCPToolInvocation.id)
    result = await session.execute(
        select(
            MCPToolInvocation.server_name,
            MCPToolInvocation.tool_name,
            MCPToolInvocation.workspace_id,
            Workspace.name.label("workspace_name"),
            call_count.label("calls"),
            failed_calls.label("failed"),
            func.avg(MCPToolInvocation.duration_ms).label("average_duration_ms"),
            func.percentile_cont(0.95)
            .within_group(MCPToolInvocation.duration_ms)
            .label("p95_duration_ms"),
            func.max(MCPToolInvocation.started_at).label("last_called_at"),
        )
        .select_from(MCPToolInvocation)
        .outerjoin(Workspace, Workspace.id == MCPToolInvocation.workspace_id)
        .where(
            *mcp_tool_scope_filters(
                organization_id=organization_id,
                started_at_from=started_at_from,
                started_at_to=started_at_to,
            )
        )
        .group_by(
            MCPToolInvocation.server_name,
            MCPToolInvocation.tool_name,
            MCPToolInvocation.workspace_id,
            Workspace.name,
        )
        .order_by(desc(call_count), desc(failed_calls), MCPToolInvocation.server_name.asc())
        .limit(limit)
    )
    return list(result.mappings().all())


async def llm_usage_summary_rows(
    session: AsyncSession,
    *,
    started_at_from: datetime,
    started_at_to: datetime,
    breakdown_limit: int,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
):
    usage_day = func.date(func.timezone("UTC", LLMUsageRecord.started_at))
    grouped = (
        select(
            LLMUsageRecord.user_id,
            LLMUsageRecord.workspace_id,
            LLMUsageRecord.agent_id,
            LLMUsageRecord.provider,
            LLMUsageRecord.model,
            usage_day.label("usage_day"),
            func.grouping(LLMUsageRecord.user_id).label("group_user"),
            func.grouping(LLMUsageRecord.workspace_id).label("group_workspace"),
            func.grouping(LLMUsageRecord.agent_id).label("group_agent"),
            func.grouping(LLMUsageRecord.provider).label("group_model"),
            func.grouping(usage_day).label("group_day"),
            *llm_usage_aggregate_columns(),
        )
        .where(
            *llm_usage_scope_filters(
                organization_id=organization_id,
                workspace_id=workspace_id,
                user_id=user_id,
                started_at_from=started_at_from,
                started_at_to=started_at_to,
            )
        )
        .group_by(
            func.grouping_sets(
                tuple_(),
                tuple_(LLMUsageRecord.user_id),
                tuple_(LLMUsageRecord.workspace_id),
                tuple_(LLMUsageRecord.agent_id),
                tuple_(LLMUsageRecord.provider, LLMUsageRecord.model),
                tuple_(usage_day),
            )
        )
        .cte("llm_usage_grouped")
    )
    group_key = case(
        (grouped.c.group_user == 0, literal("user")),
        (grouped.c.group_workspace == 0, literal("workspace")),
        (grouped.c.group_agent == 0, literal("agent")),
        (grouped.c.group_model == 0, literal("model")),
        (grouped.c.group_day == 0, literal("day")),
        else_=literal("total"),
    ).label("group_key")
    ranked = select(
        grouped,
        group_key,
        func.row_number()
        .over(
            partition_by=group_key,
            order_by=(grouped.c.cost_usd.desc(), grouped.c.requests.desc()),
        )
        .label("group_rank"),
    ).cte("llm_usage_ranked")
    result = await session.execute(
        select(
            ranked,
            User.first_name,
            User.last_name,
            User.email,
            Workspace.name.label("workspace_name"),
            Agent.name.label("agent_name"),
        )
        .outerjoin(User, ranked.c.user_id == User.id)
        .outerjoin(Workspace, ranked.c.workspace_id == Workspace.id)
        .outerjoin(Agent, ranked.c.agent_id == Agent.id)
        .where(
            or_(
                ranked.c.group_key.in_(("total", "day")),
                ranked.c.group_rank <= max(1, breakdown_limit),
            )
        )
        .order_by(ranked.c.group_key, ranked.c.group_rank)
    )
    return list(result.mappings().all())


async def mcp_tool_usage_summary_rows(
    session: AsyncSession,
    *,
    started_at_from: datetime,
    started_at_to: datetime,
    breakdown_limit: int,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
):
    usage_day = func.date(func.timezone("UTC", MCPToolInvocation.started_at))
    grouped = (
        select(
            MCPToolInvocation.user_id,
            MCPToolInvocation.workspace_id,
            MCPToolInvocation.agent_id,
            usage_day.label("usage_day"),
            func.grouping(MCPToolInvocation.user_id).label("group_user"),
            func.grouping(MCPToolInvocation.workspace_id).label("group_workspace"),
            func.grouping(MCPToolInvocation.agent_id).label("group_agent"),
            func.grouping(usage_day).label("group_day"),
            func.count(MCPToolInvocation.id).label("tool_calls"),
        )
        .where(
            *mcp_tool_scope_filters(
                organization_id=organization_id,
                workspace_id=workspace_id,
                user_id=user_id,
                started_at_from=started_at_from,
                started_at_to=started_at_to,
            )
        )
        .group_by(
            func.grouping_sets(
                tuple_(),
                tuple_(MCPToolInvocation.user_id),
                tuple_(MCPToolInvocation.workspace_id),
                tuple_(MCPToolInvocation.agent_id),
                tuple_(usage_day),
            )
        )
        .cte("mcp_tool_usage_grouped")
    )
    group_key = case(
        (grouped.c.group_user == 0, literal("user")),
        (grouped.c.group_workspace == 0, literal("workspace")),
        (grouped.c.group_agent == 0, literal("agent")),
        (grouped.c.group_day == 0, literal("day")),
        else_=literal("total"),
    ).label("group_key")
    ranked = select(
        grouped,
        group_key,
        func.row_number()
        .over(
            partition_by=group_key,
            order_by=grouped.c.tool_calls.desc(),
        )
        .label("group_rank"),
    ).cte("mcp_tool_usage_ranked")
    result = await session.execute(
        select(
            ranked,
            User.first_name,
            User.last_name,
            User.email,
            Workspace.name.label("workspace_name"),
            Agent.name.label("agent_name"),
        )
        .outerjoin(User, ranked.c.user_id == User.id)
        .outerjoin(Workspace, ranked.c.workspace_id == Workspace.id)
        .outerjoin(Agent, ranked.c.agent_id == Agent.id)
        .where(
            or_(
                ranked.c.group_key.in_(("total", "day")),
                ranked.c.group_rank <= max(1, breakdown_limit),
            )
        )
        .order_by(ranked.c.group_key, ranked.c.group_rank)
    )
    return list(result.mappings().all())


async def list_llm_usage_records_for_agent_run(
    session: AsyncSession,
    *,
    agent_run_id: UUID,
) -> list[LLMUsageRecord]:
    result = await session.execute(
        select(LLMUsageRecord)
        .where(LLMUsageRecord.agent_run_id == agent_run_id)
        .order_by(LLMUsageRecord.started_at, LLMUsageRecord.created_at)
    )
    return list(result.scalars().all())


async def list_model_prices(session: AsyncSession) -> list[LLMModelPrice]:
    result = await session.execute(
        select(LLMModelPrice).order_by(LLMModelPrice.provider, LLMModelPrice.model)
    )
    return list(result.scalars().all())


async def get_model_price_by_id(
    session: AsyncSession,
    *,
    price_id: UUID,
) -> LLMModelPrice | None:
    result = await session.execute(
        select(LLMModelPrice).where(LLMModelPrice.id == price_id)
    )
    return result.scalar_one_or_none()


async def get_model_price(
    session: AsyncSession,
    *,
    provider: str,
    model: str,
) -> LLMModelPrice | None:
    result = await session.execute(
        select(LLMModelPrice).where(
            LLMModelPrice.provider == provider,
            LLMModelPrice.model == model,
        )
    )
    return result.scalar_one_or_none()


async def list_model_prices_for_provider_models(
    session: AsyncSession,
    *,
    provider: str,
    models: list[str],
) -> list[LLMModelPrice]:
    if not models:
        return []
    result = await session.execute(
        select(LLMModelPrice).where(
            LLMModelPrice.provider == provider,
            LLMModelPrice.model.in_(models),
        )
    )
    return list(result.scalars().all())


async def save_model_price(
    session: AsyncSession,
    *,
    model_price: LLMModelPrice,
) -> LLMModelPrice:
    session.add(model_price)
    await session.flush()
    return model_price


async def delete_model_price(
    session: AsyncSession,
    *,
    model_price: LLMModelPrice,
) -> None:
    await session.delete(model_price)


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
