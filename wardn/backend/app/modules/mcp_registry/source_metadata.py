import asyncio
import base64
import binascii
import json
import re
import tomllib
from typing import Any, Literal
from urllib.parse import quote, urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.config import get_settings
from app.modules.mcp_registry.schemas import MCPRepositoryMetadataImportResponse

GITHUB_API_ROOT = "https://api.github.com"
GITHUB_REQUEST_TIMEOUT_SECONDS = 10.0
GITHUB_IMPORT_TIMEOUT_SECONDS = 25.0
GITHUB_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
GITHUB_MAX_FILE_BYTES = 1024 * 1024
_IMPORT_CONCURRENCY = asyncio.Semaphore(4)
_GITHUB_OWNER_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_GITHUB_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


def _validate_bounded_json(value: Any) -> Any:
    nodes = 0

    def visit(item: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > 5_000 or depth > 20:
            raise ValueError("repository metadata is too complex")
        if isinstance(item, dict):
            if len(item) > 100:
                raise ValueError("repository metadata object has too many fields")
            for key, child in item.items():
                if not isinstance(key, str) or len(key) > 256:
                    raise ValueError("repository metadata contains an invalid field name")
                visit(child, depth + 1)
        elif isinstance(item, list):
            if len(item) > 100:
                raise ValueError("repository metadata array has too many items")
            for child in item:
                visit(child, depth + 1)
        elif isinstance(item, str):
            if len(item) > 65_536:
                raise ValueError("repository metadata string is too long")
        elif item is not None and not isinstance(item, (bool, int, float)):
            raise ValueError("repository metadata contains an unsupported value")

    visit(value, 0)
    return value


class _GitHubRepositoryPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    default_branch: str = Field(default="main", min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=65_536)
    homepage: str | None = Field(default=None, max_length=2048)
    html_url: str | None = Field(default=None, max_length=2048)
    name: str = Field(min_length=1, max_length=100)


class _GitHubContentPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["file"]
    encoding: Literal["base64"]
    content: str = Field(max_length=(GITHUB_MAX_FILE_BYTES * 4 // 3) + 4096)


class _GitHubReleasePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tag_name: str = Field(default="", max_length=255)


class _RepositoryDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: str = Field(default="github", max_length=64)
    url: str = Field(default="", max_length=2048)
    subfolder: str = Field(default="", max_length=4096)


class _IconDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")

    src: str = Field(max_length=2048)


class _ServerJSONDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=131_072)
    title: str = Field(default="", max_length=100)
    version: str = Field(default="", max_length=255)
    website_url: str = Field(default="", alias="websiteUrl", max_length=2048)
    repository: _RepositoryDocument | None = None
    icon: str = Field(default="", max_length=2048)
    icons: list[_IconDocument] = Field(default_factory=list, max_length=32)
    packages: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    remotes: list[dict[str, Any]] = Field(default_factory=list, max_length=100)

    @field_validator("packages", "remotes")
    @classmethod
    def validate_nested_content(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _validate_bounded_json(value)


class _MCPServerConfigDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")

    command: str = Field(max_length=4096)
    args: list[str] = Field(default_factory=list, max_length=100)
    env: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict,
        max_length=100,
    )


class _MCPJSONDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mcp_servers: dict[str, _MCPServerConfigDocument] = Field(
        alias="mcpServers",
        min_length=1,
        max_length=100,
    )


class _PackageJSONDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=214)
    version: str = Field(default="", max_length=255)


class _PythonProjectDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = Field(default=None, max_length=214)


class _PythonToolDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")

    poetry: _PythonProjectDocument | None = None


class _PyprojectDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project: _PythonProjectDocument | None = None
    tool: _PythonToolDocument | None = None


class InvalidGitHubRepositoryURLError(ValueError):
    pass


class GitHubRepositoryNotFoundError(ValueError):
    pass


def parse_github_repository_url(value: str) -> tuple[str, str]:
    candidate = value.strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    hostname = (parsed.hostname or "").casefold().removeprefix("www.")
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.scheme not in {"http", "https"} or hostname != "github.com" or len(parts) < 2:
        raise InvalidGitHubRepositoryURLError("Enter a GitHub repository URL.")
    owner = parts[0]
    repo = re.sub(r"\.git$", "", parts[1], flags=re.IGNORECASE)
    if not _GITHUB_OWNER_PATTERN.fullmatch(owner) or not _GITHUB_REPOSITORY_PATTERN.fullmatch(repo):
        raise InvalidGitHubRepositoryURLError("Enter a GitHub repository URL.")
    return owner, repo


def title_from_repository_name(value: str) -> str:
    title = re.sub(r"[-_]+", " ", value)
    title = re.sub(r"\bmcp\b", "MCP", title, flags=re.IGNORECASE)
    return re.sub(r"\b\w", lambda match: match.group(0).upper(), title)[:100]


def _github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "wardn-ai",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = get_settings().github_token.get_secret_value().strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _fetch_github_json(client: httpx.AsyncClient, path: str) -> dict[str, Any] | None:
    try:
        async with client.stream(
            "GET",
            f"{GITHUB_API_ROOT}{path}",
            headers=_github_headers(),
        ) as response:
            if not response.is_success:
                return None
            content_length = response.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > GITHUB_MAX_RESPONSE_BYTES:
                        return None
                except ValueError:
                    return None
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > GITHUB_MAX_RESPONSE_BYTES:
                    return None
                chunks.append(chunk)
    except (httpx.HTTPError, TimeoutError):
        return None
    try:
        payload = json.loads(b"".join(chunks))
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
        return None
    return payload if isinstance(payload, dict) else None


def _decode_content(payload: dict[str, Any] | None) -> str:
    try:
        document = _GitHubContentPayload.model_validate(payload)
    except ValidationError:
        return ""
    try:
        encoded = "".join(document.content.split())
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return ""
    if len(decoded) > GITHUB_MAX_FILE_BYTES:
        return ""
    return decoded.decode("utf-8", errors="replace")


async def _fetch_repository_file(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    path: str,
    branch: str,
) -> str:
    payload = await _fetch_github_json(
        client,
        f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/contents/{path}"
        f"?ref={quote(branch, safe='')}",
    )
    return _decode_content(payload)


async def _fetch_repository_readme(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    branch: str,
) -> str:
    payload = await _fetch_github_json(
        client,
        f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/readme"
        f"?ref={quote(branch, safe='')}",
    )
    return _decode_content(payload)


async def _fetch_latest_release_version(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
) -> str:
    payload = await _fetch_github_json(
        client,
        f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/releases/latest",
    )
    try:
        release = _GitHubReleasePayload.model_validate(payload)
    except ValidationError:
        return ""
    tag_name = release.tag_name.strip()
    return re.sub(r"^v(?=\d)", "", tag_name, flags=re.IGNORECASE)


def _replace_version_tokens(value: Any, version: str) -> Any:
    replacement = version or "latest"
    if isinstance(value, str):
        return value.replace("$VERSION", replacement)
    if isinstance(value, list):
        return [_replace_version_tokens(item, replacement) for item in value]
    if isinstance(value, dict):
        return {key: _replace_version_tokens(item, replacement) for key, item in value.items()}
    return value


def _supported_packages(value: Any, version: str) -> list[dict[str, Any]]:
    packages = _replace_version_tokens(value, version)
    if not isinstance(packages, list):
        return []
    return [
        package
        for package in packages
        if isinstance(package, dict)
        and str(package.get("registryType") or "").casefold() != "mcpb"
    ]


def _normalized_version(value: Any, release_version: str) -> str:
    version = value.strip() if isinstance(value, str) else ""
    if not version or version == "0.0.0":
        return release_version or "latest"
    return str(_replace_version_tokens(version, release_version))


def _raw_github_url(owner: str, repo: str, branch: str, path: str) -> str:
    encoded_path = "/".join(quote(part, safe="") for part in path.split("/"))
    return (
        f"https://raw.githubusercontent.com/{quote(owner, safe='')}/{quote(repo, safe='')}/"
        f"{quote(branch, safe='')}/{encoded_path}"
    )


def _normalize_icon_url(
    document: dict[str, Any], owner: str, repo: str, branch: str
) -> str:
    icon = document.get("icon")
    icon_path = icon.strip() if isinstance(icon, str) else ""
    icons = document.get("icons")
    if not icon_path and isinstance(icons, list):
        for candidate in icons:
            src = candidate.get("src") if isinstance(candidate, dict) else None
            if isinstance(src, str) and src.strip():
                icon_path = src.strip()
                break
    if not icon_path:
        return ""
    if icon_path.casefold().startswith(("http://", "https://")):
        return icon_path
    return _raw_github_url(owner, repo, branch, icon_path.lstrip("/"))


def _json_object(raw_value: str) -> dict[str, Any] | None:
    if not raw_value:
        return None
    try:
        parsed = json.loads(raw_value)
    except (json.JSONDecodeError, RecursionError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_server_json(
    raw_server_json: str,
    readme: str,
    release_version: str,
    owner: str,
    repo: str,
    branch: str,
    canonical_repository_url: str,
) -> dict[str, Any] | None:
    document_payload = _json_object(raw_server_json)
    try:
        validated = _ServerJSONDocument.model_validate(document_payload)
    except ValidationError:
        return None
    document = validated.model_dump(by_alias=True)
    version = _normalized_version(document.get("version"), release_version)
    repository = document.get("repository")
    repository = repository if isinstance(repository, dict) else {}
    remotes = document.get("remotes")
    return {
        "source": "server.json",
        "name": str(document["name"]),
        "title": str(document.get("title") or title_from_repository_name(repo)),
        "description": readme or str(document["description"]),
        "version": version,
        "website_url": str(document.get("websiteUrl") or canonical_repository_url),
        "repository": {
            "source": repository.get("source") or "github",
            "url": repository.get("url") or canonical_repository_url,
            "subfolder": repository.get("subfolder") or "",
        },
        "icon_url": _normalize_icon_url(document, owner, repo, branch),
        "remotes": _replace_version_tokens(remotes, version) if isinstance(remotes, list) else [],
        "packages": _supported_packages(document.get("packages"), version),
    }


def _string_array(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _command_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.split(r"[\\/]", value.strip())[-1].casefold()


def _environment_variables(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    variables = []
    for name, raw_value in value.items():
        default_value = raw_value if isinstance(raw_value, str) else ""
        variables.append(
            {
                "name": str(name),
                "description": "",
                "default": default_value,
                "isRequired": not default_value.strip(),
                "isSecret": bool(
                    re.search(
                        r"secret|token|password|credential|credentials|key|private",
                        str(name),
                        flags=re.IGNORECASE,
                    )
                ),
                "format": "string",
            }
        )
    return variables


def _package_target_from_mcp_server(
    server_config: dict[str, Any], release_version: str
) -> dict[str, Any] | None:
    command = _command_name(server_config.get("command"))
    args = _string_array(server_config.get("args"))
    if command == "uvx":
        registry_type = "uvx"
        identifier_index = next(
            (index for index, arg in enumerate(args) if arg and not arg.startswith("-")), -1
        )
        excluded = {identifier_index}
    elif command == "npx":
        registry_type = "npm"
        identifier_index = next(
            (
                index
                for index, arg in enumerate(args)
                if arg and arg != "-y" and not arg.startswith("-")
            ),
            -1,
        )
        excluded = {identifier_index, *(index for index, arg in enumerate(args) if arg == "-y")}
    else:
        return None
    if identifier_index < 0:
        return None
    return {
        "registryType": registry_type,
        "identifier": args[identifier_index],
        "version": release_version or "latest",
        "transport": {"type": "stdio"},
        "environmentVariables": _environment_variables(server_config.get("env")),
        "packageArguments": [
            {"value": arg} for index, arg in enumerate(args) if index not in excluded
        ],
    }


def _normalize_mcp_json(
    raw_mcp_json: str,
    readme: str,
    description_fallback: str,
    release_version: str,
    repo: str,
    canonical_repository_url: str,
) -> dict[str, Any] | None:
    document_payload = _json_object(raw_mcp_json)
    try:
        document = _MCPJSONDocument.model_validate(document_payload)
    except ValidationError:
        return None
    servers = document.mcp_servers
    server_entry = next(
        ((key, value.model_dump()) for key, value in servers.items()),
        None,
    )
    if not server_entry:
        return None
    server_key, server_config = server_entry
    package_target = _package_target_from_mcp_server(server_config, release_version)
    if not package_target:
        return None
    title = title_from_repository_name(str(server_key or repo))
    return {
        "source": "mcp.json",
        "title": title,
        "description": readme or description_fallback or title,
        "version": release_version or "latest",
        "website_url": canonical_repository_url,
        "repository": {"source": "github", "url": canonical_repository_url, "subfolder": ""},
        "remotes": [],
        "packages": [package_target],
    }


def _package_from_package_json(
    raw_package_json: str, release_version: str
) -> dict[str, Any] | None:
    package_payload = _json_object(raw_package_json)
    try:
        package = _PackageJSONDocument.model_validate(package_payload)
    except ValidationError:
        return None
    package_version = package.version.strip()
    return {
        "registryType": "npm",
        "identifier": package.name.strip(),
        "version": release_version
        or (package_version if package_version and package_version != "0.0.0" else "latest"),
    }


def _package_from_pyproject(
    raw_pyproject: str, release_version: str
) -> dict[str, Any] | None:
    if not raw_pyproject:
        return None
    try:
        parsed = tomllib.loads(raw_pyproject)
        document = _PyprojectDocument.model_validate(parsed)
    except (tomllib.TOMLDecodeError, ValidationError):
        return None
    name = document.project.name if document.project else None
    if not name and document.tool and document.tool.poetry:
        name = document.tool.poetry.name
    if not name or not name.strip():
        return None
    return {"registryType": "uvx", "identifier": name.strip(), "version": release_version}


async def import_repository_metadata(
    repository_url: str,
) -> MCPRepositoryMetadataImportResponse:
    owner, repo = parse_github_repository_url(repository_url)
    timeout = httpx.Timeout(
        connect=5.0,
        read=GITHUB_REQUEST_TIMEOUT_SECONDS,
        write=5.0,
        pool=5.0,
    )
    try:
        async with asyncio.timeout(GITHUB_IMPORT_TIMEOUT_SECONDS):
            async with (
                _IMPORT_CONCURRENCY,
                httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client,
            ):
                repository_payload = await _fetch_github_json(
                    client,
                    f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}",
                )
                try:
                    repository_document = _GitHubRepositoryPayload.model_validate(
                        repository_payload
                    )
                except ValidationError as exc:
                    raise GitHubRepositoryNotFoundError(
                        "Repository metadata could not be loaded."
                    ) from exc
                repository = repository_document.model_dump()
                branch = repository_document.default_branch
                server_json, mcp_json, readme, package_json, pyproject, release_version = (
                    await asyncio.gather(
                        _fetch_repository_file(client, owner, repo, "server.json", branch),
                        _fetch_repository_file(client, owner, repo, "mcp.json", branch),
                        _fetch_repository_readme(client, owner, repo, branch),
                        _fetch_repository_file(client, owner, repo, "package.json", branch),
                        _fetch_repository_file(client, owner, repo, "pyproject.toml", branch),
                        _fetch_latest_release_version(client, owner, repo),
                    )
                )
    except TimeoutError as exc:
        raise GitHubRepositoryNotFoundError(
            "Repository metadata request timed out."
        ) from exc
    canonical_url = str(repository.get("html_url") or f"https://github.com/{owner}/{repo}")
    normalized = _normalize_server_json(
        server_json,
        readme,
        release_version,
        owner,
        repo,
        branch,
        canonical_url,
    ) or _normalize_mcp_json(
        mcp_json,
        readme,
        str(repository.get("description") or ""),
        release_version,
        repo,
        canonical_url,
    )
    if normalized is None:
        packages = [
            package
            for package in (
                _package_from_package_json(package_json, release_version),
                _package_from_pyproject(pyproject, release_version),
            )
            if package is not None
        ]
        repository_name = str(repository.get("name") or repo)
        normalized = {
            "source": "repository",
            "title": title_from_repository_name(repository_name),
            "description": readme or str(repository.get("description") or ""),
            "version": release_version or "latest",
            "website_url": str(repository.get("homepage") or canonical_url),
            "repository": {"source": "github", "url": canonical_url, "subfolder": ""},
            "packages": packages,
        }
    return MCPRepositoryMetadataImportResponse.model_validate(normalized)
