"""Repeatable seed command for one administrator and sample users."""

from __future__ import annotations

import argparse
import getpass
import os
from dataclasses import dataclass
from uuid import uuid4

from common.config import ConfigurationError, load_settings
from common.logging import configure_logging
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed Phase 2 users")
    parser.add_argument("--admin-username", default="admin")
    parser.add_argument(
        "--sample-user",
        action="append",
        dest="sample_users",
        help="sample username; repeat for more users (defaults: alice and bob)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        raise SystemExit(f"configuration error: {exc}") from exc

    admin_password = os.environ.get("SEED_ADMIN_PASSWORD") or getpass.getpass(
        "Seed administrator password: "
    )
    sample_password = os.environ.get("SEED_SAMPLE_PASSWORD") or getpass.getpass(
        "Seed sample-user password: "
    )
    try:
        result = seed_users(
            Database(settings.chat_database_path),
            admin_username=args.admin_username,
            admin_password=admin_password,
            sample_usernames=args.sample_users or ["alice", "bob"],
            sample_password=sample_password,
        )
    except ValueError as exc:
        raise SystemExit(f"seed input error: {exc}") from exc
    logger = configure_logging(
        service="database-seed",
        node_id=settings.chat_node_id,
        level=settings.log_level,
    )
    logger.info(
        "seed_complete",
        extra={"created_users": result.created, "existing_users": result.existing},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
