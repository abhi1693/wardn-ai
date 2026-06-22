import os

SENSITIVE_NAME_PARTS = ("TOKEN", "SECRET", "PASSWORD", "AUTH", "KEY", "CREDENTIAL")
REDACTION = "[REDACTED]"


def sensitive_environment_values(environ: dict[str, str] | None = None) -> list[str]:
    values: list[str] = []
    for key, value in (environ or os.environ).items():
        if value and any(part in key.upper() for part in SENSITIVE_NAME_PARTS):
            values.append(value)
    return values


def redact_text(value: str, *, secrets: list[str] | None = None) -> str:
    redacted = value
    for secret in secrets or sensitive_environment_values():
        redacted = redacted.replace(secret, REDACTION)
    return redacted
