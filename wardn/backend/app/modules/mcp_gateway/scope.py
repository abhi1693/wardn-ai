import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class GatewayScope:
    user_id: uuid.UUID
    is_superuser: bool
    organization_id: uuid.UUID | None = None
    workspace_id: uuid.UUID | None = None

