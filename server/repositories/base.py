"""Persistence ports that keep business logic independent of SQLite."""

from __future__ import annotations

from typing import Protocol, Sequence, TypeVar


EntityT = TypeVar("EntityT")


class Repository(Protocol[EntityT]):
    """Minimal entity storage contract to be specialized in later phases."""

    def add(self, entity: EntityT) -> None: ...

    def get(self, entity_id: str) -> EntityT | None: ...

    def list(self) -> Sequence[EntityT]: ...


class UnitOfWork(Protocol):
    """Transaction boundary for atomic application operations."""

    def __enter__(self) -> UnitOfWork: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

