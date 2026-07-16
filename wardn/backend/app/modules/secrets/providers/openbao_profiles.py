import json
import re
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import ConfigDict, Field, ValidationError, field_validator, model_validator

from app.core.schemas import APIModel
from app.modules.secrets.exceptions import InvalidSecretStoreError

PROFILE_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
MOUNT_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_/-]{0,127}")
STANDARD_AUTH_MOUNTS = {
    "approle": "approle",
    "kubernetes": "kubernetes",
}


class OpenBaoAuthProfile(APIModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(min_length=1, max_length=2048)
    method: Literal["approle", "kubernetes"]
    auth_mount: str = Field(default="", max_length=128)
    namespace: str = Field(default="", max_length=255)
    tls_verify: bool = True
    role: str = Field(default="", max_length=255)
    token_file: str = Field(default="", max_length=1024)
    role_id_file: str = Field(default="", max_length=1024)
    secret_id_file: str = Field(default="", max_length=1024)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("baseUrl must be an HTTP(S) URL with a hostname")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("baseUrl must not include credentials, a query, or a fragment")
        return normalized

    @field_validator("auth_mount")
    @classmethod
    def validate_auth_mount(cls, value: str) -> str:
        normalized = value.strip().strip("/")
        if normalized and not MOUNT_PATTERN.fullmatch(normalized):
            raise ValueError("authMount contains unsupported characters")
        return normalized

    @field_validator("namespace", "role")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("token_file", "role_id_file", "secret_id_file")
    @classmethod
    def validate_relative_file(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            return ""
        path = Path(normalized)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("credential files must be relative paths without traversal")
        return normalized

    @model_validator(mode="after")
    def validate_method_settings(self) -> "OpenBaoAuthProfile":
        if self.tls_verify and urlsplit(self.base_url).scheme == "http":
            raise ValueError("tlsVerify requires an HTTPS baseUrl")
        if not self.auth_mount:
            self.auth_mount = STANDARD_AUTH_MOUNTS[self.method]
        if self.method == "kubernetes":
            if not self.role or not self.token_file:
                raise ValueError("Kubernetes profiles require role and tokenFile")
            if self.role_id_file or self.secret_id_file:
                raise ValueError("Kubernetes profiles must not include AppRole credential files")
        elif not self.role_id_file or not self.secret_id_file:
            raise ValueError("AppRole profiles require roleIdFile and secretIdFile")
        elif self.role or self.token_file:
            raise ValueError("AppRole profiles must not include Kubernetes credentials")
        return self


@lru_cache(maxsize=8)
def parse_openbao_auth_profiles(raw_profiles: str) -> Mapping[str, OpenBaoAuthProfile]:
    try:
        payload = json.loads(raw_profiles)
    except json.JSONDecodeError as exc:
        raise InvalidSecretStoreError("operator OpenBao auth profiles are not valid JSON") from exc
    if not isinstance(payload, dict):
        raise InvalidSecretStoreError("operator OpenBao auth profiles must be a JSON object")

    profiles: dict[str, OpenBaoAuthProfile] = {}
    try:
        for raw_name, raw_profile in payload.items():
            if not isinstance(raw_name, str) or not PROFILE_NAME_PATTERN.fullmatch(raw_name):
                raise InvalidSecretStoreError("operator OpenBao auth profile name is invalid")
            profiles[raw_name] = OpenBaoAuthProfile.model_validate(raw_profile)
    except ValidationError as exc:
        raise InvalidSecretStoreError("operator OpenBao auth profile is invalid") from exc
    return profiles


def read_profile_file(root: str, relative_path: str, label: str) -> str:
    try:
        resolved_root = Path(root).resolve(strict=True)
        resolved_path = (resolved_root / relative_path).resolve(strict=True)
    except OSError as exc:
        raise InvalidSecretStoreError(f"{label} file could not be resolved") from exc
    if resolved_root == Path(resolved_root.anchor):
        raise InvalidSecretStoreError("operator credential root must not be a filesystem root")
    if resolved_path == resolved_root or not resolved_path.is_relative_to(resolved_root):
        raise InvalidSecretStoreError(f"{label} file must be inside the operator credential root")
    if not resolved_path.is_file():
        raise InvalidSecretStoreError(f"{label} file is not a regular file")
    try:
        value = resolved_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise InvalidSecretStoreError(f"{label} file could not be read") from exc
    if not value:
        raise InvalidSecretStoreError(f"{label} file was empty")
    return value
