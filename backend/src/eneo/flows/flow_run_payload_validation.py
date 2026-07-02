from __future__ import annotations

import json
from uuid import UUID

from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.flow_run_input_envelope import FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS
from eneo.main.config import get_settings


def reject_reserved_input_payload_keys(
    input_payload_json: FlowPersistedJsonObject | None,
) -> None:
    if input_payload_json is None:
        return
    reserved_keys = sorted(
        set(input_payload_json) & FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS
    )
    if not reserved_keys:
        return
    raise FlowBadRequestException(
        "Flow run input_payload_json contains reserved orchestration keys.",
        code=FlowApiErrorCode.RUN_RESERVED_INPUT_PAYLOAD_KEY,
        context={"keys": reserved_keys},
    )


def ensure_inline_payload_size_allowed(
    *,
    flow_id: UUID,
    input_payload_json: FlowPersistedJsonObject | None,
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
    raise FlowBadRequestException(
        "Flow run input payload exceeds allowed size limit.",
        code=FlowApiErrorCode.RUN_INPUT_PAYLOAD_TOO_LARGE,
        context={
            "flow_id": str(flow_id),
            "max_inline_text_bytes": max_inline_text_bytes,
        },
    )
