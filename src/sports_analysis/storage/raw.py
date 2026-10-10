"""Captures keep independent identities even when provider bytes are unchanged."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sports_analysis.providers.base import ProviderRequest, RawResponse
from sports_analysis.storage.objects import ObjectRef, ObjectStore, sha256


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


@dataclass(frozen=True)
class StoredRawCapture:
    capture_id: UUID
    payload: ObjectRef
    metadata: ObjectRef


def load_raw(store: ObjectStore, capture: StoredRawCapture) -> RawResponse:
    """Verify both objects and their binding before interpreting persisted bytes.

    Parsing errors intentionally omit external contents, which may be sensitive.
    The logical adapter metadata is reconstructed through its original validators.
    """
    payload = store.get(capture.payload)
    encoded_metadata = store.get(capture.metadata)
    try:
        metadata = json.loads(encoded_metadata)
        if (
            not isinstance(metadata, dict)
            or metadata["metadata_schema_version"] != "raw_metadata_v1"
            or metadata["capture_id"] != str(capture.capture_id)
            or metadata["content_hash"] != capture.payload.content_hash
            or not isinstance(metadata["params"], dict)
        ):
            raise ValueError
        request = ProviderRequest(metadata["endpoint"], tuple(metadata["params"].items()))
        if dict(request.params) != metadata["params"]:
            raise ValueError
        response = RawResponse(
            metadata["provider"],
            request,
            datetime.fromisoformat(metadata["fetched_at"]),
            metadata["adapter_version"],
            metadata["schema_version"],
            payload,
        )
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ValueError("Invalid RAW capture metadata") from None
    return response


def persist_raw(
    store: ObjectStore, response: RawResponse, *, capture_id: UUID | None = None
) -> StoredRawCapture:
    """An explicit capture UUID supports retrying the same logical observation.

    New observations always use a new UUID. Consumers only receive a complete capture
    once both immutable objects exist; interrupted writes can safely be retried.
    """
    identity = uuid4() if capture_id is None else capture_id
    if not isinstance(identity, UUID):
        raise ValueError("Capture identity must be a UUID")
    prefix = f"raw/{response.provider}/{response.fetched_at:%Y-%m-%d}/{identity}"
    metadata = canonical_json(
        {
            "capture_id": str(identity),
            "provider": response.provider,
            "endpoint": response.request.endpoint,
            "params": dict(response.request.params),
            "fetched_at": response.fetched_at.isoformat(),
            "content_hash": sha256(response.payload),
            "adapter_version": response.adapter_version,
            "schema_version": response.schema_version,
            "metadata_schema_version": "raw_metadata_v1",
        }
    )
    # Claim identity before payload publication; a conflicting retry cannot pair a
    # new payload with metadata from a previous observation.
    metadata_reference = store.put_if_absent(f"{prefix}/metadata.json", metadata)
    payload_reference = store.put_if_absent(f"{prefix}/payload.bin", response.payload)
    return StoredRawCapture(identity, payload_reference, metadata_reference)


@dataclass(frozen=True)
class InputManifest:
    analysis_run_id: UUID
    captures: tuple[StoredRawCapture, ...]
    pipeline_version: str
    normalizer_version: str

    def persist(self, store: ObjectStore) -> ObjectRef:
        from sports_analysis.providers.base import validate_label

        validate_label(self.pipeline_version)
        validate_label(self.normalizer_version)
        if len({capture.capture_id for capture in self.captures}) != len(self.captures):
            raise ValueError("Manifest contains duplicate captures")
        # Verify every reference before publishing a manifest that promises reproducibility.
        for capture in self.captures:
            load_raw(store, capture)
        contents = canonical_json(
            {
                "schema_version": "input_manifest_v1",
                "analysis_run_id": str(self.analysis_run_id),
                "pipeline_version": self.pipeline_version,
                "normalizer_version": self.normalizer_version,
                "captures": [
                    {
                        "capture_id": str(capture.capture_id),
                        "raw_key": capture.payload.key,
                        "content_hash": capture.payload.content_hash,
                        "size_bytes": capture.payload.size_bytes,
                        "metadata_key": capture.metadata.key,
                        "metadata_hash": capture.metadata.content_hash,
                    }
                    for capture in self.captures
                ],
            }
        )
        return store.put_if_absent(f"manifests/{self.analysis_run_id}.json", contents)
