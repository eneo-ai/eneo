from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypeGuard, cast
from uuid import UUID

from eneo.authentication.principal_types import PrincipalType
from eneo.json_types import JsonObject, JsonValue

RERUN_REQUEST_FINGERPRINT_ALGORITHM_VERSION = 3


@dataclass(frozen=True, slots=True)
class FlowRunRerunRequestFingerprintInput:
    tenant_id: UUID
    requested_by_principal_type: PrincipalType
    requested_by_user_id: UUID | None
    requested_by_service_id: UUID | None
    flow_id: UUID
    flow_run_id: UUID
    rerun_step_id: UUID
    expected_run_revision: int
    prior_root_attempt_id: UUID | None
    input_payload_json: Mapping[str, object] | None
    root_step_inputs: Mapping[UUID, Sequence[UUID]] | None


def build_rerun_request_fingerprint(
    request: FlowRunRerunRequestFingerprintInput,
) -> str:
    payload: JsonObject = {
        "request_fingerprint_algorithm_version": (
            RERUN_REQUEST_FINGERPRINT_ALGORITHM_VERSION
        ),
        "tenant_id": str(request.tenant_id),
        "principal_type": request.requested_by_principal_type.value,
        "requested_by_user_id": (
            str(request.requested_by_user_id)
            if request.requested_by_user_id is not None
            else None
        ),
        "requested_by_service_id": (
            str(request.requested_by_service_id)
            if request.requested_by_service_id is not None
            else None
        ),
        "flow_id": str(request.flow_id),
        "flow_run_id": str(request.flow_run_id),
        "rerun_step_id": str(request.rerun_step_id),
        "expected_run_revision": request.expected_run_revision,
        "prior_root_attempt_id": (
            str(request.prior_root_attempt_id)
            if request.prior_root_attempt_id is not None
            else None
        ),
        "input_payload_json": _normalize_json_object(request.input_payload_json),
        "root_step_inputs": _normalize_step_inputs(request.root_step_inputs),
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _normalize_step_inputs(
    step_inputs: Mapping[UUID, Sequence[UUID]] | None,
) -> JsonObject:
    if step_inputs is None:
        return {}
    normalized: JsonObject = {}
    for step_id, file_ids in sorted(
        step_inputs.items(),
        key=lambda item: str(item[0]),
    ):
        normalized_file_ids: list[JsonValue] = []
        # Step maps are unordered; each step's file sequence preserves runtime ordinal.
        for file_id in file_ids:
            normalized_file_ids.append(str(file_id))
        normalized[str(step_id)] = {
            "file_ids": normalized_file_ids,
        }
    return normalized


def _normalize_json_object(value: Mapping[str, object] | None) -> JsonObject | None:
    if value is None:
        return None
    return _normalize_json_mapping(value)


def _normalize_json_mapping(
    value: Mapping[str, object] | Mapping[object, object],
) -> JsonObject:
    normalized: JsonObject = {}
    for item_key, item_value in sorted(value.items(), key=lambda item: str(item[0])):
        normalized[str(item_key)] = _normalize_json_value(item_value)
    return normalized


def _normalize_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if _is_json_mapping(value):
        return _normalize_json_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize_json_value(item) for item in cast(Sequence[object], value)]
    raise TypeError(
        f"Unsupported rerun request fingerprint value: {type(value).__name__}"
    )


def _is_json_mapping(value: object) -> TypeGuard[Mapping[object, object]]:
    return isinstance(value, Mapping)
