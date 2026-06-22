import json
import os
from dataclasses import dataclass

from adapter.constants import (
    WARDN_RUNTIME_ARGS_JSON_ENV,
    WARDN_RUNTIME_COMMAND_ENV,
    WARDN_RUNTIME_CWD_ENV,
    WARDN_RUNTIME_REQUEST_TIMEOUT_SECONDS_ENV,
    WARDN_RUNTIME_STARTUP_TIMEOUT_SECONDS_ENV,
)


@dataclass(frozen=True)
class AdapterSettings:
    command: str
    args: list[str]
    cwd: str = ""
    startup_timeout_seconds: float = 60
    request_timeout_seconds: float = 300


def parse_runtime_args(value: str) -> list[str]:
    if not value:
        return []
    parsed = json.loads(value)
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise ValueError("WARDN_RUNTIME_ARGS_JSON must be a JSON array of strings")
    return parsed


def settings_from_env() -> AdapterSettings:
    command = os.getenv(WARDN_RUNTIME_COMMAND_ENV, "").strip()
    if not command:
        raise ValueError(f"{WARDN_RUNTIME_COMMAND_ENV} is required")
    return AdapterSettings(
        command=command,
        args=parse_runtime_args(os.getenv(WARDN_RUNTIME_ARGS_JSON_ENV, "")),
        cwd=os.getenv(WARDN_RUNTIME_CWD_ENV, ""),
        startup_timeout_seconds=float(os.getenv(WARDN_RUNTIME_STARTUP_TIMEOUT_SECONDS_ENV, "60")),
        request_timeout_seconds=float(os.getenv(WARDN_RUNTIME_REQUEST_TIMEOUT_SECONDS_ENV, "300")),
    )
