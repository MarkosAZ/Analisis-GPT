import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest

from sports_analysis.providers.base import ProviderRequest, RawResponse
from sports_analysis.storage.objects import (
    ImmutableObjectConflict,
    InvalidObjectKey,
    LocalObjectStore,
    ObjectIntegrityError,
    ObjectNamespace,
)
from sports_analysis.storage.raw import InputManifest, canonical_json, load_raw, persist_raw


def test_write_is_idempotent_but_never_overwrites(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    original = store.put_if_absent("raw/provider/sample.bin", b"original")
    assert store.put_if_absent(original.key, b"original") == original
    with pytest.raises(ImmutableObjectConflict):
        store.put_if_absent(original.key, b"replacement")
    assert store.get(original) == b"original"
    assert not tuple(tmp_path.rglob(".pending-*"))


def test_competing_writers_publish_exactly_one_complete_object(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    barrier = Barrier(2)
    inputs = (b"A" * 100_000, b"B" * 100_000)

    def write(payload: bytes) -> bytes | None:
        barrier.wait(timeout=5)
        try:
            reference = store.put_if_absent("raw/race.bin", payload)
        except ImmutableObjectConflict:
            return None
        return store.get(reference)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(write, inputs))
    assert sum(result is not None for result in results) == 1
    assert (tmp_path / "raw/race.bin").read_bytes() in inputs


@pytest.mark.parametrize(
    "key",
    [
        "../escape",
        "/raw/absolute",
        "raw/../escape",
        "raw//empty",
        "raw/./dot",
        "private/a",
        "raw/..\\escape",
        "raw/http://host",
        "raw/a?token=value",
        "raw/a\x00b",
        "raw/",
    ],
)
def test_invalid_keys_never_escape_storage_root(tmp_path: Path, key: str) -> None:
    with pytest.raises(InvalidObjectKey):
        LocalObjectStore(tmp_path).put_if_absent(key, b"data")


def test_symlinks_cannot_redirect_writes_or_reads(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "objects")
    outside = tmp_path / "outside"
    outside.mkdir()
    (store.root / "raw").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        store.put_if_absent("raw/stolen.bin", b"data")
    assert not tuple(outside.iterdir())
    (store.root / "raw").unlink()
    ref = store.put_if_absent("raw/existing.bin", b"expected")
    (outside / "secret").write_bytes(b"expected")
    (store.root / ref.key).unlink()
    (store.root / ref.key).symlink_to(outside / "secret")
    with pytest.raises(OSError):
        store.get(ref)


def test_corruption_is_detected_on_read(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    ref = store.put_if_absent("models/model.bin", b"original")
    (tmp_path / ref.key).write_bytes(b"tampered")
    with pytest.raises(ObjectIntegrityError):
        store.get(ref)


def test_special_file_substitution_fails_without_blocking(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    ref = store.put_if_absent("raw/sample.bin", b"original")
    (tmp_path / ref.key).unlink()
    os.mkfifo(tmp_path / ref.key)
    with pytest.raises(ObjectIntegrityError, match="regular file"):
        store.get(ref)


@pytest.mark.parametrize("namespace", list(ObjectNamespace))
def test_supported_storage_namespaces(tmp_path: Path, namespace: ObjectNamespace) -> None:
    store = LocalObjectStore(tmp_path)
    assert store.get(store.put_if_absent(f"{namespace}/object.bin", b"value")) == b"value"


def response(payload: bytes = b'{"odds":2.0}') -> RawResponse:
    return RawResponse(
        "fixture",
        ProviderRequest("odds", (("event_id", "123"), ("token", "private-value"))),
        datetime(2026, 1, 1, tzinfo=UTC),
        "adapter_v1",
        "1",
        payload,
    )


def test_equal_raw_bytes_keep_distinct_observations_and_sanitized_metadata(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    first = persist_raw(store, response())
    second = persist_raw(store, response())
    assert first.capture_id != second.capture_id
    assert first.payload.key != second.payload.key
    assert first.payload.content_hash == second.payload.content_hash
    metadata_bytes = store.get(first.metadata)
    metadata = json.loads(metadata_bytes)
    assert metadata["content_hash"] == first.payload.content_hash
    assert metadata["params"] == {"event_id": "123"}
    assert b"private-value" not in metadata_bytes
    assert b"token" not in metadata_bytes


def test_retry_same_capture_is_idempotent_and_conflicting_retry_fails(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    identity = uuid4()
    first = persist_raw(store, response(), capture_id=identity)
    assert persist_raw(store, response(), capture_id=identity) == first
    with pytest.raises(ImmutableObjectConflict):
        persist_raw(store, response(b"new bytes"), capture_id=identity)
    assert store.get(first.payload) == response().payload


def test_manifest_verifies_its_inputs_and_is_immutable(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    capture = persist_raw(store, response())
    manifest = InputManifest(uuid4(), (capture,), "pipeline_v1", "normalizer_v1")
    ref = manifest.persist(store)
    assert manifest.persist(store) == ref
    body = json.loads(store.get(ref))
    assert body["captures"][0]["content_hash"] == capture.payload.content_hash
    (tmp_path / capture.payload.key).write_bytes(b"corrupted")
    with pytest.raises(ObjectIntegrityError):
        manifest.persist(store)


def test_manifest_rejects_mixed_capture_identities(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    first = persist_raw(store, response())
    second = persist_raw(store, response())
    mixed = replace(first, metadata=second.metadata)
    manifest = InputManifest(uuid4(), (mixed,), "pipeline_v1", "normalizer_v1")
    with pytest.raises(ValueError, match="Invalid RAW capture metadata"):
        manifest.persist(store)
    assert not (tmp_path / "manifests").exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fetched_at", "private-invalid-timestamp"),
        ("content_hash", "private-invalid-hash"),
        ("metadata_schema_version", "unknown_v2"),
        ("provider", "https://private-host"),
        ("params", {"token": "private-token"}),
    ],
)
def test_raw_metadata_is_validated_without_exposing_content(
    tmp_path: Path, field: str, value: object
) -> None:
    store = LocalObjectStore(tmp_path)
    capture = persist_raw(store, response())
    metadata = json.loads(store.get(capture.metadata))
    metadata[field] = value
    altered = replace(
        capture,
        metadata=store.put_if_absent("raw/altered-metadata.json", canonical_json(metadata)),
    )
    with pytest.raises(ValueError, match="Invalid RAW capture metadata") as error:
        load_raw(store, altered)
    assert "private" not in str(error.value)
