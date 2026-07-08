from argparse import Namespace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.llm_providers import commands
from app.modules.users.models import User


class FakeCallbackServer:
    def __init__(self, result_queue) -> None:
        self.result_queue = result_queue

    def serve_forever(self) -> None:
        self.result_queue.put("oauth-code")

    def shutdown(self) -> None:
        return None

    def server_close(self) -> None:
        return None


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def commit(self) -> None:
        return None


@pytest.mark.asyncio
async def test_connect_chatgpt_writes_tokens_and_creates_handle_credential(monkeypatch) -> None:
    organization_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=True)
    store_id = uuid4()
    access_handle_id = uuid4()
    refresh_handle_id = uuid4()
    calls = {}

    monkeypatch.setattr(
        commands,
        "start_callback_server",
        lambda state, result_queue: FakeCallbackServer(result_queue),
    )
    monkeypatch.setattr(commands.webbrowser, "open", lambda _url: None)
    monkeypatch.setattr(commands, "AsyncSessionLocal", lambda: FakeSession())

    async def request_chatgpt_device_code():
        return SimpleNamespace(
            device_auth_id="deviceauth-1",
            user_code="ABCD-EFGH",
            verification_url="https://auth.openai.com/codex/device",
            interval_seconds=1,
        )

    async def poll_chatgpt_device_authorization(_device_code):
        return SimpleNamespace(
            authorization_code="oauth-code",
            code_verifier="device-verifier",
        )

    monkeypatch.setattr(commands, "request_chatgpt_device_code", request_chatgpt_device_code)
    monkeypatch.setattr(
        commands,
        "poll_chatgpt_device_authorization",
        poll_chatgpt_device_authorization,
    )

    async def get_command_user(*args, **kwargs):
        return user

    monkeypatch.setattr(commands, "get_command_user", get_command_user)

    async def missing_credential(*args, **kwargs):
        return None

    monkeypatch.setattr(commands.llm_repository, "get_credential_by_name", missing_credential)

    async def exchange_chatgpt_oauth_code(*args, **kwargs):
        calls["exchange"] = kwargs
        return {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "expires_in": 3600,
        }

    async def write_secret_values(*args, **kwargs):
        calls["write"] = {"args": args, "kwargs": kwargs}

    async def create_secret_handle(*args, **kwargs):
        payload = args[3]
        key_name = payload.key_name
        handle_id = access_handle_id if key_name == "access_token" else refresh_handle_id
        calls.setdefault("handles", []).append(payload)
        return SimpleNamespace(id=handle_id)

    async def create_provider_credential(*args, **kwargs):
        payload = args[3]
        calls["credential"] = payload
        return SimpleNamespace(id=uuid4(), name=payload.name)

    monkeypatch.setattr(commands, "exchange_chatgpt_oauth_code", exchange_chatgpt_oauth_code)
    monkeypatch.setattr(commands, "write_secret_values", write_secret_values)
    monkeypatch.setattr(commands, "create_secret_handle", create_secret_handle)
    monkeypatch.setattr(commands, "create_provider_credential", create_provider_credential)
    monkeypatch.setattr(commands, "chatgpt_oauth_metadata", lambda _token: {"accountId": "acct"})

    await commands.connect_chatgpt_from_args(
        Namespace(
            organization_id=str(organization_id),
            credential_id="",
            user_email=user.email,
            user_id="",
            name="Team ChatGPT",
            visibility="organization",
            workspace_id="",
            secret_store_id=str(store_id),
            secret_path="wardn/custom/chatgpt",
            flow="device",
            no_browser=True,
            timeout_seconds=5,
        )
    )

    assert calls["exchange"] == {
        "code": "oauth-code",
        "code_verifier": "device-verifier",
        "redirect_uri": commands.CHATGPT_DEVICE_AUTH_CALLBACK_URL,
    }
    assert calls["write"]["args"][2] == organization_id
    assert calls["write"]["args"][3] == store_id
    assert calls["write"]["kwargs"]["external_ref"] == "wardn/custom/chatgpt"
    assert calls["write"]["kwargs"]["values"] == {
        "access_token": "access-token",
        "refresh_token": "refresh-token",
    }
    assert [handle.key_name for handle in calls["handles"]] == [
        "access_token",
        "refresh_token",
    ]
    assert calls["handles"][0].display_name.startswith("Team ChatGPT access token ")
    assert calls["handles"][1].display_name.startswith("Team ChatGPT refresh token ")
    credential = calls["credential"]
    assert credential.name == "Team ChatGPT"
    assert credential.oauth_access_token_secret_handle_id == access_handle_id
    assert credential.oauth_refresh_token_secret_handle_id == refresh_handle_id


@pytest.mark.asyncio
async def test_connect_chatgpt_reconnects_existing_credential(monkeypatch) -> None:
    organization_id = uuid4()
    credential_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=True)
    credential = SimpleNamespace(
        id=credential_id,
        name="Team ChatGPT",
        provider="openai_chatgpt",
        auth_method="oauth",
        oauth_provider="chatgpt",
        visibility="organization",
        workspace_id=None,
    )
    calls = {}

    monkeypatch.setattr(
        commands,
        "start_callback_server",
        lambda state, result_queue: FakeCallbackServer(result_queue),
    )
    monkeypatch.setattr(commands.webbrowser, "open", lambda _url: None)
    monkeypatch.setattr(commands, "AsyncSessionLocal", lambda: FakeSession())

    async def request_chatgpt_device_code():
        return SimpleNamespace(
            device_auth_id="deviceauth-1",
            user_code="ABCD-EFGH",
            verification_url="https://auth.openai.com/codex/device",
            interval_seconds=1,
        )

    async def poll_chatgpt_device_authorization(_device_code):
        return SimpleNamespace(
            authorization_code="oauth-code",
            code_verifier="device-verifier",
        )

    monkeypatch.setattr(commands, "request_chatgpt_device_code", request_chatgpt_device_code)
    monkeypatch.setattr(
        commands,
        "poll_chatgpt_device_authorization",
        poll_chatgpt_device_authorization,
    )

    async def get_command_user(*args, **kwargs):
        return user

    async def get_credential(*args, **kwargs):
        assert kwargs["credential_id"] == credential_id
        return credential

    async def require_scope_permission(*args, **kwargs):
        calls.setdefault("permission", []).append(kwargs)

    async def exchange_chatgpt_oauth_code(*args, **kwargs):
        return {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 3600,
        }

    async def replace_chatgpt_oauth_credential_tokens(*args, **kwargs):
        calls["replace"] = {"args": args, "kwargs": kwargs}

    async def fail_create_provider_credential(*args, **kwargs):
        raise AssertionError("reconnect should not create a credential")

    monkeypatch.setattr(commands, "get_command_user", get_command_user)
    monkeypatch.setattr(commands.llm_repository, "get_credential", get_credential)
    monkeypatch.setattr(commands, "require_scope_permission", require_scope_permission)
    monkeypatch.setattr(commands, "user_can_see_credential", lambda _user, _credential: True)
    monkeypatch.setattr(commands, "exchange_chatgpt_oauth_code", exchange_chatgpt_oauth_code)
    monkeypatch.setattr(
        commands,
        "replace_chatgpt_oauth_credential_tokens",
        replace_chatgpt_oauth_credential_tokens,
    )
    monkeypatch.setattr(
        commands,
        "create_provider_credential",
        fail_create_provider_credential,
    )

    await commands.connect_chatgpt_from_args(
        Namespace(
            organization_id=str(organization_id),
            credential_id=str(credential_id),
            user_email=user.email,
            user_id="",
            name="ignored",
            visibility="organization",
            workspace_id="",
            secret_store_id="",
            secret_path="",
            flow="device",
            no_browser=True,
            timeout_seconds=5,
        )
    )

    assert calls["permission"] == [
        {
            "visibility": "organization",
            "workspace_id": None,
        },
        {
            "visibility": "organization",
            "workspace_id": None,
        },
    ]
    assert calls["replace"]["args"][1] is credential
    assert calls["replace"]["args"][2]["access_token"] == "new-access-token"
