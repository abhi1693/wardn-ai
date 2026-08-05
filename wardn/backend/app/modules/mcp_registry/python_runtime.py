import json
import re
import sys
from dataclasses import dataclass
from typing import Any
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import urlopen

PYTHON_VERSION_FIELDS = ("pythonVersion", "python_version")
PYTHON_REQUIRES_FIELDS = (
    "requiresPython",
    "requires_python",
    "pythonRequires",
    "python_requires",
)
PYTHON_RUNTIME_DEPENDENCY_FIELDS = ("runtimeDependencies", "pythonDependencies")
PYTHON_RUNTIME_COMPATIBILITY_DEPENDENCIES = {
    # mcp-google-search-console 2.0.2 imports mcp.server.fastmcp but only declares mcp>=1.0.0.
    ("mcp-google-search-console", "2.0.2"): ("mcp<2",),
}


@dataclass(frozen=True)
class PythonRuntimeRequirement:
    requires_python: str = ""
    python_version: str = ""


def normalized_python_version(value: Any) -> str:
    raw_value = str(value or "").strip()
    if not raw_value:
        return ""
    match = re.match(r"^(?P<major>\d+)(?:\.(?P<minor>\d+))?", raw_value)
    if not match:
        return ""
    major = match.group("major")
    minor = match.group("minor")
    return f"{major}.{minor}" if minor is not None else major


def normalized_python_package_name(value: Any) -> str:
    return re.sub(r"[-_.]+", "-", str(value or "").strip()).casefold()


def python_version_tuple(value: str) -> tuple[int, int]:
    normalized = normalized_python_version(value)
    if not normalized:
        return (0, 0)
    parts = normalized.split(".", 1)
    major = int(parts[0])
    minor = int(parts[1]) if len(parts) > 1 else 0
    return major, minor


def current_python_version_tuple() -> tuple[int, int]:
    return sys.version_info.major, sys.version_info.minor


def python_version_exceeds_current(value: str) -> bool:
    return python_version_tuple(value) > current_python_version_tuple()


def package_declared_python_version(package: dict[str, Any]) -> str:
    for field_name in PYTHON_VERSION_FIELDS:
        version = normalized_python_version(package.get(field_name))
        if version:
            return version
    return ""


def package_declared_requires_python(package: dict[str, Any]) -> str:
    for field_name in PYTHON_REQUIRES_FIELDS:
        value = str(package.get(field_name) or "").strip()
        if value:
            return value
    return ""


def python_version_from_requires_python(requires_python: str) -> str:
    lower_bound: tuple[int, int] | None = None
    for raw_constraint in str(requires_python or "").split(","):
        constraint = raw_constraint.strip()
        match = re.match(
            r"^(?P<operator>>=|>|==|~=)\s*(?P<major>\d+)"
            r"(?:\.(?P<minor>\d+))?",
            constraint,
        )
        if not match:
            continue
        major = int(match.group("major"))
        minor = int(match.group("minor") or "0")
        operator = match.group("operator")
        if operator == ">":
            minor += 1
        candidate = (major, minor)
        if lower_bound is None or candidate > lower_bound:
            lower_bound = candidate
    if lower_bound is None:
        return ""
    return f"{lower_bound[0]}.{lower_bound[1]}"


def pypi_json_url(identifier: str, version: str) -> str:
    package = quote(identifier.strip(), safe="")
    if version and version != "latest":
        return f"https://pypi.org/pypi/{package}/{quote(version, safe='')}/json"
    return f"https://pypi.org/pypi/{package}/json"


def read_pypi_requires_python(identifier: str, version: str) -> str:
    try:
        with urlopen(pypi_json_url(identifier, version), timeout=10) as response:
            payload = json.load(response)
    except (OSError, URLError, ValueError):
        return ""
    info = payload.get("info") if isinstance(payload, dict) else None
    if isinstance(info, dict):
        requires_python = str(info.get("requires_python") or "").strip()
        if requires_python:
            return requires_python
    urls = payload.get("urls") if isinstance(payload, dict) else None
    if isinstance(urls, list):
        for item in urls:
            if not isinstance(item, dict):
                continue
            requires_python = str(item.get("requires_python") or "").strip()
            if requires_python:
                return requires_python
    return ""


def resolve_python_runtime_requirement(
    package: dict[str, Any],
    *,
    identifier: str,
    version: str,
    fetch_pypi_metadata: bool = False,
) -> PythonRuntimeRequirement:
    python_version = package_declared_python_version(package)
    requires_python = package_declared_requires_python(package)
    if not requires_python and fetch_pypi_metadata and identifier:
        requires_python = read_pypi_requires_python(identifier, version)
    if not python_version:
        inferred_version = python_version_from_requires_python(requires_python)
        if python_version_exceeds_current(inferred_version):
            python_version = inferred_version
    return PythonRuntimeRequirement(
        requires_python=requires_python,
        python_version=python_version,
    )


def apply_python_runtime_requirement(
    package: dict[str, Any],
    requirement: PythonRuntimeRequirement,
) -> dict[str, Any]:
    if not requirement.requires_python and not requirement.python_version:
        return package
    updated_package = dict(package)
    if requirement.requires_python:
        updated_package.setdefault("requiresPython", requirement.requires_python)
    if requirement.python_version:
        updated_package.setdefault("pythonVersion", requirement.python_version)
    return updated_package


def python_runtime_compatibility_dependencies(
    *,
    identifier: str,
    version: str,
) -> list[str]:
    package_name = normalized_python_package_name(identifier)
    package_version = str(version or "").strip()
    return list(
        PYTHON_RUNTIME_COMPATIBILITY_DEPENDENCIES.get(
            (package_name, package_version),
            (),
        )
    )


def python_runtime_dependency_values(
    *sources: dict[str, Any],
    identifier: str,
    version: str,
) -> list[str]:
    dependencies: list[str] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        for field_name in PYTHON_RUNTIME_DEPENDENCY_FIELDS:
            raw_dependencies = source.get(field_name)
            if not isinstance(raw_dependencies, list):
                continue
            for dependency in raw_dependencies:
                value = str(dependency or "").strip()
                if value and value not in dependencies:
                    dependencies.append(value)
    for dependency in python_runtime_compatibility_dependencies(
        identifier=identifier,
        version=version,
    ):
        if dependency not in dependencies:
            dependencies.append(dependency)
    return dependencies
