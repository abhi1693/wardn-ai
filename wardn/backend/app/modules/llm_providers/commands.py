import argparse
import asyncio
import queue
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse
from uuid import UUID

from pydantic import SecretStr, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.commands.registry import CommandRegistry
from app.db.session import AsyncSessionLocal
from app.modules.llm_providers.exceptions import (
    DuplicateLLMProviderCredentialError,
    InvalidLLMProviderCredentialAuthError,
    InvalidLLMProviderCredentialScopeError,
)
from app.modules.llm_providers.schemas import LLMProviderCredentialCreate
from app.modules.llm_providers.service import (
    CHATGPT_OAUTH_SCOPE,
    OPENAI_CHATGPT_PROVIDER,
    build_chatgpt_authorization_url,
    chatgpt_oauth_metadata,
    create_provider_credential,
    exchange_chatgpt_oauth_code,
    expires_at_from_seconds,
    generate_oauth_state,
    generate_pkce_pair,
)
from app.modules.organizations.exceptions import (
    OrganizationAccessDeniedError,
    OrganizationNotFoundError,
    WorkspaceAccessDeniedError,
    WorkspaceNotFoundError,
)
from app.modules.users import repository as user_repository

CALLBACK_HOST = "localhost"
CALLBACK_PORT = 1455
CALLBACK_PATH = "/auth/callback"
REDIRECT_URI = f"http://{CALLBACK_HOST}:{CALLBACK_PORT}{CALLBACK_PATH}"


def configure_connectchatgpt_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--organization-id", required=True, help="Organization UUID.")
    parser.add_argument("--user-email", default="", help="Wardn user email to own the credential.")
    parser.add_argument("--user-id", default="", help="Wardn user UUID to own the credential.")
    parser.add_argument("--name", default="OpenAI ChatGPT", help="Credential name.")
    parser.add_argument(
        "--visibility",
        choices=("organization", "workspace", "user"),
        default="organization",
        help="Credential visibility.",
    )
    parser.add_argument("--workspace-id", default="", help="Workspace UUID for workspace scope.")
    parser.add_argument(
        "--default",
        action="store_true",
        dest="is_default",
        help="Mark this as the default OpenAI ChatGPT credential for the selected scope.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Print the authorization URL without opening a browser.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=15 * 60,
        help="Seconds to wait for the localhost OAuth callback.",
    )


def oauth_success_html() -> bytes:
    return (
        b"<!doctype html><html><body>"
        b"<h1>Authentication completed</h1>"
        b"<p>You can close this window and return to the Wardn command.</p>"
        b"</body></html>"
    )


def oauth_error_html(message: str) -> bytes:
    return (
        "<!doctype html><html><body>"
        "<h1>Authentication failed</h1>"
        f"<p>{message}</p>"
        "</body></html>"
    ).encode()


def start_callback_server(state: str, result_queue: queue.Queue[str]) -> HTTPServer:
    class CallbackHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return

        def respond(self, status_code: int, body: bytes) -> None:
            self.send_response(status_code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            url = urlparse(self.path)
            if url.path != CALLBACK_PATH:
                self.respond(404, oauth_error_html("Callback route not found."))
                return
            params = parse_qs(url.query)
            if params.get("state", [""])[0] != state:
                self.respond(400, oauth_error_html("State mismatch."))
                return
            error = params.get("error", [""])[0]
            if error:
                result_queue.put(f"ERROR:{error}")
                self.respond(400, oauth_error_html(error))
                return
            code = params.get("code", [""])[0]
            if not code:
                self.respond(400, oauth_error_html("Missing authorization code."))
                return
            result_queue.put(code)
            self.respond(200, oauth_success_html())

    return HTTPServer((CALLBACK_HOST, CALLBACK_PORT), CallbackHandler)


async def get_command_user(session, *, user_id: str, user_email: str):
    if user_id:
        user = await user_repository.get_user_by_id(session, UUID(user_id))
    elif user_email:
        user = await user_repository.get_user_by_email(session, user_email)
    else:
        raise ValueError("--user-email or --user-id is required")
    if user is None or not user.is_active:
        raise ValueError("Wardn user not found or inactive")
    return user


async def connect_chatgpt_from_args(args: argparse.Namespace) -> None:
    organization_id = UUID(args.organization_id)
    workspace_id = UUID(args.workspace_id) if args.workspace_id else None
    if args.visibility == "workspace" and workspace_id is None:
        raise ValueError("--workspace-id is required when --visibility workspace")
    if args.visibility != "workspace" and workspace_id is not None:
        raise ValueError("--workspace-id is only valid for workspace visibility")

    verifier, challenge = generate_pkce_pair()
    state = generate_oauth_state()
    authorization_url = build_chatgpt_authorization_url(
        state=state,
        code_challenge=challenge,
        redirect_uri=REDIRECT_URI,
    )

    result_queue: queue.Queue[str] = queue.Queue(maxsize=1)
    server = start_callback_server(state, result_queue)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        print("Open this URL to connect ChatGPT:")
        print(authorization_url)
        if not args.no_browser:
            webbrowser.open(authorization_url)
        code = result_queue.get(timeout=args.timeout_seconds)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    if code.startswith("ERROR:"):
        raise InvalidLLMProviderCredentialAuthError(code.removeprefix("ERROR:"))

    token_payload = await exchange_chatgpt_oauth_code(
        code=code,
        code_verifier=verifier,
        redirect_uri=REDIRECT_URI,
    )

    async with AsyncSessionLocal() as session:
        user = await get_command_user(
            session,
            user_id=args.user_id,
            user_email=args.user_email,
        )
        credential = await create_provider_credential(
            session,
            user,
            organization_id,
            LLMProviderCredentialCreate(
                name=args.name,
                provider=OPENAI_CHATGPT_PROVIDER,
                visibility=args.visibility,
                workspaceId=workspace_id,
                authMethod="oauth",
                oauthProvider="chatgpt",
                oauthAccessToken=SecretStr(token_payload["access_token"]),
                oauthRefreshToken=SecretStr(token_payload["refresh_token"]),
                oauthExpiresAt=expires_at_from_seconds(token_payload.get("expires_in")),
                oauthScopes=CHATGPT_OAUTH_SCOPE.split(),
                oauthMetadata=chatgpt_oauth_metadata(token_payload["access_token"]),
                isDefault=args.is_default,
            ),
        )
        await session.commit()
        print(f"ChatGPT credential connected: {credential.name} ({credential.id})")


def handle_connectchatgpt(args: argparse.Namespace) -> int:
    try:
        asyncio.run(connect_chatgpt_from_args(args))
    except queue.Empty:
        print("Error: timed out waiting for ChatGPT OAuth callback.", file=sys.stderr)
        return 1
    except (
        DuplicateLLMProviderCredentialError,
        InvalidLLMProviderCredentialAuthError,
        InvalidLLMProviderCredentialScopeError,
        OrganizationAccessDeniedError,
        OrganizationNotFoundError,
        WorkspaceAccessDeniedError,
        WorkspaceNotFoundError,
        ValidationError,
        ValueError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(
            f"Error: could not start localhost OAuth callback on port {CALLBACK_PORT}: {exc}",
            file=sys.stderr,
        )
        return 1
    except SQLAlchemyError as exc:
        print(f"Database error: {exc}", file=sys.stderr)
        return 1
    return 0


def register_llm_provider_commands(registry: CommandRegistry) -> None:
    registry.register(
        "connectchatgpt",
        "Connect an OpenAI ChatGPT OAuth credential using a localhost callback.",
        configure_connectchatgpt_parser,
        handle_connectchatgpt,
    )
