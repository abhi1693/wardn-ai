from app.modules.mcp_registry import python_runtime


def test_python_runtime_requirement_infers_higher_python_version(monkeypatch) -> None:
    monkeypatch.setattr(python_runtime, "current_python_version_tuple", lambda: (3, 12))

    requirement = python_runtime.resolve_python_runtime_requirement(
        {"requiresPython": ">=3.13"},
        identifier="unifi-access-mcp",
        version="0.5.2",
    )

    assert requirement.requires_python == ">=3.13"
    assert requirement.python_version == "3.13"


def test_python_runtime_requirement_ignores_currently_supported_python(monkeypatch) -> None:
    monkeypatch.setattr(python_runtime, "current_python_version_tuple", lambda: (3, 12))

    requirement = python_runtime.resolve_python_runtime_requirement(
        {"requiresPython": ">=3.10"},
        identifier="example-mcp",
        version="1.0.0",
    )

    assert requirement.requires_python == ">=3.10"
    assert requirement.python_version == ""
