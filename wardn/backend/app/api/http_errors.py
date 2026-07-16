import logging
import re
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.responses import JSONResponse

from app.core.pagination import InvalidCursorError
from app.modules.agents.exceptions import (
    AgentNotFoundError,
    DuplicateAgentError,
    InvalidAgentScopeError,
    InvalidAgentToolAssignmentError,
)
from app.modules.agents.types import AgentChatProviderError
from app.modules.guardrails.exceptions import (
    DuplicateGuardrailPolicyError,
    GuardrailPolicyNotFoundError,
    InvalidGuardrailPolicyError,
)
from app.modules.limits.exceptions import (
    InvalidLimitKeyError,
    InvalidLimitScopeError,
    LimitAccessDeniedError,
    LimitExceededError,
    LimitNotFoundError,
)
from app.modules.llm_providers.exceptions import (
    DuplicateLLMProviderCredentialError,
    InvalidLLMProviderCredentialAuthError,
    InvalidLLMProviderCredentialScopeError,
    LLMProviderCredentialNotFoundError,
)
from app.modules.mcp_registry.exceptions import (
    DuplicateMCPCatalogSourceError,
    DuplicateMCPServerVersionError,
    InvalidRegistryCursorError,
    MCPCatalogSourceNotFoundError,
    MCPOperationJobNotFoundError,
    MCPServerInstallationFailedError,
    MCPServerInstallationNotFoundError,
    MCPServerInstallationUnsupportedError,
    MCPServerNotFoundError,
    MCPServerVersionInUseError,
)
from app.modules.organizations.exceptions import (
    DuplicateOrganizationError,
    DuplicateWorkspaceError,
    OrganizationAccessDeniedError,
    OrganizationNotFoundError,
    WorkspaceAccessDeniedError,
    WorkspaceNotFoundError,
)
from app.modules.secrets.exceptions import (
    DuplicateSecretHandleError,
    DuplicateSecretStoreError,
    InvalidSecretHandleError,
    InvalidSecretStoreError,
    SecretHandleNotFoundError,
    SecretProviderError,
    SecretStoreNotFoundError,
)
from app.modules.users.exceptions import (
    BootstrapUserExistsError,
    DuplicateUserError,
    InvalidAPITokenScopeError,
    InvalidLoginError,
    OIDCAuthenticationError,
    OIDCConfigurationError,
    UserAPITokenNotFoundError,
    UserNotFoundError,
)

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
PROBLEM_CONTENT_TYPE = "application/problem+json"
SAFE_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


@dataclass(frozen=True)
class ErrorDefinition:
    status_code: int
    code: str
    title: str


def _definition(status_code: int, code: str) -> ErrorDefinition:
    try:
        title = HTTPStatus(status_code).phrase
    except ValueError:
        title = "Request Failed"
    return ErrorDefinition(
        status_code=status_code,
        code=code,
        title=title,
    )


DOMAIN_ERRORS: dict[type[Exception], ErrorDefinition] = {
    OrganizationNotFoundError: _definition(404, "organization_not_found"),
    WorkspaceNotFoundError: _definition(404, "workspace_not_found"),
    OrganizationAccessDeniedError: _definition(403, "organization_access_denied"),
    WorkspaceAccessDeniedError: _definition(403, "workspace_access_denied"),
    DuplicateOrganizationError: _definition(409, "organization_already_exists"),
    DuplicateWorkspaceError: _definition(409, "workspace_already_exists"),
    LimitAccessDeniedError: _definition(403, "limit_access_denied"),
    LimitNotFoundError: _definition(404, "limit_not_found"),
    InvalidLimitKeyError: _definition(400, "invalid_limit_key"),
    InvalidLimitScopeError: _definition(400, "invalid_limit_scope"),
    LimitExceededError: _definition(403, "limit_exceeded"),
    AgentNotFoundError: _definition(404, "agent_not_found"),
    DuplicateAgentError: _definition(409, "agent_already_exists"),
    InvalidAgentScopeError: _definition(400, "invalid_agent_scope"),
    InvalidAgentToolAssignmentError: _definition(400, "invalid_agent_tool_assignment"),
    LLMProviderCredentialNotFoundError: _definition(404, "llm_credential_not_found"),
    DuplicateLLMProviderCredentialError: _definition(409, "llm_credential_already_exists"),
    InvalidLLMProviderCredentialScopeError: _definition(400, "invalid_llm_credential_scope"),
    InvalidLLMProviderCredentialAuthError: _definition(400, "invalid_llm_credential_auth"),
    SecretStoreNotFoundError: _definition(404, "secret_store_not_found"),
    SecretHandleNotFoundError: _definition(404, "secret_handle_not_found"),
    DuplicateSecretStoreError: _definition(409, "secret_store_already_exists"),
    DuplicateSecretHandleError: _definition(409, "secret_handle_already_exists"),
    InvalidSecretStoreError: _definition(400, "invalid_secret_store"),
    InvalidSecretHandleError: _definition(400, "invalid_secret_handle"),
    SecretProviderError: _definition(400, "secret_provider_error"),
    GuardrailPolicyNotFoundError: _definition(404, "guardrail_policy_not_found"),
    DuplicateGuardrailPolicyError: _definition(409, "guardrail_policy_already_exists"),
    InvalidGuardrailPolicyError: _definition(400, "invalid_guardrail_policy"),
    DuplicateMCPServerVersionError: _definition(409, "mcp_server_version_already_exists"),
    MCPServerNotFoundError: _definition(404, "mcp_server_not_found"),
    MCPServerInstallationNotFoundError: _definition(404, "mcp_installation_not_found"),
    MCPServerInstallationFailedError: _definition(502, "mcp_installation_failed"),
    MCPServerInstallationUnsupportedError: _definition(400, "mcp_installation_unsupported"),
    MCPServerVersionInUseError: _definition(409, "mcp_server_version_in_use"),
    InvalidRegistryCursorError: _definition(400, "invalid_registry_cursor"),
    MCPCatalogSourceNotFoundError: _definition(404, "mcp_catalog_source_not_found"),
    DuplicateMCPCatalogSourceError: _definition(409, "mcp_catalog_source_already_exists"),
    MCPOperationJobNotFoundError: _definition(404, "mcp_operation_job_not_found"),
    InvalidCursorError: _definition(400, "invalid_cursor"),
    DuplicateUserError: _definition(409, "user_already_exists"),
    BootstrapUserExistsError: _definition(409, "bootstrap_user_already_exists"),
    UserNotFoundError: _definition(404, "user_not_found"),
    UserAPITokenNotFoundError: _definition(404, "api_token_not_found"),
    InvalidLoginError: _definition(401, "invalid_login"),
    InvalidAPITokenScopeError: _definition(400, "invalid_api_token_scope"),
    OIDCConfigurationError: _definition(503, "oidc_configuration_error"),
    OIDCAuthenticationError: _definition(401, "oidc_authentication_error"),
}


def request_id_for(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id:
        return request_id
    request_id = uuid.uuid4().hex
    request.state.request_id = request_id
    return request_id


def _problem_response(
    request: Request,
    definition: ErrorDefinition,
    detail: str,
    *,
    headers: dict[str, str] | None = None,
    errors: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    request_id = request_id_for(request)
    response_headers = dict(headers or {})
    response_headers[REQUEST_ID_HEADER] = request_id
    body = {
        "type": f"urn:wardn:error:{definition.code}",
        "title": definition.title,
        "status": definition.status_code,
        "detail": detail,
        "instance": request.url.path,
        "code": definition.code,
        "requestId": request_id,
    }
    if errors is not None:
        body["errors"] = errors
    return JSONResponse(
        status_code=definition.status_code,
        content=jsonable_encoder(body),
        headers=response_headers,
        media_type=PROBLEM_CONTENT_TYPE,
    )


async def domain_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, AgentChatProviderError):
        definition = _definition(exc.status_code, "agent_chat_provider_error")
    else:
        definition = next(
            DOMAIN_ERRORS[exception_type]
            for exception_type in type(exc).__mro__
            if exception_type in DOMAIN_ERRORS
        )
    return _problem_response(request, definition, str(exc))


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    definition = _definition(exc.status_code, f"http_{exc.status_code}")
    detail = exc.detail if isinstance(exc.detail, str) else definition.title
    return _problem_response(request, definition, detail, headers=exc.headers)


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError | ValidationError,
) -> JSONResponse:
    definition = _definition(422, "request_validation_error")
    return _problem_response(
        request,
        definition,
        "Request validation failed.",
        errors=jsonable_encoder(exc.errors()),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = request_id_for(request)
    logger.exception("Unhandled request error", extra={"request_id": request_id})
    return _problem_response(
        request,
        _definition(500, "internal_server_error"),
        "An unexpected error occurred.",
    )


def configure_error_handling(app: FastAPI) -> None:
    for exception_type in DOMAIN_ERRORS:
        app.add_exception_handler(exception_type, domain_exception_handler)
    app.add_exception_handler(AgentChatProviderError, domain_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(ValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
