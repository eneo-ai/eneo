from __future__ import annotations

import json
from uuid import UUID

from intric.flows.domain.flow import JsonObject
from intric.flows.flow_run_step_inputs import FLOW_RUN_ORCHESTRATION_INPUT_KEYS
from intric.main.config import get_settings
from intric.main.exceptions import BadRequestException


def reject_reserved_input_payload_keys(
    input_payload_json: JsonObject | None,
) -> None:
    if input_payload_json is None:
        return
    reserved_keys = sorted(set(input_payload_json) & FLOW_RUN_ORCHESTRATION_INPUT_KEYS)
    if not reserved_keys:
        return
    raise BadRequestException(
        "Flow run input_payload_json contains reserved orchestration keys.",
        code="flow_run_reserved_input_payload_key",
        context={"keys": reserved_keys},
    )


def ensure_inline_payload_size_allowed(
    *,
    flow_id: UUID,
    input_payload_json: JsonObject | None,
) -> None:
    if input_payload_json is None:
        return
    payload_size = len(
        json.dumps(
            input_payload_json,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    max_inline_text_bytes = get_settings().flow_max_inline_text_bytes
    if payload_size <= max_inline_text_bytes:
        return
    raise BadRequestException(
        "Flow run input payload exceeds allowed size limit.",
        code="flow_run_input_payload_too_large",
        context={
            "flow_id": str(flow_id),
            "max_inline_text_bytes": max_inline_text_bytes,
        },
    )
