from collections.abc import Iterable
from typing import Any

from sqlalchemy.exc import IntegrityError


def integrity_constraint_name(exc: IntegrityError) -> str | None:
    """Return the database constraint reported by a wrapped driver error."""
    pending: list[Any] = [exc]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        if current is None or id(current) in visited:
            continue
        visited.add(id(current))

        constraint_name = getattr(current, "constraint_name", None)
        if isinstance(constraint_name, str) and constraint_name:
            return constraint_name
        diagnostic = getattr(current, "diag", None)
        constraint_name = getattr(diagnostic, "constraint_name", None)
        if isinstance(constraint_name, str) and constraint_name:
            return constraint_name

        pending.extend(
            (
                getattr(current, "orig", None),
                getattr(current, "__cause__", None),
                getattr(current, "__context__", None),
            )
        )
    return None


def is_constraint_violation(exc: IntegrityError, constraint_names: Iterable[str]) -> bool:
    """Match only a known constraint, preserving unrelated integrity failures."""
    expected = frozenset(constraint_names)
    actual = integrity_constraint_name(exc)
    if actual is not None:
        return actual in expected
    error_text = str(exc)
    return any(name in error_text for name in expected)
