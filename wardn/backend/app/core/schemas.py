from typing import Any

from pydantic import BaseModel, ConfigDict


def to_camel_case(field_name: str) -> str:
    """Convert a snake-case Python field name to Wardn's camel-case API spelling."""

    first, *rest = field_name.split("_")
    return first + "".join(part[:1].upper() + part[1:] for part in rest)


class APIModel(BaseModel):
    """Base model for the public API's camel-case JSON contract."""

    model_config = ConfigDict(
        alias_generator=to_camel_case,
        validate_by_alias=True,
        validate_by_name=True,
        serialize_by_alias=True,
    )


class ErrorResponse(APIModel):
    type: str
    title: str
    status: int
    detail: str
    instance: str
    code: str
    request_id: str
    errors: list[dict[str, Any]] | None = None
