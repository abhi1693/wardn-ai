from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.core.schemas import APIModel


class LicenseLeaseImport(APIModel):
    signed_lease: str = Field(min_length=1, max_length=131_072)
    renewal_token: str | None = Field(default=None, min_length=32, max_length=4096)


class LicenseStatus(APIModel):
    instance_id: UUID
    state: Literal["community", "licensed", "grace"]
    edition: str
    license_id: str | None = None
    expires_at: datetime | None = None
    grace_until: datetime | None = None
    features: dict[str, bool]
    limits: dict[str, int]
    automatic_renewal_configured: bool


class LicenseRenewalRequest(APIModel):
    instance_id: UUID
    current_lease_sequence: int | None = None
    renewal_token: str | None = None
    instance_name: str = ""
    server_url: str = ""
    app_version: str = ""


class LicenseRenewalResponse(APIModel):
    signed_lease: str = Field(min_length=1, max_length=131_072)
    renewal_token: str = Field(min_length=32, max_length=4096)
