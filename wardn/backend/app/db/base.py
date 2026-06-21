from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def import_models() -> None:
    from app.modules.mcp_registry import models as _mcp_registry_models  # noqa: F401
    from app.modules.mcp_runtime import models as _mcp_runtime_models  # noqa: F401
    from app.modules.users import models as _users_models  # noqa: F401
