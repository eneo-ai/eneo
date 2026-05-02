from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

from intric.flows.flow_run_rerun_request import (
    FlowRunRerunRequestFingerprintInput,
    build_rerun_request_fingerprint,
)


def _uuid(value: int) -> UUID:
    return UUID(int=value)


def _request() -> FlowRunRerunRequestFingerprintInput:
    return FlowRunRerunRequestFingerprintInput(
        tenant_id=_uuid(1),
        requested_by_user_id=_uuid(2),
        flow_id=_uuid(3),
        flow_run_id=_uuid(4),
        rerun_step_id=_uuid(5),
        expected_run_revision=7,
        prior_root_attempt_id=_uuid(6),
        input_payload_json={
            "case": {
                "id": "A-123",
                "tags": ["urgent", "appeal"],
            }
        },
        root_step_inputs={
            _uuid(5): [_uuid(12), _uuid(11)],
        },
    )


def _fingerprint(
    request: FlowRunRerunRequestFingerprintInput,
) -> str:
    return build_rerun_request_fingerprint(request)


def test_rerun_request_fingerprint_is_stable_for_equivalent_json_and_file_order():
    first = _request()
    second = replace(
        first,
        input_payload_json={
            "case": {
                "tags": ["urgent", "appeal"],
                "id": "A-123",
            }
        },
        root_step_inputs={
            _uuid(5): [_uuid(11), _uuid(12)],
        },
    )

    assert _fingerprint(first) == _fingerprint(second)


@pytest.mark.parametrize(
    "changed",
    [
        replace(_request(), tenant_id=_uuid(10)),
        replace(_request(), requested_by_user_id=_uuid(20)),
        replace(_request(), flow_id=_uuid(30)),
        replace(_request(), flow_run_id=_uuid(40)),
        replace(_request(), rerun_step_id=_uuid(50)),
        replace(_request(), expected_run_revision=8),
        replace(_request(), prior_root_attempt_id=_uuid(60)),
        replace(_request(), prior_root_attempt_id=None),
        replace(_request(), input_payload_json={"case": {"id": "B-456"}}),
        replace(_request(), root_step_inputs={_uuid(5): [_uuid(13)]}),
    ],
)
def test_rerun_request_fingerprint_changes_for_replay_relevant_fields(
    changed: FlowRunRerunRequestFingerprintInput,
):
    assert _fingerprint(changed) != _fingerprint(_request())


def test_rerun_request_fingerprint_distinguishes_missing_and_empty_input_payload():
    missing_payload = replace(_request(), input_payload_json=None)
    empty_payload = replace(_request(), input_payload_json={})

    assert _fingerprint(missing_payload) != _fingerprint(empty_payload)


def test_rerun_request_fingerprint_treats_missing_step_inputs_as_empty():
    missing_inputs = replace(_request(), root_step_inputs=None)
    empty_inputs = replace(_request(), root_step_inputs={})

    assert _fingerprint(missing_inputs) == _fingerprint(empty_inputs)


def test_rerun_request_fingerprint_rejects_non_json_values():
    request = replace(_request(), input_payload_json={"bad": object()})

    with pytest.raises(TypeError):
        build_rerun_request_fingerprint(request)
