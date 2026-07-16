from typing import Any

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    type: str
    title: str
    status: int
    detail: str
    instance: str
    code: str
    request_id: str = Field(alias="requestId")
    errors: list[dict[str, Any]] | None = None
