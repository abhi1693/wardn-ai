import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.mcp_registry import router, source_metadata
from app.modules.mcp_registry.schemas import MCPRepositoryMetadataImportRequest
from app.modules.mcp_registry.source_metadata_rate_limit import (
    RepositoryMetadataRateLimitResult,
)


def test_parse_github_repository_url_rejects_non_github_hosts() -> None:
    with pytest.raises(source_metadata.InvalidGitHubRepositoryURLError):
        source_metadata.parse_github_repository_url("https://example.com/acme/server")


def test_repository_metadata_endpoint_rejects_unauthenticated_requests() -> None:
    response = TestClient(create_app()).post(
        f"/api/v1/organizations/{uuid4()}/mcp/registry/source-metadata",
        json={"repositoryUrl": "https://github.com/acme/server"},
    )

    assert response.status_code == 401


@pytest.mark.parametrize(
    "repository_url",
    (
        "https://github.com/-invalid/server",
        "https://github.com/acme/server%2Fother",
        "https://github.com/acme/invalid repository",
    ),
)
def test_parse_github_repository_url_rejects_invalid_identifiers(
    repository_url: str,
) -> None:
    with pytest.raises(source_metadata.InvalidGitHubRepositoryURLError):
        source_metadata.parse_github_repository_url(repository_url)


class _RecordingSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_import_route_authorizes_before_consuming_rate_limit(monkeypatch) -> None:
    async def deny(*_args) -> None:
        raise HTTPException(status_code=403, detail="organization access denied")

    async def unexpected_rate_limit(*_args, **_kwargs):
        raise AssertionError("rate limit must not be consumed before authorization")

    monkeypatch.setattr(router, "require_organization_admin_or_404", deny)
    monkeypatch.setattr(
        router,
        "consume_repository_metadata_rate_limit",
        unexpected_rate_limit,
    )

    with pytest.raises(HTTPException) as caught:
        await router.import_organization_mcp_repository_metadata(
            uuid4(),
            MCPRepositoryMetadataImportRequest(repositoryUrl="https://github.com/acme/server"),
            _RecordingSession(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
        )

    assert caught.value.status_code == 403


@pytest.mark.asyncio
async def test_import_route_commits_shared_rate_limit_before_returning_429(monkeypatch) -> None:
    async def authorize(*_args) -> None:
        return None

    async def reject(*_args, **_kwargs) -> RepositoryMetadataRateLimitResult:
        return RepositoryMetadataRateLimitResult(allowed=False, retry_after_seconds=42)

    async def unexpected_import(*_args, **_kwargs):
        raise AssertionError("GitHub must not be called after the rate limit is exceeded")

    monkeypatch.setattr(router, "require_organization_admin_or_404", authorize)
    monkeypatch.setattr(router, "consume_repository_metadata_rate_limit", reject)
    monkeypatch.setattr(router, "import_repository_metadata", unexpected_import)
    session = _RecordingSession()

    with pytest.raises(HTTPException) as caught:
        await router.import_organization_mcp_repository_metadata(
            uuid4(),
            MCPRepositoryMetadataImportRequest(repositoryUrl="https://github.com/acme/server"),
            session,  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
        )

    assert caught.value.status_code == 429
    assert caught.value.headers == {"Retry-After": "42"}
    assert session.commits == 1


@pytest.mark.asyncio
async def test_github_json_reader_stops_at_response_size_limit(monkeypatch) -> None:
    monkeypatch.setattr(source_metadata, "GITHUB_MAX_RESPONSE_BYTES", 8)

    class OversizedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"12345"
            yield b"67890"
            raise AssertionError("reader must stop once the size limit is exceeded")

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, stream=OversizedStream())
    )
    async with httpx.AsyncClient(transport=transport) as client:
        payload = await source_metadata._fetch_github_json(client, "/repos/acme/server")

    assert payload is None


def test_repository_content_requires_expected_schema() -> None:
    malformed = json.dumps(
        {
            "name": "acme/server",
            "description": "Valid description",
            "packages": "not-a-list",
        }
    )

    assert source_metadata._normalize_server_json(
        malformed,
        "",
        "1.0.0",
        "acme",
        "server",
        "main",
        "https://github.com/acme/server",
    ) is None

    nested: dict[str, object] = {}
    cursor = nested
    for _ in range(25):
        child: dict[str, object] = {}
        cursor["child"] = child
        cursor = child
    overly_complex = json.dumps(
        {
            "name": "acme/server",
            "description": "Valid description",
            "packages": [nested],
        }
    )
    assert source_metadata._normalize_server_json(
        overly_complex,
        "",
        "1.0.0",
        "acme",
        "server",
        "main",
        "https://github.com/acme/server",
    ) is None


@pytest.mark.asyncio
async def test_repository_import_has_a_total_outbound_timeout(monkeypatch) -> None:
    async def slow_fetch(*_args, **_kwargs):
        await asyncio.sleep(1)
        return None

    monkeypatch.setattr(source_metadata, "GITHUB_IMPORT_TIMEOUT_SECONDS", 0.001)
    monkeypatch.setattr(source_metadata, "_fetch_github_json", slow_fetch)

    with pytest.raises(
        source_metadata.GitHubRepositoryNotFoundError,
        match="timed out",
    ):
        await source_metadata.import_repository_metadata("https://github.com/acme/server")


@pytest.mark.asyncio
async def test_import_repository_metadata_normalizes_server_json(monkeypatch) -> None:
    async def fake_fetch_github_json(_client, _path):
        return {
            "default_branch": "main",
            "description": "Fallback",
            "html_url": "https://github.com/acme/mcp-example",
            "name": "mcp-example",
        }

    async def fake_fetch_repository_file(_client, _owner, _repo, path, _branch):
        if path == "server.json":
            return json.dumps(
                {
                    "name": "acme/example",
                    "title": "Example",
                    "description": "Server description",
                    "version": "$VERSION",
                    "icon": "assets/icon.png",
                    "packages": [
                        {"registryType": "npm", "identifier": "@acme/example@$VERSION"},
                        {"registryType": "mcpb", "identifier": "ignored"},
                    ],
                }
            )
        return ""

    async def fake_fetch_readme(*_args):
        return "Repository README"

    async def fake_fetch_release(*_args):
        return "1.2.3"

    monkeypatch.setattr(source_metadata, "_fetch_github_json", fake_fetch_github_json)
    monkeypatch.setattr(source_metadata, "_fetch_repository_file", fake_fetch_repository_file)
    monkeypatch.setattr(source_metadata, "_fetch_repository_readme", fake_fetch_readme)
    monkeypatch.setattr(source_metadata, "_fetch_latest_release_version", fake_fetch_release)

    result = await source_metadata.import_repository_metadata(
        "https://github.com/acme/mcp-example"
    )

    assert result.source == "server.json"
    assert result.name == "acme/example"
    assert result.description == "Repository README"
    assert result.version == "1.2.3"
    assert result.icon_url.endswith("/acme/mcp-example/main/assets/icon.png")
    assert result.packages == [
        {"registryType": "npm", "identifier": "@acme/example@1.2.3"}
    ]


@pytest.mark.asyncio
async def test_import_repository_metadata_falls_back_to_package_json(monkeypatch) -> None:
    async def fake_fetch_github_json(_client, _path):
        return {
            "default_branch": "main",
            "description": "Package fallback",
            "html_url": "https://github.com/acme/tool",
            "name": "tool",
        }

    async def fake_fetch_repository_file(_client, _owner, _repo, path, _branch):
        if path == "package.json":
            return json.dumps({"name": "@acme/tool", "version": "2.0.0"})
        return ""

    async def fake_fetch_readme(*_args):
        return ""

    async def fake_fetch_release(*_args):
        return ""

    monkeypatch.setattr(source_metadata, "_fetch_github_json", fake_fetch_github_json)
    monkeypatch.setattr(source_metadata, "_fetch_repository_file", fake_fetch_repository_file)
    monkeypatch.setattr(source_metadata, "_fetch_repository_readme", fake_fetch_readme)
    monkeypatch.setattr(source_metadata, "_fetch_latest_release_version", fake_fetch_release)

    result = await source_metadata.import_repository_metadata("github.com/acme/tool")

    assert result.source == "repository"
    assert result.title == "Tool"
    assert result.packages == [
        {"registryType": "npm", "identifier": "@acme/tool", "version": "2.0.0"}
    ]
