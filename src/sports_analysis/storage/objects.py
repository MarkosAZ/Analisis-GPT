"""Immutable private object storage, independent of S3/R2 client libraries."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import uuid4


class ObjectNamespace(StrEnum):
    RAW = "raw"
    PARQUET = "parquet"
    DATASETS = "datasets"
    MODELS = "models"
    MANIFESTS = "manifests"
    DISTRIBUTIONS = "distributions"


class InvalidObjectKey(ValueError):
    """Object keys must stay inside their private storage namespace."""


class ImmutableObjectConflict(ValueError):
    """The key already contains different bytes."""


class ObjectIntegrityError(ValueError):
    """Stored bytes do not match their expected digest or length."""


def validate_key(key: str) -> tuple[str, ...]:
    parts = tuple(key.split("/"))
    if (
        len(parts) < 2
        or parts[0] not in {namespace.value for namespace in ObjectNamespace}
        or any(
            part in {"", ".", ".."} or re.fullmatch(r"[A-Za-z0-9_.-]+", part) is None
            for part in parts
        )
    ):
        raise InvalidObjectKey("Invalid relative object key")
    return parts


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class ObjectRef:
    key: str
    content_hash: str
    size_bytes: int

    def __post_init__(self) -> None:
        validate_key(self.key)
        if (
            re.fullmatch(r"[0-9a-f]{64}", self.content_hash) is None
            or type(self.size_bytes) is not int
            or self.size_bytes < 0
        ):
            raise ValueError("Invalid object reference")


class ObjectStore(Protocol):
    """Adapters must implement conditional creation and verify reads."""

    def put_if_absent(self, key: str, data: bytes) -> ObjectRef: ...

    def get(self, reference: ObjectRef) -> bytes: ...


class LocalObjectStore:
    """POSIX local store; atomic publish, no symlink traversal, no overwrites.

    Directory-descriptor traversal keeps concurrent path replacement from redirecting
    accesses outside the configured root. The root itself is trusted configuration.
    Storage is private infrastructure and must never be published as a Pages artifact.
    """

    def __init__(self, root: Path) -> None:
        if root.is_symlink():
            raise InvalidObjectKey("Storage root must not be a symlink")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root = root.resolve(strict=True)

    @contextmanager
    def _parent(self, parts: tuple[str, ...], *, create: bool) -> Iterator[int]:
        descriptors: list[int] = []
        try:
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            descriptors.append(directory)
            for part in parts[:-1]:
                if create:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=directory)
                    except FileExistsError:
                        pass
                directory = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
                )
                descriptors.append(directory)
            yield directory
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)

    @staticmethod
    def _read(parent: int, name: str) -> bytes:
        # O_NONBLOCK prevents a substituted FIFO from stalling a worker before
        # fstat can reject it. It has no effect on regular files.
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise ObjectIntegrityError("Stored object must be a regular file")
            return handle.read()

    def put_if_absent(self, key: str, data: bytes) -> ObjectRef:
        parts = validate_key(key)
        if not isinstance(data, bytes):
            raise ValueError("Object payload must be immutable bytes")
        reference = ObjectRef(key, sha256(data), len(data))
        with self._parent(parts, create=True) as parent:
            temporary = f".pending-{uuid4().hex}"
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                mode=0o600,
                dir_fd=parent,
            )
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    os.link(
                        temporary,
                        parts[-1],
                        src_dir_fd=parent,
                        dst_dir_fd=parent,
                        follow_symlinks=False,
                    )
                except FileExistsError:
                    if self._read(parent, parts[-1]) != data:
                        raise ImmutableObjectConflict("Object key is already occupied") from None
                os.fsync(parent)
            finally:
                os.unlink(temporary, dir_fd=parent)
        return reference

    def get(self, reference: ObjectRef) -> bytes:
        parts = validate_key(reference.key)
        with self._parent(parts, create=False) as parent:
            data = self._read(parent, parts[-1])
        if len(data) != reference.size_bytes or sha256(data) != reference.content_hash:
            raise ObjectIntegrityError("Object checksum or length mismatch")
        return data
