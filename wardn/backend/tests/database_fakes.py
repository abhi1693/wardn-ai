from typing import Any


class EmptyResult:
    """Minimal SQLAlchemy result double for tests that expect no persisted rows."""

    def scalar_one(self) -> int:
        return 0

    def scalar_one_or_none(self) -> None:
        return None

    def scalars(self) -> "EmptyResult":
        return self

    def all(self) -> list[Any]:
        return []

    def __iter__(self):
        return iter(())
