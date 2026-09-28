"""Legacy test seeding helper; interactive account creation uses Register."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from common.metadata import utc_now
from domain.models import User, UserRole, UserStatus
from server.database import Database, apply_migrations
from server.application.admin import USERNAME_PATTERN
from server.repositories.sqlite import SQLiteUnitOfWorkFactory
from server.security.passwords import hash_password


@dataclass(frozen=True, slots=True)
class SeedResult:
    created: tuple[str, ...]
    existing: tuple[str, ...]


def seed_users(
    database: Database,
    *,
    admin_username: str,
    admin_password: str,
    sample_usernames: list[str],
    sample_password: str,
) -> SeedResult:
    apply_migrations(database)
    factory = SQLiteUnitOfWorkFactory(database)
    created: list[str] = []
    existing: list[str] = []
    specifications = [
        (admin_username, admin_password, UserRole.ADMIN),
        *((username, sample_password, UserRole.USER) for username in sample_usernames),
    ]
    with factory() as unit_of_work:
        for username, password, role in specifications:
            normalized = username.strip()
            if not USERNAME_PATTERN.fullmatch(normalized):
                raise ValueError(
                    f"invalid seed username {normalized!r}; use 3-64 safe characters"
                )
            if unit_of_work.users.get_by_username(normalized) is not None:
                existing.append(normalized)
                continue
            user = User(
                id=str(uuid4()),
                username=normalized,
                role=role,
                status=UserStatus.ACTIVE,
                created_at=utc_now(),
            )
            unit_of_work.users.add(user, hash_password(password))
            created.append(normalized)
        unit_of_work.commit()
    return SeedResult(tuple(created), tuple(existing))


def main(argv: list[str] | None = None) -> int:
    print("Seeding is retired. Start the app and use Register to create user accounts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
