import base64
import hashlib
import hmac
import html
import json
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from urllib.parse import parse_qs, urlencode, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import SecretStr, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import create_session_token, verify_session_token
from app.db.session import get_db_session
from app.modules.organizations import repository as organizations_repository
from app.modules.organizations.service import ORG_ADMIN_ROLES
from app.modules.users import repository as users_repository
from app.modules.users.exceptions import InvalidAPITokenScopeError, InvalidLoginError
from app.modules.users.models import User
from app.modules.users.oidc import oidc_enabled
from app.modules.users.schemas import LoginRequest, UserAPITokenCreate
from app.modules.users.service import authenticate_local_user, create_user_api_token

MCP_OAUTH_SCOPE = "mcp:tools"
AUTH_CODE_TTL_SECONDS = 5 * 60
CLIENT_TTL_SECONDS = 365 * 24 * 60 * 60
_USED_AUTH_CODE_IDS: set[str] = set()

oauth_router = APIRouter(prefix="/oauth", tags=["mcp-oauth"], include_in_schema=False)
well_known_router = APIRouter(tags=["mcp-oauth"], include_in_schema=False)


def public_base_url(request: Request) -> str:
    configured = get_settings().public_base_url.strip().rstrip("/")
    if configured:
        return configured
    forwarded_host = request.headers.get("x-forwarded-host", "").strip()
    forwarded_proto = request.headers.get("x-forwarded-proto", "").strip()
    if forwarded_host and forwarded_proto in {"http", "https"}:
        return f"{forwarded_proto}://{forwarded_host}".rstrip("/")
    return str(request.base_url).rstrip("/")


def mcp_resource_url(request: Request, resource_path: str | None = None) -> str:
    if resource_path:
        return f"{public_base_url(request)}/{resource_path.strip('/')}"
    return f"{public_base_url(request)}{get_settings().api_prefix}/mcp/gateway"


def direct_mcp_resource_url(request: Request) -> str:
    return f"{str(request.base_url).rstrip('/')}{get_settings().api_prefix}/mcp/gateway"


def accepted_mcp_resource_urls(request: Request) -> set[str]:
    return {
        mcp_resource_url(request),
        direct_mcp_resource_url(request),
    }


def protected_resource_metadata_url(request: Request) -> str:
    return f"{public_base_url(request)}/.well-known/oauth-protected-resource"


def authorization_issuer(request: Request) -> str:
    return public_base_url(request)


def authorization_endpoint(request: Request) -> str:
    return f"{public_base_url(request)}{get_settings().api_prefix}/oauth/authorize"


def token_endpoint(request: Request) -> str:
    return f"{public_base_url(request)}{get_settings().api_prefix}/oauth/token"


def registration_endpoint(request: Request) -> str:
    return f"{public_base_url(request)}{get_settings().api_prefix}/oauth/register"


def authorize_path() -> str:
    return f"{get_settings().api_prefix}/oauth/authorize"


def bearer_challenge(request: Request, *, error: str | None = None) -> str:
    parameters = [
        f'resource_metadata="{protected_resource_metadata_url(request)}"',
        f'scope="{MCP_OAUTH_SCOPE}"',
    ]
    if error:
        parameters.insert(0, f'error="{error}"')
    return f"Bearer {', '.join(parameters)}"


def b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def signing_secret() -> bytes:
    return get_settings().session_secret.encode("utf-8")


def signed_payload(payload: dict[str, Any]) -> str:
    body = b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = hmac.new(signing_secret(), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{b64url_encode(signature)}"


def verify_signed_payload(token: str) -> dict[str, Any]:
    try:
        body, signature = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("invalid signed token") from exc

    expected = b64url_encode(
        hmac.new(signing_secret(), body.encode("ascii"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(signature, expected):
        raise ValueError("invalid signed token")

    payload = json.loads(b64url_decode(body))
    if not isinstance(payload, dict):
        raise ValueError("invalid signed token")

    expires_at = payload.get("exp")
    if not isinstance(expires_at, int | float) or expires_at < time.time():
        raise ValueError("expired signed token")
    return payload


def safe_redirect_uri(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme == "https" and parsed.netloc:
        return True
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        return True
    return False


def create_client_id(payload: dict[str, Any]) -> str:
    now = int(time.time())
    return signed_payload(
        {
            "typ": "mcp_client",
            "iat": now,
            "exp": now + CLIENT_TTL_SECONDS,
            "client_name": str(payload.get("client_name") or "MCP client"),
            "redirect_uris": payload.get("redirect_uris") or [],
        }
    )


def client_metadata(client_id: str) -> dict[str, Any]:
    payload = verify_signed_payload(client_id)
    if payload.get("typ") != "mcp_client":
        raise ValueError("invalid client_id")
    redirect_uris = payload.get("redirect_uris")
    if not isinstance(redirect_uris, list):
        raise ValueError("invalid client_id")
    return payload


def validate_redirect_uri(client_id: str, redirect_uri: str) -> dict[str, Any]:
    metadata = client_metadata(client_id)
    allowed = {str(uri) for uri in metadata.get("redirect_uris", [])}
    if redirect_uri not in allowed:
        raise ValueError("redirect_uri is not registered for this client")
    return metadata


def code_challenge_for_verifier(verifier: str) -> str:
    return b64url_encode(hashlib.sha256(verifier.encode("ascii")).digest())


def append_query(url: str, values: dict[str, str]) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(values)}"


def authorize_request_path(params: dict[str, str]) -> str:
    query = urlencode(params)
    path = authorize_path()
    return f"{path}?{query}" if query else path


def oidc_login_redirect(params: dict[str, str]) -> RedirectResponse:
    settings = get_settings()
    login_url = (
        f"{settings.frontend_base_url.rstrip('/')}/api/auth/oidc/login"
        if settings.frontend_base_url.strip()
        else f"{settings.api_prefix}/auth/oidc/login"
    )
    return RedirectResponse(
        append_query(login_url, {"redirectTo": authorize_request_path(params)}),
        status_code=status.HTTP_302_FOUND,
    )


def html_page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)}</title>
  <style>
    body {{
      font-family: system-ui, sans-serif;
      max-width: 32rem;
      margin: 4rem auto;
      padding: 0 1rem;
      color: #172033;
    }}
    label {{ display: block; margin: 1rem 0 .375rem; font-size: .875rem; font-weight: 600; }}
    input, select {{
      width: 100%;
      box-sizing: border-box;
      border: 1px solid #cbd5e1;
      border-radius: .375rem;
      padding: .625rem .75rem;
    }}
    button {{
      margin-top: 1rem;
      border: 0;
      border-radius: .375rem;
      padding: .625rem .875rem;
      background: #2563eb;
      color: white;
      font-weight: 600;
    }}
    .muted {{ color: #64748b; font-size: .875rem; }}
    .error {{ color: #b91c1c; }}
  </style>
</head>
<body>{body}</body>
</html>"""
    )


def set_session_cookie(response: Response, user: User) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=create_session_token(user.id),
        httponly=True,
        secure=settings.environment != "local",
        samesite="lax",
        max_age=settings.session_ttl_seconds,
        path="/",
    )


async def current_session_user(request: Request, session: AsyncSession) -> User | None:
    session_token = request.cookies.get(get_settings().session_cookie_name)
    user_id = verify_session_token(session_token) if session_token else None
    if user_id is None:
        return None
    user = await users_repository.get_user_by_id(session, user_id)
    if user is None or not user.is_active:
        return None
    return user


def validate_authorize_params(params: dict[str, str], *, expected_resources: set[str]) -> None:
    if params.get("response_type") != "code":
        raise ValueError("response_type must be code")
    if not params.get("client_id"):
        raise ValueError("client_id is required")
    if not params.get("redirect_uri"):
        raise ValueError("redirect_uri is required")
    if not params.get("code_challenge"):
        raise ValueError("code_challenge is required")
    if params.get("code_challenge_method") != "S256":
        raise ValueError("code_challenge_method must be S256")
    if not params.get("resource"):
        raise ValueError("resource is required")
    if params["resource"] not in expected_resources:
        raise ValueError("resource does not match this MCP server")
    validate_redirect_uri(params["client_id"], params["redirect_uri"])


async def mcp_scope_options(session: AsyncSession, user: User) -> list[dict[str, str]]:
    if user.is_superuser:
        organization_rows = await organizations_repository.list_organizations_for_user(
            session, user.id
        )
    else:
        organization_rows = await organizations_repository.list_joined_organizations_for_user(
            session, user.id
        )

    options: list[dict[str, str]] = []
    for organization, organization_membership in organization_rows:
        if organization.status != "active":
            continue
        organization_label = organization.name or organization.slug
        options.append(
            {
                "value": f"organization:{organization.id}",
                "label": f"{organization_label} (organization)",
                "kind": "organization",
                "id": str(organization.id),
                "name": organization_label,
            }
        )

        workspace_rows = await organizations_repository.list_workspaces_for_user(
            session,
            organization.id,
            user.id,
        )
        can_use_all_workspaces = (
            user.is_superuser
            or organization_membership is not None
            and organization_membership.role in ORG_ADMIN_ROLES
        )
        for workspace, workspace_membership in workspace_rows:
            if workspace.status != "active":
                continue
            if not can_use_all_workspaces and workspace_membership is None:
                continue
            workspace_label = workspace.name or workspace.slug
            options.append(
                {
                    "value": f"workspace:{workspace.id}",
                    "label": f"{organization_label} / {workspace_label} (workspace)",
                    "kind": "workspace",
                    "id": str(workspace.id),
                    "name": workspace_label,
                }
            )
    return options


async def selected_mcp_scope(
    session: AsyncSession,
    user: User,
    scope_target: str,
) -> dict[str, str]:
    options = await mcp_scope_options(session, user)
    for option in options:
        if option["value"] == scope_target:
            return option
    raise ValueError("selected organization or workspace is not available")


def hidden_authorize_inputs(params: dict[str, str]) -> str:
    return "\n".join(
        (
            f'<input type="hidden" name="{html.escape(key, quote=True)}" '
            f'value="{html.escape(value, quote=True)}" />'
        )
        for key, value in params.items()
        if key not in {"email", "password", "scopeTarget"}
    )


async def consent_form(
    session: AsyncSession,
    user: User,
    params: dict[str, str],
    *,
    error: str = "",
) -> HTMLResponse:
    options = await mcp_scope_options(session, user)
    if not options:
        return html_page(
            "Authorization error",
            (
                "<h1>Authorization error</h1>"
                "<p>No active organizations or workspaces are available.</p>"
            ),
        )

    selected = params.get("scopeTarget") or options[0]["value"]
    option_html = "\n".join(
        (
            f'<option value="{html.escape(option["value"], quote=True)}"'
            f'{" selected" if option["value"] == selected else ""}>'
            f'{html.escape(option["label"])}</option>'
        )
        for option in options
    )
    error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
    client_name = "MCP client"
    try:
        client_name = str(client_metadata(params["client_id"]).get("client_name") or client_name)
    except (KeyError, ValueError):
        pass

    return html_page(
        "Authorize Wardn MCP",
        f"""
<h1>Authorize Wardn MCP</h1>
<p class="muted">{html.escape(client_name)} is requesting access to Wardn MCP tools.</p>
{error_html}
<form method="post" action="{authorize_path()}">
  {hidden_authorize_inputs(params)}
  <label for="scopeTarget">Access scope</label>
  <select id="scopeTarget" name="scopeTarget" required>
    {option_html}
  </select>
  <button type="submit">Authorize</button>
</form>
""",
    )


def authorization_code(user: User, params: dict[str, str], token_scope: dict[str, str]) -> str:
    now = int(time.time())
    return signed_payload(
        {
            "typ": "mcp_auth_code",
            "jti": secrets.token_urlsafe(16),
            "iat": now,
            "exp": now + AUTH_CODE_TTL_SECONDS,
            "user_id": str(user.id),
            "client_id": params["client_id"],
            "redirect_uri": params["redirect_uri"],
            "code_challenge": params["code_challenge"],
            "resource": params["resource"],
            "scope": params.get("scope") or MCP_OAUTH_SCOPE,
            "token_scope_kind": token_scope["kind"],
            "token_scope_id": token_scope["id"],
            "token_scope_name": token_scope["name"],
        }
    )


def authorize_redirect(
    user: User,
    params: dict[str, str],
    token_scope: dict[str, str],
) -> RedirectResponse:
    query = {"code": authorization_code(user, params, token_scope)}
    if params.get("state"):
        query["state"] = params["state"]
    return RedirectResponse(append_query(params["redirect_uri"], query), status_code=302)


def login_form(params: dict[str, str], *, error: str = "") -> HTMLResponse:
    error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
    client_name = "MCP client"
    try:
        client_name = str(client_metadata(params["client_id"]).get("client_name") or client_name)
    except (KeyError, ValueError):
        pass
    return html_page(
        "Authorize Wardn MCP",
        f"""
<h1>Authorize Wardn MCP</h1>
<p class="muted">{html.escape(client_name)} is requesting access to Wardn MCP tools.</p>
{error_html}
<form method="post" action="{authorize_path()}">
  {hidden_authorize_inputs(params)}
  <label for="email">Email</label>
  <input id="email" name="email" type="email" autocomplete="email" required />
  <label for="password">Password</label>
  <input id="password" name="password" type="password" autocomplete="current-password" required />
  <button type="submit">Authorize</button>
</form>
""",
    )


def protected_resource_metadata_response(
    request: Request,
    resource_path: str | None = None,
) -> JSONResponse:
    return JSONResponse(
        {
            "resource": mcp_resource_url(request, resource_path),
            "authorization_servers": [authorization_issuer(request)],
            "scopes_supported": [MCP_OAUTH_SCOPE],
            "bearer_methods_supported": ["header"],
        }
    )


def authorization_server_metadata_response(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "issuer": authorization_issuer(request),
            "authorization_endpoint": authorization_endpoint(request),
            "token_endpoint": token_endpoint(request),
            "registration_endpoint": registration_endpoint(request),
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": [MCP_OAUTH_SCOPE],
            "resource_parameter_supported": True,
        }
    )


@well_known_router.get("/.well-known/oauth-protected-resource")
async def protected_resource_metadata(request: Request) -> JSONResponse:
    return protected_resource_metadata_response(request)


@well_known_router.get("/.well-known/oauth-protected-resource/{resource_path:path}")
async def protected_resource_metadata_for_path(
    request: Request,
    resource_path: str,
) -> JSONResponse:
    return protected_resource_metadata_response(request, resource_path)


@well_known_router.get("/.well-known/oauth-authorization-server")
async def authorization_server_metadata(request: Request) -> JSONResponse:
    return authorization_server_metadata_response(request)


@well_known_router.get("/.well-known/oauth-authorization-server/{resource_path:path}")
async def authorization_server_metadata_for_path(
    request: Request,
    resource_path: str,
) -> JSONResponse:
    return authorization_server_metadata_response(request)


@well_known_router.get("/.well-known/openid-configuration")
async def openid_configuration(request: Request) -> JSONResponse:
    return authorization_server_metadata_response(request)


@well_known_router.get("/.well-known/openid-configuration/{resource_path:path}")
async def openid_configuration_for_path(
    request: Request,
    resource_path: str,
) -> JSONResponse:
    return authorization_server_metadata_response(request)


@oauth_router.post("/register", status_code=status.HTTP_201_CREATED)
async def register_client(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid client metadata") from exc

    redirect_uris = payload.get("redirect_uris")
    if not isinstance(redirect_uris, list) or not redirect_uris:
        raise HTTPException(status_code=400, detail="redirect_uris is required")
    if not all(isinstance(uri, str) and safe_redirect_uri(uri) for uri in redirect_uris):
        raise HTTPException(status_code=400, detail="invalid redirect_uri")

    client_id = create_client_id(payload)
    return JSONResponse(
        {
            "client_id": client_id,
            "client_id_issued_at": int(time.time()),
            "client_name": str(payload.get("client_name") or "MCP client"),
            "redirect_uris": redirect_uris,
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
        status_code=status.HTTP_201_CREATED,
    )


@oauth_router.get("/authorize")
async def authorize(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
):
    params = {key: value for key, value in request.query_params.items()}
    try:
        validate_authorize_params(params, expected_resources=accepted_mcp_resource_urls(request))
    except ValueError as exc:
        return html_page(
            "Authorization error",
            f"<h1>Authorization error</h1><p>{html.escape(str(exc))}</p>",
        )

    user = await current_session_user(request, session)
    if user is not None:
        return await consent_form(session, user, params)
    if oidc_enabled(get_settings()):
        return oidc_login_redirect(params)
    return login_form(params)


@oauth_router.post("/authorize")
async def authorize_with_password(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
):
    raw_body = (await request.body()).decode("utf-8")
    form = {key: values[-1] for key, values in parse_qs(raw_body).items() if values}
    session_user = await current_session_user(request, session)

    try:
        validate_authorize_params(form, expected_resources=accepted_mcp_resource_urls(request))
        user = session_user
        just_logged_in = False
        if user is None:
            if oidc_enabled(get_settings()):
                return oidc_login_redirect(form)
            login = LoginRequest(
                email=form.get("email", ""),
                password=SecretStr(form.get("password", "")),
            )
            user = await authenticate_local_user(session, login)
            just_logged_in = True
    except (InvalidLoginError, ValidationError):
        return login_form(form, error="Invalid email or password.")
    except ValueError as exc:
        return html_page(
            "Authorization error",
            f"<h1>Authorization error</h1><p>{html.escape(str(exc))}</p>",
        )

    if not form.get("scopeTarget"):
        response = await consent_form(session, user, form)
        if just_logged_in:
            set_session_cookie(response, user)
            await session.commit()
        return response

    try:
        token_scope = await selected_mcp_scope(session, user, form["scopeTarget"])
    except ValueError as exc:
        response = await consent_form(session, user, form, error=str(exc))
        if just_logged_in:
            set_session_cookie(response, user)
            await session.commit()
        return response

    await session.commit()
    response = authorize_redirect(user, form, token_scope)
    if just_logged_in:
        set_session_cookie(response, user)
    return response


@oauth_router.post("/token")
async def exchange_token(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> JSONResponse:
    form = {key: values[-1] for key, values in parse_qs((await request.body()).decode()).items()}
    if form.get("grant_type") != "authorization_code":
        raise HTTPException(status_code=400, detail="unsupported grant_type")

    try:
        code = verify_signed_payload(form.get("code", ""))
        if code.get("typ") != "mcp_auth_code":
            raise ValueError("invalid authorization code")
        if form.get("client_id") != code.get("client_id"):
            raise ValueError("client_id mismatch")
        if form.get("redirect_uri") != code.get("redirect_uri"):
            raise ValueError("redirect_uri mismatch")
        if form.get("resource") != code.get("resource"):
            raise ValueError("resource mismatch")
        if code_challenge_for_verifier(form.get("code_verifier", "")) != code.get(
            "code_challenge"
        ):
            raise ValueError("invalid code_verifier")
        code_id = str(code.get("jti") or "")
        if not code_id or code_id in _USED_AUTH_CODE_IDS:
            raise ValueError("authorization code already used")
        _USED_AUTH_CODE_IDS.add(code_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    user = await users_repository.get_user_by_id(session, code["user_id"])
    if user is None or not user.is_active:
        raise HTTPException(status_code=400, detail="authorization user is no longer active")

    client = client_metadata(str(code["client_id"]))
    token_scope_kind = str(code.get("token_scope_kind") or "")
    token_scope_id = str(code.get("token_scope_id") or "")
    token_scope_name = str(code.get("token_scope_name") or "Wardn")
    if token_scope_kind not in {"organization", "workspace"} or not token_scope_id:
        raise HTTPException(status_code=400, detail="authorization code is missing token scope")

    try:
        organization_ids = [token_scope_id] if token_scope_kind == "organization" else []
        workspace_ids = [token_scope_id] if token_scope_kind == "workspace" else []
        _record, access_token = await create_user_api_token(
            session,
            user.id,
            UserAPITokenCreate(
                name=f"MCP OAuth: {client.get('client_name') or 'MCP client'}",
                description=f"Issued for {token_scope_kind} scope: {token_scope_name}.",
                expires_at=datetime.now(UTC) + timedelta(days=30),
                organization_ids=organization_ids,
                workspace_ids=workspace_ids,
            ),
        )
    except InvalidAPITokenScopeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await session.commit()
    return JSONResponse(
        {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": 30 * 24 * 60 * 60,
            "scope": code.get("scope") or MCP_OAUTH_SCOPE,
        }
    )
