"""Installation configuration and secret-materialization application services."""

import re
import uuid
from copy import deepcopy
from pathlib import Path

from app.modules.mcp_registry.exceptions import (
    MCPServerInstallationFailedError,
    MCPServerInstallationNotFoundError,
    MCPServerInstallationUnsupportedError,
)
from app.modules.mcp_registry.installer import (
    ConfigValues,
    config_file_content,
    config_value_mapping,
    config_value_present,
    config_value_text,
    file_config_definition,
    safe_path_component,
    selected_install_target,
    write_secret_manifest,
)
from app.modules.mcp_registry.models import MCPServerInstallation, MCPServerVersion
from app.modules.mcp_registry.schemas import (
    MCPSecretHandleConfigValue,
    MCPServerInstallRequest,
)
from app.modules.mcp_registry.tool_service import refresh_tool_schemas_for_installation
from app.modules.mcp_runtime.manager import RUNTIME_PROVIDER_KUBERNETES, get_runtime_manager
from app.modules.secrets.exceptions import SecretsError
from app.modules.secrets.schemas import SecretHandleCreate, SecretPurpose
from app.modules.secrets.service import create_secret_handle, resolve_secret, write_secret_values
from app.modules.users.models import User

MCP_INSTALL_SECRET_VALUE_KEY_PATTERN = re.compile(r"[^a-zA-Z0-9._-]+")


SECRET_HANDLE_REF_TYPE = "secret_handle"


def secret_handle_ref(handle_id: uuid.UUID | str) -> dict[str, str]:
    return {"type": SECRET_HANDLE_REF_TYPE, "secretHandleId": str(handle_id)}


def secret_handle_id_from_value(value) -> uuid.UUID | None:
    if isinstance(value, MCPSecretHandleConfigValue):
        return value.secret_handle_id
    mapping = config_value_mapping(value)
    if mapping.get("type") != SECRET_HANDLE_REF_TYPE:
        return None
    raw_handle_id = mapping.get("secretHandleId") or mapping.get("secret_handle_id")
    if not raw_handle_id:
        return None
    return uuid.UUID(str(raw_handle_id))


def parse_install_target_value(
    server: MCPServerVersion,
    install_target: str | None,
    config_values: ConfigValues,
) -> tuple[str, int]:
    raw_target = install_target or selected_install_target(server, config_values)
    kind, _, raw_index = raw_target.partition(":")
    kind = kind if kind in {"remote", "package"} else "package"
    try:
        index = int(raw_index or "0")
    except ValueError:
        index = 0
    return kind, max(index, 0)


def install_secret_key_name(field_name: str) -> str:
    key = MCP_INSTALL_SECRET_VALUE_KEY_PATTERN.sub("_", field_name.strip()).strip("._-")
    return key[:120] or "value"


def install_secret_display_name(config_name: str, field_name: str, run_id: str) -> str:
    label = field_name.removeprefix("headers.").replace("_", " ").strip()
    display_name = f"MCP {config_name} {label} {run_id}"
    return display_name[:100].strip()


def install_secret_path(
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    server_name: str,
    config_name: str,
    run_id: str,
) -> str:
    return "/".join(
        [
            "wardn",
            "organizations",
            str(organization_id),
            "workspaces",
            str(workspace_id),
            "mcp",
            safe_path_component(server_name),
            f"{safe_path_component(config_name)}-{run_id}",
        ]
    )


def selected_install_secret_fields(
    server: MCPServerVersion,
    install_target: str | None,
    config_values: ConfigValues,
) -> dict[str, SecretPurpose]:
    kind, index = parse_install_target_value(server, install_target, config_values)
    fields: dict[str, SecretPurpose] = {}

    if kind == "remote":
        remote = (server.remotes or [])[index] if index < len(server.remotes or []) else {}
        headers = remote.get("headers") if isinstance(remote, dict) else None
        if isinstance(headers, list):
            for header in headers:
                if not isinstance(header, dict) or not header.get("isSecret"):
                    continue
                name = str(header.get("name") or "").strip()
                if name:
                    fields[name] = "mcp_header"
    else:
        package = (server.packages or [])[index] if index < len(server.packages or []) else {}
        environment = package.get("environmentVariables") if isinstance(package, dict) else None
        if isinstance(environment, list):
            for env_var in environment:
                if not isinstance(env_var, dict) or not env_var.get("isSecret"):
                    continue
                name = str(env_var.get("name") or "").strip()
                if name:
                    fields[name] = "mcp_env"
        package_arguments = package.get("packageArguments") if isinstance(package, dict) else None
        if isinstance(package_arguments, list):
            for argument in package_arguments:
                if not isinstance(argument, dict):
                    continue
                name = str(argument.get("name") or "").strip()
                if not name:
                    continue
                if file_config_definition(argument):
                    fields[name] = "mcp_file"
                elif argument.get("isSecret"):
                    fields[name] = "runtime_config"

    for key, value in config_values.items():
        if str(key).startswith("headers."):
            fields[str(key)] = "mcp_header"
        elif config_value_mapping(value).get("type") == "file":
            fields[str(key)] = "mcp_file"
    return fields


def install_secret_value(value) -> tuple[str, dict | None]:
    mapping = config_value_mapping(value)
    if mapping.get("type") != "file":
        return config_value_text(value), None

    content = config_file_content(value)
    replacement = {
        key: item
        for key, item in mapping.items()
        if key not in {"content", "contentBase64", "content_base64", "path"}
    }
    replacement["type"] = "file"
    replacement.setdefault("filename", "")
    return content, replacement


async def externalize_install_config_secrets(
    session,
    user: User | None,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    server: MCPServerVersion,
    payload: MCPServerInstallRequest,
    config_values: ConfigValues,
) -> ConfigValues:
    secret_fields = selected_install_secret_fields(server, payload.install_target, config_values)
    raw_values: dict[str, str] = {}
    replacements: dict[str, dict | None] = {}
    field_key_names: dict[str, str] = {}

    for field_name in secret_fields:
        value = config_values.get(field_name)
        if not config_value_present(value) or secret_handle_id_from_value(value):
            continue
        mapping = config_value_mapping(value)
        if mapping.get("type") == "file" and secret_handle_id_from_value(mapping.get("content")):
            continue
        secret_value, replacement = install_secret_value(value)
        if not secret_value:
            continue
        key_name = install_secret_key_name(field_name)
        candidate = key_name
        counter = 2
        while candidate in raw_values:
            candidate = f"{key_name}_{counter}"
            counter += 1
        raw_values[candidate] = secret_value
        replacements[field_name] = replacement
        field_key_names[field_name] = candidate

    if not raw_values:
        return config_values
    if payload.config_secret_store_id is None:
        raise MCPServerInstallationUnsupportedError("secret backend is required for MCP secrets")
    if user is None:
        raise MCPServerInstallationUnsupportedError(
            "authenticated user is required for MCP secrets"
        )

    run_id = uuid.uuid4().hex[:8]
    external_ref = install_secret_path(
        organization_id,
        workspace_id,
        server.name,
        payload.config_name,
        run_id,
    )
    primary_purpose: SecretPurpose = next(iter(secret_fields.values()), "other")
    try:
        await write_secret_values(
            session,
            user,
            organization_id,
            payload.config_secret_store_id,
            workspace_id=workspace_id,
            external_ref=external_ref,
            values=raw_values,
            purpose=primary_purpose,
        )
    except SecretsError as exc:
        raise MCPServerInstallationUnsupportedError(str(exc)) from exc

    updated = dict(config_values)
    for field_name, key_name in field_key_names.items():
        purpose: SecretPurpose = secret_fields[field_name]
        try:
            handle = await create_secret_handle(
                session,
                user,
                organization_id,
                SecretHandleCreate(
                    store_id=payload.config_secret_store_id,
                    workspace_id=workspace_id,
                    purpose=purpose,
                    display_name=install_secret_display_name(
                        payload.config_name,
                        field_name,
                        run_id,
                    ),
                    external_ref=external_ref,
                    key_name=key_name,
                    metadata={
                        "serverName": server.name,
                        "configName": payload.config_name,
                        "configField": field_name,
                        "installTarget": payload.install_target or "",
                    },
                ),
            )
        except SecretsError as exc:
            raise MCPServerInstallationUnsupportedError(str(exc)) from exc

        replacement = replacements[field_name]
        if replacement is not None:
            updated[field_name] = {**replacement, "content": secret_handle_ref(handle.id)}
        else:
            updated[field_name] = secret_handle_ref(handle.id)
    return updated


async def resolve_install_config_values(
    session,
    organization_id: uuid.UUID | None,
    workspace_id: uuid.UUID,
    config_values: ConfigValues,
) -> tuple[ConfigValues, dict[str, uuid.UUID]]:
    resolved: ConfigValues = {}
    handle_refs: dict[str, uuid.UUID] = {}
    for key, value in config_values.items():
        handle_id = secret_handle_id_from_value(value)
        mapping = config_value_mapping(value)
        content_handle_id = None
        if handle_id is None and mapping.get("type") == "file":
            content_handle_id = secret_handle_id_from_value(mapping.get("content"))
        if handle_id is None and content_handle_id is None:
            resolved[key] = value
            continue
        if content_handle_id is not None:
            handle_id = content_handle_id
        assert handle_id is not None
        if organization_id is None:
            raise MCPServerInstallationNotFoundError("workspace is not configured")
        try:
            secret = await resolve_secret(
                session,
                organization_id,
                handle_id,
                workspace_id=workspace_id,
            )
        except SecretsError as exc:
            raise MCPServerInstallationNotFoundError(str(exc)) from exc
        if content_handle_id is not None:
            resolved[key] = {**mapping, "content": secret.value}
        else:
            resolved[key] = secret.value
        handle_refs[key] = handle_id
    return resolved, handle_refs


def secret_references_from_runtime_secret_config(
    secret_config: dict | None,
    handle_refs: dict[str, uuid.UUID],
) -> dict:
    if not secret_config:
        return {}
    references = deepcopy(secret_config)
    for namespace in ("headers", "environment", "packageArguments"):
        namespace_values = references.get(namespace)
        if not isinstance(namespace_values, dict):
            continue
        for key in list(namespace_values):
            if key in handle_refs:
                namespace_values[key] = secret_handle_ref(handle_refs[key])
            elif namespace == "headers" and f"headers.{key}" in handle_refs:
                namespace_values[key] = secret_handle_ref(handle_refs[f"headers.{key}"])
    files = references.get("files")
    if isinstance(files, dict):
        for key, detail in files.items():
            if key in handle_refs and isinstance(detail, dict):
                detail["content"] = secret_handle_ref(handle_refs[key])
    return references


def persist_install_secret_references(install_path: str, secret_references: dict) -> None:
    if not secret_references or not install_path:
        return
    path = Path(install_path)
    if path.exists():
        write_secret_manifest(path, secret_references)


async def validate_package_runtime_install(
    session,
    installation: MCPServerInstallation,
    server: MCPServerVersion,
) -> None:
    if installation.install_type != "package":
        return
    manager = get_runtime_manager()
    try:
        provider_name = manager.provider_name(installation)
    except Exception as exc:
        detail = str(exc) or exc.__class__.__name__
        raise MCPServerInstallationFailedError(detail) from exc
    if provider_name != RUNTIME_PROVIDER_KUBERNETES:
        return

    try:
        await refresh_tool_schemas_for_installation(
            session,
            installation=installation,
            server=server,
            runtime_manager=manager,
        )
    except Exception as exc:
        detail = str(exc) or exc.__class__.__name__
        raise MCPServerInstallationFailedError(detail) from exc


def install_config_values_from_secret_references(secret_references: dict | None) -> ConfigValues:
    if not secret_references:
        return {}
    values: ConfigValues = {}
    for namespace in ("headers", "environment", "packageArguments"):
        namespace_values = secret_references.get(namespace)
        if isinstance(namespace_values, dict):
            values.update(
                {
                    str(key): value
                    for key, value in namespace_values.items()
                    if value is not None
                }
            )
    files = secret_references.get("files")
    if isinstance(files, dict):
        for name, detail in files.items():
            if not isinstance(detail, dict):
                continue
            content = detail.get("content")
            if content is None:
                continue
            values[str(name)] = {
                "type": "file",
                "filename": str(detail.get("filename") or ""),
                "content": content,
            }
    return values


def visible_config_field_names(
    server: MCPServerVersion,
    installation: MCPServerInstallation,
) -> set[str]:
    runtime_config = installation.runtime_config or {}
    package = runtime_config.get("package")
    transport = runtime_config.get("transport")
    definitions = []

    for package_definition in server.packages or []:
        definitions.extend(package_definition.get("environmentVariables", []))
        definitions.extend(package_definition.get("packageArguments", []))
    for remote in server.remotes or []:
        definitions.extend(remote.get("headers", []))

    if isinstance(package, dict):
        definitions.extend(package.get("environmentVariables", []))
        definitions.extend(package.get("packageArguments", []))
    if isinstance(transport, dict):
        definitions.extend(transport.get("headers", []))

    return {
        str(definition.get("name"))
        for definition in definitions
        if isinstance(definition, dict)
        and definition.get("name")
        and not definition.get("isSecret")
    }


def public_config_value(value) -> str:
    mapping = config_value_mapping(value)
    if not mapping:
        return config_value_text(value)
    return str(mapping.get("filename") or "configured")


def public_configured_values(
    server: MCPServerVersion,
    installation: MCPServerInstallation,
) -> dict[str, str]:
    visible_names = visible_config_field_names(server, installation)
    stored_values = install_config_values_from_secret_references(installation.secret_references)
    return {
        key: public_config_value(value)
        for key, value in stored_values.items()
        if key in visible_names
    }


def merged_install_config_values(
    existing: MCPServerInstallation | None,
    new_values: ConfigValues,
) -> ConfigValues:
    merged = install_config_values_from_secret_references(
        existing.secret_references if existing else None
    )
    merged.update({key: value for key, value in new_values.items() if config_value_present(value)})
    return merged
