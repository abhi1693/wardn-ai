from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def import_models() -> None:
    from app.modules.agents import models as _agents_models  # noqa: F401
    from app.modules.guardrails import models as _guardrails_models  # noqa: F401
    from app.modules.llm_providers import models as _llm_provider_models  # noqa: F401
    from app.modules.mcp_registry import models as _mcp_registry_models  # noqa: F401
    from app.modules.mcp_runtime import models as _mcp_runtime_models  # noqa: F401
    from app.modules.organizations import models as _organization_models  # noqa: F401
    from app.modules.secrets import models as _secrets_models  # noqa: F401
    from app.modules.users import models as _users_models  # noqa: F401
