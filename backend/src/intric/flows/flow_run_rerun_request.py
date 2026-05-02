from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypeAlias, cast
from uuid import UUID

from intric.authentication.principal_types import PrincipalType

JsonPrimitive: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]

RERUN_REQUEST_FINGERPRINT_ALGORITHM_VERSION = 1


@dataclass(frozen=True, slots=True)
class FlowRunRerunRequestFingerprintInput:
    tenant_id: UUID
    requested_by_user_id: UUID
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
    payload: dict[str, JsonValue] = {
        "request_fingerprint_algorithm_version": (
            RERUN_REQUEST_FINGERPRINT_ALGORITHM_VERSION
        ),
        "tenant_id": str(request.tenant_id),
        "principal_type": PrincipalType.USER.value,
        "requested_by_user_id": str(request.requested_by_user_id),
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
) -> dict[str, JsonValue]:
    if step_inputs is None:
        return {}
    normalized: dict[str, JsonValue] = {}
    for step_id, file_ids in sorted(
        step_inputs.items(),
        key=lambda item: str(item[0]),
    ):
        normalized_file_ids: list[JsonValue] = []
        for file_id in sorted(str(file_id) for file_id in file_ids):
            normalized_file_ids.append(file_id)
        normalized[str(step_id)] = {
            "file_ids": normalized_file_ids,
        }
    return normalized


def _normalize_json_object(value: Mapping[str, object] | None) -> JsonValue:
    if value is None:
        return None
    return _normalize_json_value(value)


def _normalize_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        normalized: dict[str, JsonValue] = {}
        for item_key, item_value in sorted(
            cast(Mapping[object, object], value).items(),
            key=lambda item: str(item[0]),
        ):
            normalized[str(item_key)] = _normalize_json_value(item_value)
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize_json_value(item) for item in cast(Sequence[object], value)]
    raise TypeError(
        f"Unsupported rerun request fingerprint value: {type(value).__name__}"
    )
