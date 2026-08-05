"""MCP installation, tool-discovery, and validation application services."""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from urllib.parse import urlparse

from app.core.pagination import CursorPageMetadata
from app.db.domain_types import MCPInstallationStatus
from app.modules.limits import service as limits_service
from app.modules.mcp_gateway.client import MCPGatewayUpstreamError
from app.modules.mcp_registry import repository, tool_repository
from app.modules.mcp_registry.catalog_service import server_update_available
from app.modules.mcp_registry.config_service import (
    externalize_install_config_secrets,
    install_config_values_from_secret_references,
    merged_install_config_values,
    parse_install_target_value,
    persist_install_secret_references,
    public_configured_values,
    resolve_install_config_values,
    secret_references_from_runtime_secret_config,
    validate_package_runtime_install,
)
from app.modules.mcp_registry.exceptions import (
    MCPServerInstallationFailedError,
    MCPServerInstallationNotFoundError,
    MCPServerInstallationUnsupportedError,
    MCPServerNotFoundError,
)
from app.modules.mcp_registry.installer import (
    install_server_runtime,
    remove_installation_artifacts,
)
from app.modules.mcp_registry.models import (
    MCPServerInstallation,
    MCPServerVersion,
)
from app.modules.mcp_registry.schemas import (
    MCPServerBulkUpdateRequest,
    MCPServerDocument,
    MCPServerInstallationListResponse,
    MCPServerInstallationRead,
    MCPServerInstallationToolsResponse,
    MCPServerInstallationToolValidationRequest,
    MCPServerInstallationToolValidationResponse,
    MCPServerInstallRequest,
    MCPServerToolRead,
)
from app.modules.mcp_registry.scope_service import (
    default_workspace_id,
    organization_id_for_workspace,
)
from app.modules.mcp_registry.telemetry import schedule_mcp_server_install_telemetry
from app.modules.mcp_registry.tool_service import (
    refresh_tool_schemas_for_installation,
    seed_tool_schemas_from_registry_metadata,
)
from app.modules.mcp_runtime import repository as runtime_repository
from app.modules.mcp_runtime.manager import (
    RUNTIME_PROVIDER_KUBERNETES,
    MCPRuntimeManager,
    get_runtime_manager,
)
from app.modules.mcp_runtime.service import call_tool_with_isolated_tracking
from app.modules.users.models import User

logger = logging.getLogger(__name__)
RUNTIME_NETWORK_POLICY_CONFIG_KEY = "networkPolicy"
DEFAULT_RUNTIME_NETWORK_POLICY_CONFIG = {
    "mode": "intent",
    "allowKubernetesApi": False,
    "allowRemoteMcpEgress": True,
    "allowRuntimeDependencyEgress": True,
    "denyOtherEgress": True,
    "isolationEnabled": True,
    "publicEgress": False,
    "privateEgress": False,
    "privateEgressPorts": [80, 443],
    "inClusterKubernetesApi": False,
    "customEgress": [],
    "remoteDestinations": [],
}


def installation_service_log_extra(
    *,
    workspace_id: uuid.UUID | None,
    server_name: str,
    version: str | None = None,
    config_name: str | None = None,
    installation_id: uuid.UUID | None = None,
    install_type: str | None = None,
    install_target: str | None = None,
) -> dict[str, str | None]:
    return {
        "workspace_id": str(workspace_id) if workspace_id else None,
        "mcp_server_name": server_name,
        "mcp_server_version": version,
        "mcp_config_name": config_name,
        "mcp_installation_id": str(installation_id) if installation_id else None,
        "mcp_install_type": install_type,
        "mcp_install_target": install_target,
    }


def installation_network_policy_config(
    installation: MCPServerInstallation | None,
) -> dict | None:
    if installation is None:
        return None
    runtime_config = installation.runtime_config or {}
    network_policy = runtime_config.get(RUNTIME_NETWORK_POLICY_CONFIG_KEY)
    if isinstance(network_policy, dict):
        return network_policy
    return None


def merged_install_network_policy_config(
    existing: MCPServerInstallation | None,
    requested,
) -> dict | None:
    if requested is not None:
        payload = requested.model_dump(mode="json", by_alias=True)
        explicit_intent_fields = {
            "allow_kubernetes_api",
            "allow_remote_mcp_egress",
            "allow_runtime_dependency_egress",
            "deny_other_egress",
        }
        if requested.model_fields_set.isdisjoint(explicit_intent_fields):
            payload.pop("allowKubernetesApi", None)
            payload.pop("allowRemoteMcpEgress", None)
            payload.pop("allowRuntimeDependencyEgress", None)
            payload.pop("denyOtherEgress", None)
            payload["mode"] = "legacy"
        else:
            payload["mode"] = "intent"
        return payload
    return installation_network_policy_config(existing)


def effective_runtime_network_policy_config(config: dict | None) -> dict:
    if not isinstance(config, dict):
        return dict(DEFAULT_RUNTIME_NETWORK_POLICY_CONFIG)
    effective = {**DEFAULT_RUNTIME_NETWORK_POLICY_CONFIG, **config}
    mode = str(config.get("mode") or "").strip().casefold()
    has_intent_fields = any(
        key in config
        for key in (
            "allowKubernetesApi",
            "allowRemoteMcpEgress",
            "allowRuntimeDependencyEgress",
            "denyOtherEgress",
        )
    )
    uses_intents = mode == "intent" or (mode != "legacy" and (not config or has_intent_fields))
    allow_kubernetes_api = bool(
        config.get("allowKubernetesApi", config.get("inClusterKubernetesApi", False))
    )
    if uses_intents:
        deny_other_egress = bool(
            config.get("denyOtherEgress", config.get("isolationEnabled", True))
        )
        effective["mode"] = "intent"
        effective["denyOtherEgress"] = deny_other_egress
        effective["isolationEnabled"] = deny_other_egress
        effective["publicEgress"] = False
        effective["privateEgress"] = False
        custom_egress = config.get("customEgress")
        effective["customEgress"] = custom_egress if isinstance(custom_egress, list) else []
    else:
        effective["mode"] = "legacy"
    effective["allowKubernetesApi"] = allow_kubernetes_api
    effective["inClusterKubernetesApi"] = allow_kubernetes_api
    return effective


def remote_mcp_policy_destinations(server: MCPServerVersion) -> list[dict[str, str | int]]:
    destinations: list[dict[str, str | int]] = []
    for index, remote in enumerate(server.remotes or []):
        if not isinstance(remote, dict):
            continue
        raw_url = str(remote.get("url") or "").strip()
        if not raw_url:
            continue
        parsed = urlparse(raw_url)
        if not parsed.hostname:
            continue
        scheme = parsed.scheme.casefold()
        port = parsed.port
        if port is None:
            port = 80 if scheme == "http" else 443
        if port < 1 or port > 65_535:
            continue
        destination: dict[str, str | int] = {
            "label": str(remote.get("name") or remote.get("type") or f"remote-{index + 1}")[:120],
            "host": parsed.hostname.rstrip(".").lower(),
            "port": port,
        }
        if destination not in destinations:
            destinations.append(destination)
    return destinations


def runtime_network_policy_with_remote_destinations(
    config: dict | None,
    server: MCPServerVersion,
) -> dict | None:
    if config is None:
        return None
    normalized = effective_runtime_network_policy_config(config)
    if normalized.get("mode") != "intent" or not bool(
        normalized.get("allowRemoteMcpEgress", True)
    ):
        normalized["remoteDestinations"] = []
        return normalized
    existing = normalized.get("remoteDestinations")
    if isinstance(existing, list) and existing:
        return normalized
    normalized["remoteDestinations"] = remote_mcp_policy_destinations(server)
    return normalized


def runtime_provider_probe(
    *,
    install_type: str = "package",
    runtime_config: dict | None = None,
    workspace_id: uuid.UUID | None = None,
    server_name: str = "",
    version: str = "",
) -> MCPServerInstallation:
    return MCPServerInstallation(
        workspace_id=workspace_id or uuid.uuid4(),
        server_name=server_name or "io.github.wardn/runtime-probe",
        config_name="default",
        installed_version=version or "probe",
        status="enabled",
        install_type=install_type,
        runtime_config=runtime_config or {"kind": install_type},
    )


def installation_runtime_provider_name(
    installation: MCPServerInstallation,
    *,
    manager: MCPRuntimeManager | None = None,
) -> str:
    return (manager or get_runtime_manager()).provider_name(installation)


def package_runtime_provider_name(
    *,
    manager: MCPRuntimeManager | None = None,
) -> str:
    return installation_runtime_provider_name(
        runtime_provider_probe(),
        manager=manager,
    )


def runtime_network_policy_custom_egress_count(config: dict) -> int:
    custom_egress = config.get("customEgress")
    return len(custom_egress) if isinstance(custom_egress, list) else 0


def install_target_runtime_provider_name(
    server: MCPServerVersion,
    payload: MCPServerInstallRequest,
    config_values: dict,
    *,
    manager: MCPRuntimeManager | None = None,
    workspace_id: uuid.UUID | None = None,
) -> str:
    target_kind, _ = parse_install_target_value(
        server,
        payload.install_target,
        config_values,
    )
    return installation_runtime_provider_name(
        runtime_provider_probe(
            install_type=target_kind,
            runtime_config={"kind": target_kind},
            workspace_id=workspace_id,
            server_name=server.name,
            version=server.version,
        ),
        manager=manager,
    )


def install_target_uses_runtime_network_policy(
    server: MCPServerVersion,
    payload: MCPServerInstallRequest,
    config_values: dict,
) -> bool:
    return (
        install_target_runtime_provider_name(server, payload, config_values)
        == RUNTIME_PROVIDER_KUBERNETES
    )


def runtime_network_policy_config_for_provider(
    *,
    network_policy_config: dict | None,
    network_policy_requested: bool,
    runtime_provider_name: str,
) -> dict | None:
    if runtime_provider_name == RUNTIME_PROVIDER_KUBERNETES:
        return network_policy_config
    if network_policy_requested:
        raise MCPServerInstallationUnsupportedError(
            "Runtime network policies require the Kubernetes runtime provider"
        )
    return None


async def require_install_network_policy_limits(
    session,
    *,
    organization_id: uuid.UUID | None,
    workspace_id: uuid.UUID,
    network_policy_config: dict | None,
) -> None:
    config = effective_runtime_network_policy_config(network_policy_config)
    scope_chain: list[tuple[str, uuid.UUID | None]] = [("workspace", workspace_id)]
    if organization_id is not None:
        scope_chain.append(("organization", organization_id))

    async def require_capability(limit_key: str, requested: int = 1) -> None:
        await limits_service.require_limit_available(
            session,
            limit_key=limit_key,
            scope_chain=scope_chain,
            current_count=0,
            requested=requested,
        )

    if not bool(config.get("isolationEnabled")):
        await require_capability(
            limits_service.MCP_RUNTIME_NETWORK_ISOLATION_DISABLE_PER_WORKSPACE
        )
        return
    if bool(config.get("publicEgress")):
        await require_capability(limits_service.MCP_RUNTIME_PUBLIC_EGRESS_PER_WORKSPACE)
    if bool(config.get("privateEgress")):
        await require_capability(limits_service.MCP_RUNTIME_PRIVATE_EGRESS_PER_WORKSPACE)
    if bool(config.get("inClusterKubernetesApi")):
        await require_capability(
            limits_service.MCP_RUNTIME_KUBERNETES_API_EGRESS_PER_WORKSPACE
        )

    custom_egress_count = runtime_network_policy_custom_egress_count(config)
    if custom_egress_count > 0:
        await require_capability(
            limits_service.MCP_RUNTIME_CUSTOM_EGRESS_RULES_PER_INSTALLATION,
            requested=custom_egress_count,
        )


async def installation_response(
    session,
    installation: MCPServerInstallation,
    organization_id: uuid.UUID | None = None,
    installed: MCPServerVersion | None = None,
    latest: MCPServerVersion | None = None,
) -> MCPServerInstallationRead:
    if installed is None or latest is None:
        organization_id = organization_id or await organization_id_for_workspace(
            session,
            installation.workspace_id,
        )
        installed = await repository.get_server_version(
            session,
            installation.server_name,
            installation.installed_version,
            include_deleted=True,
            organization_id=organization_id,
        )
        latest = await repository.get_server_version(
            session,
            installation.server_name,
            "latest",
            include_deleted=False,
            organization_id=organization_id,
        )
    if installed is None or latest is None:
        raise MCPServerNotFoundError("installed server version not found")

    return MCPServerInstallationRead(
        id=installation.id,
        workspace_id=installation.workspace_id,
        server_name=installation.server_name,
        config_name=installation.config_name or "default",
        installed_version=installation.installed_version,
        latest_version=latest.version,
        update_available=server_update_available(installation.installed_version, latest.version),
        status=installation.status,
        install_type=installation.install_type,
        runtime_provider=installation_runtime_provider_name(installation),
        install_path=installation.install_path,
        runtime_config=installation.runtime_config,
        configured_values=public_configured_values(installed, installation),
        install_error=installation.install_error or None,
        installed_at=installation.installed_at,
        updated_at=installation.updated_at,
        server=MCPServerDocument.model_validate(installed.server_json),
        latest_server=MCPServerDocument.model_validate(latest.server_json),
    )


async def list_installations(
    session,
    workspace_id: uuid.UUID | None = None,
    *,
    cursor: str | None = None,
    limit: int = 50,
) -> MCPServerInstallationListResponse:
    rows, next_cursor = await repository.list_installation_version_rows(
        session,
        workspace_id,
        cursor=cursor,
        limit=limit,
    )
    return MCPServerInstallationListResponse(
        installations=[
            await installation_response(
                session,
                installation,
                installed=installed,
                latest=latest,
            )
            for installation, installed, latest in rows
        ],
        metadata=CursorPageMetadata(count=len(rows), next_cursor=next_cursor),
        package_runtime_provider=package_runtime_provider_name(),
    )


def tool_schema_response(tool) -> MCPServerToolRead:
    return MCPServerToolRead(
        server_name=tool.server_name,
        server_version=tool.server_version,
        tool_name=tool.tool_name,
        title=tool.title or tool.tool_name,
        description=tool.description or "",
        input_schema=tool.input_schema or {"type": "object"},
        output_schema=tool.output_schema,
        annotations=tool.annotations or {},
    )


def first_text_content(result: dict | None) -> str:
    if not result:
        return ""
    content = result.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict):
            return str(first.get("text") or "")
    return ""


def validation_error_from_result(result: dict | None) -> str:
    text = first_text_content(result)
    if not result:
        return ""
    if result.get("isError"):
        return text

    normalized = text.strip().casefold()
    if normalized.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("error"), str):
            return payload["error"]
    if normalized.startswith(("invalid input", "invalid request", "error:")):
        return text
    return ""


async def list_installation_tools(
    session,
    installation_id,
    workspace_id: uuid.UUID | None = None,
) -> MCPServerInstallationToolsResponse:
    installation = await repository.get_installation_by_id(
        session,
        installation_id,
        workspace_id,
    )
    if installation is None:
        raise MCPServerInstallationNotFoundError("server configuration is not installed")

    organization_id = await organization_id_for_workspace(session, installation.workspace_id)
    server = await repository.get_server_version(
        session,
        installation.server_name,
        installation.installed_version,
        include_deleted=True,
        organization_id=organization_id,
    )
    if server is None:
        raise MCPServerNotFoundError("installed server version not found")

    logger.info(
        "Refreshing MCP installation tools.",
        extra=installation_service_log_extra(
            workspace_id=installation.workspace_id,
            server_name=installation.server_name,
            version=installation.installed_version,
            config_name=installation.config_name,
            installation_id=installation.id,
            install_type=installation.install_type,
        ),
    )
    refresh_result = await refresh_tool_schemas_for_installation(
        session,
        installation=installation,
        server=server,
    )

    tools = await tool_repository.list_active_tool_schemas(
        session,
        installation_id=installation.id,
        server_name=server.name,
        server_version=server.version,
    )
    logger.info(
        "Refreshed MCP installation tools.",
        extra={
            **installation_service_log_extra(
                workspace_id=installation.workspace_id,
                server_name=installation.server_name,
                version=installation.installed_version,
                config_name=installation.config_name,
                installation_id=installation.id,
                install_type=installation.install_type,
            ),
            "mcp_tool_count": len(tools),
        },
    )
    return MCPServerInstallationToolsResponse(
        server_name=installation.server_name,
        config_name=installation.config_name or "default",
        server_version=server.version,
        tools=[tool_schema_response(tool) for tool in tools],
        cache={
            "mode": getattr(refresh_result, "source", "live-refresh"),
            "refreshed": True,
        },
    )


async def validate_installation_tool(
    session,
    installation_id,
    payload: MCPServerInstallationToolValidationRequest,
    workspace_id: uuid.UUID | None = None,
) -> MCPServerInstallationToolValidationResponse:
    installation = await repository.get_installation_by_id(
        session,
        installation_id,
        workspace_id,
    )
    if installation is None:
        raise MCPServerInstallationNotFoundError("server configuration is not installed")

    organization_id = await organization_id_for_workspace(session, installation.workspace_id)
    server = await repository.get_server_version(
        session,
        installation.server_name,
        installation.installed_version,
        include_deleted=True,
        organization_id=organization_id,
    )
    if server is None:
        raise MCPServerNotFoundError("installed server version not found")

    error = ""
    error_type = None
    result = None
    logger.info(
        "Validating MCP installation tool.",
        extra={
            **installation_service_log_extra(
                workspace_id=installation.workspace_id,
                server_name=installation.server_name,
                version=installation.installed_version,
                config_name=installation.config_name,
                installation_id=installation.id,
                install_type=installation.install_type,
            ),
            "mcp_tool_name": payload.tool_name,
        },
    )
    try:
        result = await call_tool_with_isolated_tracking(
            session,
            installation,
            server,
            tool_name=payload.tool_name,
            arguments=payload.arguments,
        )
        error = validation_error_from_result(result)
        is_error = bool(error)
    except (MCPGatewayUpstreamError, ValueError) as exc:
        is_error = True
        error = str(exc)
        error_type = exc.__class__.__name__

    logger.info(
        "Validated MCP installation tool.",
        extra={
            **installation_service_log_extra(
                workspace_id=installation.workspace_id,
                server_name=installation.server_name,
                version=installation.installed_version,
                config_name=installation.config_name,
                installation_id=installation.id,
                install_type=installation.install_type,
            ),
            "mcp_tool_name": payload.tool_name,
            "mcp_validation_status": "failed" if is_error else "passed",
            "mcp_validation_error_type": error_type,
            "mcp_validation_error_present": bool(error),
        },
    )
    return MCPServerInstallationToolValidationResponse(
        server_name=installation.server_name,
        config_name=installation.config_name or "default",
        tool_name=payload.tool_name,
        status="failed" if is_error else "passed",
        is_error=is_error,
        error=error,
        result=result,
        validated_at=datetime.now(UTC),
    )


async def install_server_version(
    session,
    name: str,
    payload: MCPServerInstallRequest,
    workspace_id: uuid.UUID | None = None,
    user: User | None = None,
) -> MCPServerInstallationRead:
    workspace_id = workspace_id or await default_workspace_id(session)
    organization_id = await organization_id_for_workspace(session, workspace_id)
    server = await repository.get_server_version(
        session,
        name,
        payload.version,
        include_deleted=False,
        organization_id=organization_id,
    )
    if server is None:
        raise MCPServerNotFoundError("server version not found")

    await limits_service.lock_quota_capacity(
        session,
        [
            limits_service.quota_scope(
                limits_service.MCP_SERVER_INSTALLATIONS_PER_WORKSPACE,
                workspace_id,
            )
        ],
    )
    installation = await repository.get_installation(
        session,
        name,
        payload.config_name,
        workspace_id,
    )
    config_values = merged_install_config_values(installation, payload.config_values)
    network_policy_config = merged_install_network_policy_config(
        installation,
        payload.network_policy,
    )
    runtime_provider_name = install_target_runtime_provider_name(
        server,
        payload,
        config_values,
        workspace_id=workspace_id,
    )
    network_policy_config = runtime_network_policy_config_for_provider(
        network_policy_config=network_policy_config,
        network_policy_requested=payload.network_policy is not None,
        runtime_provider_name=runtime_provider_name,
    )
    network_policy_config = runtime_network_policy_with_remote_destinations(
        network_policy_config,
        server,
    )
    if runtime_provider_name == RUNTIME_PROVIDER_KUBERNETES:
        await require_install_network_policy_limits(
            session,
            organization_id=organization_id,
            workspace_id=workspace_id,
            network_policy_config=network_policy_config,
        )
    is_new_installation = installation is None
    logger.info(
        "Starting MCP server installation.",
        extra={
            **installation_service_log_extra(
                workspace_id=workspace_id,
                server_name=name,
                version=server.version,
                config_name=payload.config_name,
                installation_id=installation.id if installation else None,
                install_target=payload.install_target,
            ),
            "mcp_installation_new": is_new_installation,
        },
    )
    if is_new_installation:
        installation_count = await repository.count_installations_for_workspace(
            session,
            workspace_id,
        )
        scope_chain = [("workspace", workspace_id)]
        if organization_id is not None:
            scope_chain.insert(1, ("organization", organization_id))
        await limits_service.require_limit_available(
            session,
            limit_key=limits_service.MCP_SERVER_INSTALLATIONS_PER_WORKSPACE,
            scope_chain=scope_chain,
            current_count=installation_count,
        )
    if organization_id is not None:
        config_values = await externalize_install_config_secrets(
            session,
            user,
            organization_id,
            workspace_id,
            server,
            payload,
            config_values,
            existing_installation=installation,
        )
    resolved_config_values, handle_refs = await resolve_install_config_values(
        session,
        organization_id,
        workspace_id,
        config_values,
    )
    runtime_install = await asyncio.to_thread(
        install_server_runtime,
        server,
        config_values=resolved_config_values,
        install_target=payload.install_target,
        network_policy=network_policy_config,
        config_name=payload.config_name,
        workspace_id=str(workspace_id),
    )
    secret_references = secret_references_from_runtime_secret_config(
        runtime_install.secret_config,
        handle_refs,
    )
    persist_install_secret_references(runtime_install.install_path, secret_references)
    previous_install_path = installation.install_path if installation else ""
    if installation is None:
        installation = MCPServerInstallation(
            workspace_id=workspace_id,
            server_name=name,
            config_name=payload.config_name,
            installed_version=server.version,
            status=MCPInstallationStatus(runtime_install.status),
            install_type=runtime_install.install_type,
            install_path=runtime_install.install_path,
            runtime_config=runtime_install.runtime_config,
            secret_references=secret_references,
            install_error=runtime_install.install_error,
        )
        session.add(installation)
    else:
        installation.installed_version = server.version
        installation.status = MCPInstallationStatus(runtime_install.status)
        installation.install_type = runtime_install.install_type
        installation.install_path = runtime_install.install_path
        installation.runtime_config = runtime_install.runtime_config
        installation.secret_references = secret_references
        installation.install_error = runtime_install.install_error

    await session.flush()
    await session.refresh(installation)
    try:
        await validate_package_runtime_install(session, installation, server)
    except MCPServerInstallationFailedError:
        logger.warning(
            "MCP server installation validation failed.",
            extra=installation_service_log_extra(
                workspace_id=workspace_id,
                server_name=name,
                version=server.version,
                config_name=payload.config_name,
                installation_id=installation.id,
                install_type=runtime_install.install_type,
                install_target=payload.install_target,
            ),
        )
        if is_new_installation or previous_install_path != runtime_install.install_path:
            remove_installation_artifacts(runtime_install.install_path)
        raise

    if previous_install_path and previous_install_path != runtime_install.install_path:
        remove_installation_artifacts(previous_install_path)

    await seed_tool_schemas_from_registry_metadata(
        session,
        installation=installation,
        server=server,
    )
    schedule_mcp_server_install_telemetry(server, install_type=installation.install_type)
    response = await installation_response(session, installation, organization_id=organization_id)
    logger.info(
        "Completed MCP server installation.",
        extra={
            **installation_service_log_extra(
                workspace_id=workspace_id,
                server_name=name,
                version=server.version,
                config_name=installation.config_name,
                installation_id=installation.id,
                install_type=installation.install_type,
                install_target=payload.install_target,
            ),
            "mcp_install_status": str(installation.status),
        },
    )
    return response


async def uninstall_server(
    session,
    name: str,
    config_name: str = "default",
    workspace_id: uuid.UUID | None = None,
) -> None:
    workspace_id = workspace_id or await default_workspace_id(session)
    installation = await repository.get_installation(session, name, config_name, workspace_id)
    if installation is None:
        raise MCPServerInstallationNotFoundError("server is not installed")

    logger.info(
        "Uninstalling MCP server.",
        extra=installation_service_log_extra(
            workspace_id=workspace_id,
            server_name=installation.server_name,
            version=installation.installed_version,
            config_name=installation.config_name,
            installation_id=installation.id,
            install_type=installation.install_type,
        ),
    )
    await delete_installation_runtime_resources(session, installation)
    remove_installation_artifacts(installation.install_path)
    await repository.delete_installation(session, installation)
    await session.flush()
    logger.info(
        "Uninstalled MCP server.",
        extra=installation_service_log_extra(
            workspace_id=workspace_id,
            server_name=installation.server_name,
            version=installation.installed_version,
            config_name=installation.config_name,
            installation_id=installation.id,
            install_type=installation.install_type,
        ),
    )


async def uninstall_installation(
    session,
    installation_id,
    workspace_id: uuid.UUID | None = None,
) -> None:
    installation = await repository.get_installation_by_id(session, installation_id, workspace_id)
    if installation is None:
        raise MCPServerInstallationNotFoundError("server configuration is not installed")

    logger.info(
        "Uninstalling MCP server configuration.",
        extra=installation_service_log_extra(
            workspace_id=installation.workspace_id,
            server_name=installation.server_name,
            version=installation.installed_version,
            config_name=installation.config_name,
            installation_id=installation.id,
            install_type=installation.install_type,
        ),
    )
    await delete_installation_runtime_resources(session, installation)
    remove_installation_artifacts(installation.install_path)
    await repository.delete_installation(session, installation)
    await session.flush()
    logger.info(
        "Uninstalled MCP server configuration.",
        extra=installation_service_log_extra(
            workspace_id=installation.workspace_id,
            server_name=installation.server_name,
            version=installation.installed_version,
            config_name=installation.config_name,
            installation_id=installation.id,
            install_type=installation.install_type,
        ),
    )


async def delete_installation_runtime_resources(
    session,
    installation: MCPServerInstallation,
    *,
    manager: MCPRuntimeManager | None = None,
) -> None:
    runtime_sessions = await runtime_repository.list_runtime_sessions_for_installation(
        session,
        installation.id,
    )
    if not runtime_sessions:
        return

    manager = manager or get_runtime_manager()
    await session.commit()
    logger.info(
        "Deleting MCP installation runtime resources.",
        extra={
            **installation_service_log_extra(
                workspace_id=installation.workspace_id,
                server_name=installation.server_name,
                version=installation.installed_version,
                config_name=installation.config_name,
                installation_id=installation.id,
                install_type=installation.install_type,
            ),
            "mcp_runtime_session_count": len(runtime_sessions),
        },
    )
    for runtime_session in runtime_sessions:
        await asyncio.to_thread(
            manager.stop_runtime,
            runtime_session,
            delete_resources=True,
        )
    logger.info(
        "Deleted MCP installation runtime resources.",
        extra={
            **installation_service_log_extra(
                workspace_id=installation.workspace_id,
                server_name=installation.server_name,
                version=installation.installed_version,
                config_name=installation.config_name,
                installation_id=installation.id,
                install_type=installation.install_type,
            ),
            "mcp_runtime_session_count": len(runtime_sessions),
        },
    )


async def update_installed_servers(
    session,
    payload: MCPServerBulkUpdateRequest,
    workspace_id: uuid.UUID | None = None,
) -> MCPServerInstallationListResponse:
    workspace_id = workspace_id or await default_workspace_id(session)
    organization_id = await organization_id_for_workspace(session, workspace_id)
    updated: list[MCPServerInstallationRead] = []
    logger.info(
        "Starting MCP installed server bulk update.",
        extra={
            "organization_id": str(organization_id) if organization_id else None,
            "workspace_id": str(workspace_id),
            "mcp_server_count": len(payload.server_names),
        },
    )
    for server_name in payload.server_names:
        installations = await repository.list_installations_for_server(
            session,
            server_name,
            workspace_id,
        )
        if not installations:
            raise MCPServerInstallationNotFoundError("server is not installed")
        latest = await repository.get_server_version(
            session,
            server_name,
            "latest",
            include_deleted=False,
            organization_id=organization_id,
        )
        if latest is None:
            raise MCPServerNotFoundError("latest server version not found")
        for installation in installations:
            install_target = "remote" if installation.install_type == "remote" else "package"
            logger.info(
                "Updating MCP installed server.",
                extra=installation_service_log_extra(
                    workspace_id=workspace_id,
                    server_name=server_name,
                    version=latest.version,
                    config_name=installation.config_name,
                    installation_id=installation.id,
                    install_type=installation.install_type,
                    install_target=install_target,
                ),
            )
            config_values = install_config_values_from_secret_references(
                installation.secret_references
            )
            runtime_provider_name = installation_runtime_provider_name(installation)
            network_policy_config = runtime_network_policy_config_for_provider(
                network_policy_config=installation_network_policy_config(installation),
                network_policy_requested=False,
                runtime_provider_name=runtime_provider_name,
            )
            network_policy_config = runtime_network_policy_with_remote_destinations(
                network_policy_config,
                latest,
            )
            if runtime_provider_name == RUNTIME_PROVIDER_KUBERNETES:
                await require_install_network_policy_limits(
                    session,
                    organization_id=organization_id,
                    workspace_id=workspace_id,
                    network_policy_config=network_policy_config,
                )
            resolved_config_values, handle_refs = await resolve_install_config_values(
                session,
                organization_id,
                workspace_id,
                config_values,
            )
            runtime_install = await asyncio.to_thread(
                install_server_runtime,
                latest,
                config_values=resolved_config_values,
                install_target=install_target,
                network_policy=network_policy_config,
                config_name=installation.config_name,
                workspace_id=str(workspace_id),
            )
            secret_references = secret_references_from_runtime_secret_config(
                runtime_install.secret_config,
                handle_refs,
            )
            persist_install_secret_references(runtime_install.install_path, secret_references)
            previous_install_path = installation.install_path
            installation.installed_version = latest.version
            installation.status = MCPInstallationStatus(runtime_install.status)
            installation.install_type = runtime_install.install_type
            installation.install_path = runtime_install.install_path
            installation.runtime_config = runtime_install.runtime_config
            installation.secret_references = secret_references
            installation.install_error = runtime_install.install_error
            if previous_install_path and previous_install_path != runtime_install.install_path:
                remove_installation_artifacts(previous_install_path)
            await session.flush()
            await session.refresh(installation)
            logger.info(
                "Updated MCP installed server.",
                extra=installation_service_log_extra(
                    workspace_id=workspace_id,
                    server_name=server_name,
                    version=latest.version,
                    config_name=installation.config_name,
                    installation_id=installation.id,
                    install_type=installation.install_type,
                    install_target=install_target,
                ),
            )
            updated.append(
                await installation_response(
                    session,
                    installation,
                    organization_id=organization_id,
                )
            )

    logger.info(
        "Completed MCP installed server bulk update.",
        extra={
            "organization_id": str(organization_id) if organization_id else None,
            "workspace_id": str(workspace_id),
            "mcp_server_count": len(payload.server_names),
            "mcp_installation_update_count": len(updated),
        },
    )
    return MCPServerInstallationListResponse(
        installations=updated,
        metadata=CursorPageMetadata(count=len(updated), next_cursor=""),
        package_runtime_provider=package_runtime_provider_name(),
    )
