from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from app.core.schemas import APIModel


class RuntimeLogEntry(APIModel):
    id: str
    timestamp: datetime
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    message: str
    fields: dict[str, Any]


class StoredLogEntry(BaseModel):
    timestamp: datetime
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    message: str
    fields: dict[str, Any]


class RuntimeLogPage(APIModel):
    job_id: UUID | None
    job_status: str | None
    items: list[RuntimeLogEntry]
    next_cursor: str | None
    has_more: bool
    truncated: bool
    unreadable_entries: int
    retention_seconds: int
    max_entries: int
