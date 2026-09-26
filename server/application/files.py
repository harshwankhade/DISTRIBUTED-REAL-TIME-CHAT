"""Authorized streaming file storage and metadata application logic."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Iterable
from pathlib import Path
from uuid import uuid4

from common.errors import ApplicationError, ErrorCode
from common.metadata import utc_now
from domain.models import FileMetadata
from server.application.auth import AuthApplication
from server.application.commands import StoreFileMetadataCommand
from server.repositories.sqlite import SQLiteUnitOfWorkFactory


CHECKSUM_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


class FileApplication:
    def __init__(self, factory: SQLiteUnitOfWorkFactory, auth: AuthApplication, *,
                 storage_path: Path, max_size_bytes: int,
                 allowed_content_types: tuple[str, ...]) -> None:
        self._factory = factory
        self._auth = auth
        self._root = storage_path.resolve()
        self._max_size = max_size_bytes
        self._allowed_types = frozenset(item.lower() for item in allowed_content_types)

    def _authorize_channel(self, unit_of_work, channel_id: str, user_id: str,
                           request_id: str, *, write: bool) -> None:
        channel = unit_of_work.channels.get(channel_id)
        if channel is None:
            raise ApplicationError(ErrorCode.NOT_FOUND, "channel not found", request_id)
        if write and channel.is_archived:
            raise ApplicationError(ErrorCode.CONFLICT, "channel is archived", request_id)
        if not unit_of_work.channels.is_member(channel_id, user_id):
            raise ApplicationError(ErrorCode.PERMISSION_DENIED, "channel membership required", request_id)

    @staticmethod
    def _same_request(existing: FileMetadata, *, channel_id: str, message_id: str | None,
                      original_name: str, content_type: str, size: int, checksum: str) -> bool:
        return (
            existing.channel_id == channel_id
            and existing.message_id == message_id
            and existing.original_name == original_name
            and existing.content_type == content_type
            and existing.size_bytes == size
            and existing.checksum_sha256 == checksum
        )

    def upload(self, token: str | None, *, channel_id: str, message_id: str | None,
               original_name: str, content_type: str, expected_size: int,
               expected_checksum: str, client_request_id: str,
               chunks: Iterable[bytes], request_id: str) -> FileMetadata:
        user = self._auth.authenticate(token, request_id=request_id)
        content_type = content_type.strip().lower()
        checksum = expected_checksum.strip().lower()
        if not client_request_id.strip():
            raise ApplicationError(ErrorCode.INVALID_ARGUMENT, "client_request_id is required", request_id)
        if not original_name or original_name in {".", ".."} or "/" in original_name or "\\" in original_name:
            raise ApplicationError(ErrorCode.INVALID_ARGUMENT, "original_name must be a safe base name", request_id)
        if content_type not in self._allowed_types:
            raise ApplicationError(ErrorCode.INVALID_ARGUMENT, "content type is not allowed", request_id)
        if expected_size < 0 or expected_size > self._max_size:
            raise ApplicationError(ErrorCode.INVALID_ARGUMENT, "file size is outside the configured limit", request_id)
        if not CHECKSUM_PATTERN.fullmatch(checksum):
            raise ApplicationError(ErrorCode.INVALID_ARGUMENT, "expected checksum must be SHA-256 hex", request_id)
        normalized_message_id = message_id.strip() or None

        with self._factory() as unit_of_work:
            self._authorize_channel(unit_of_work, channel_id, user.id, request_id, write=True)
            if normalized_message_id is not None:
                linked = unit_of_work.messages.get(normalized_message_id)
                if linked is None or linked.channel_id != channel_id:
                    raise ApplicationError(ErrorCode.INVALID_ARGUMENT, "message does not belong to channel", request_id)
            existing = unit_of_work.files.get_by_client_request(user.id, client_request_id)
            if existing is not None:
                if not self._same_request(
                    existing, channel_id=channel_id, message_id=normalized_message_id,
                    original_name=original_name, content_type=content_type,
                    size=expected_size, checksum=checksum,
                ):
                    raise ApplicationError(ErrorCode.CONFLICT, "client_request_id was reused for a different file", request_id)
                return existing

        self._root.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix="upload-", suffix=".part", dir=self._root)
        temporary_path = Path(temporary_name)
        digest = hashlib.sha256()
        actual_size = 0
        try:
            with os.fdopen(descriptor, "wb") as output:
                for chunk in chunks:
                    if not chunk:
                        continue
                    actual_size += len(chunk)
                    if actual_size > expected_size or actual_size > self._max_size:
                        raise ApplicationError(ErrorCode.INVALID_ARGUMENT, "upload exceeds declared or configured size", request_id)
                    output.write(chunk)
                    digest.update(chunk)
            if actual_size != expected_size:
                raise ApplicationError(ErrorCode.INVALID_ARGUMENT, "upload size does not match header", request_id)
            if digest.hexdigest() != checksum:
                raise ApplicationError(ErrorCode.INVALID_ARGUMENT, "upload checksum does not match header", request_id)

            file_id = str(uuid4())
            storage_reference = f"{file_id}.bin"
            command = StoreFileMetadataCommand(
                file_id, channel_id, user.id, original_name, storage_reference, content_type,
                actual_size, checksum, utc_now(), client_request_id, normalized_message_id,
            )
            final_path = self._root / command.storage_reference
            metadata = FileMetadata(
                command.file_id, command.channel_id, command.uploader_id,
                command.original_name, command.storage_reference, command.content_type,
                command.size_bytes, command.checksum_sha256, command.created_at,
                command.message_id,
            )
            os.replace(temporary_path, final_path)
            with self._factory(immediate=True) as unit_of_work:
                created = unit_of_work.files.add(metadata, client_request_id)
                if created:
                    unit_of_work.commit()
                    return metadata
                existing = unit_of_work.files.get_by_client_request(user.id, client_request_id)
                unit_of_work.commit()
            final_path.unlink(missing_ok=True)
            if existing is None or not self._same_request(
                existing, channel_id=channel_id, message_id=normalized_message_id,
                original_name=original_name, content_type=content_type,
                size=expected_size, checksum=checksum,
            ):
                raise ApplicationError(ErrorCode.CONFLICT, "concurrent upload used a conflicting client_request_id", request_id)
            return existing
        finally:
            temporary_path.unlink(missing_ok=True)

    def authorize_download(self, token: str | None, file_id: str, *, request_id: str) -> tuple[FileMetadata, Path]:
        user = self._auth.authenticate(token, request_id=request_id)
        with self._factory() as unit_of_work:
            metadata = unit_of_work.files.get(file_id)
            if metadata is None:
                raise ApplicationError(ErrorCode.NOT_FOUND, "file not found", request_id)
            self._authorize_channel(unit_of_work, metadata.channel_id, user.id, request_id, write=False)
        path = (self._root / metadata.storage_reference).resolve()
        if path.parent != self._root or not path.is_file():
            raise ApplicationError(ErrorCode.INTERNAL, "stored file is unavailable", request_id)
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(65_536), b""):
                size += len(chunk)
                digest.update(chunk)
        if size != metadata.size_bytes or digest.hexdigest() != metadata.checksum_sha256:
            raise ApplicationError(ErrorCode.INTERNAL, "stored file failed integrity verification", request_id)
        return metadata, path
