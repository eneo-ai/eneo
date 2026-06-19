from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from intric.authentication.principal_types import PrincipalType
from intric.flows.flow_run_input_envelope import FLOW_INPUT_TRANSCRIPTION_KEY
from intric.flows.principal import FlowPrincipal
from intric.flows.runtime.input_files import load_files_by_requested_ids
from intric.flows.runtime.models import RunExecutionState
from intric.flows.runtime.step_input_resolution import (
    enforce_inline_input_cap,
    resolve_input_source_text,
)
from intric.main.exceptions import TypedIOValidationException


def test_enforce_inline_input_cap_counts_utf8_bytes_not_characters():
    with pytest.raises(TypedIOValidationException) as exc:
        enforce_inline_input_cap(
            text="ååå",
            step_order=2,
            input_source="flow_input",
            max_inline_text_bytes=5,
        )

    assert exc.value.code == "typed_io_input_too_large"


def test_resolve_input_source_text_serializes_non_text_flow_payload():
    run = SimpleNamespace(id=uuid4(), input_payload_json={"number": 7, "enabled": True})

    resolved = resolve_input_source_text(
        input_source="flow_input",
        run=run,
        step_order=1,
        prior_results=[],
        state=None,
        logger=MagicMock(),
    )

    assert resolved == '{"number": 7, "enabled": true}'


def test_resolve_input_source_text_prefers_top_level_text_field():
    run = SimpleNamespace(
        id=uuid4(),
        input_payload_json={
            "text": "explicit flow text",
            "number": 7,
            FLOW_INPUT_TRANSCRIPTION_KEY: "cached transcript",
        },
    )

    resolved = resolve_input_source_text(
        input_source="flow_input",
        run=run,
        step_order=1,
        prior_results=[],
        state=None,
        logger=MagicMock(),
    )

    assert resolved == "explicit flow text"


def test_resolve_input_source_text_skips_runtime_orchestration_metadata_only_payload():
    run = SimpleNamespace(
        id=uuid4(),
        input_payload_json={
            "expected_flow_version": 9,
            "step_inputs": {str(uuid4()): {"file_ids": [str(uuid4())]}},
            "file_ids": [str(uuid4())],
        },
    )

    resolved = resolve_input_source_text(
        input_source="flow_input",
        run=run,
        step_order=1,
        prior_results=[],
        state=None,
        logger=MagicMock(),
    )

    assert resolved == ""


def test_resolve_input_source_text_skips_runtime_transcription_cache_only_payload():
    run = SimpleNamespace(
        id=uuid4(),
        input_payload_json={FLOW_INPUT_TRANSCRIPTION_KEY: "cached transcript"},
    )

    resolved = resolve_input_source_text(
        input_source="flow_input",
        run=run,
        step_order=1,
        prior_results=[],
        state=None,
        logger=MagicMock(),
    )

    assert resolved == ""


def test_resolve_input_source_text_strips_runtime_orchestration_metadata_from_semantic_payload():
    run = SimpleNamespace(
        id=uuid4(),
        input_payload_json={
            "request_id": "abc-123",
            "category": "runtime step upload test",
            "expected_flow_version": 9,
            "step_inputs": {str(uuid4()): {"file_ids": [str(uuid4())]}},
            "file_ids": [str(uuid4())],
        },
    )

    resolved = resolve_input_source_text(
        input_source="flow_input",
        run=run,
        step_order=1,
        prior_results=[],
        state=None,
        logger=MagicMock(),
    )

    assert resolved == (
        '{"request_id": "abc-123", "category": "runtime step upload test"}'
    )


@pytest.mark.asyncio
async def test_load_files_by_requested_ids_returns_requested_order() -> None:
    tenant_id = uuid4()
    principal = FlowPrincipal(
        principal_type=PrincipalType.USER, principal_user_id=uuid4()
    )
    first_file = SimpleNamespace(id=uuid4())
    second_file = SimpleNamespace(id=uuid4())
    file_repo = _FileRepoReturning([second_file, first_file])

    files = await load_files_by_requested_ids(
        file_repo=file_repo,
        requested_ids=[first_file.id, second_file.id],
        principal=principal,
        tenant_id=tenant_id,
    )

    assert files == [first_file, second_file]
    assert file_repo.calls == [
        {
            "ids": [first_file.id, second_file.id],
            "owner_type": "user",
            "owner_user_id": principal.principal_user_id,
            "owner_service_id": None,
            "tenant_id": tenant_id,
        }
    ]


@pytest.mark.asyncio
async def test_load_files_by_requested_ids_cache_hit_reorders_per_request() -> None:
    tenant_id = uuid4()
    principal = FlowPrincipal(
        principal_type=PrincipalType.USER, principal_user_id=uuid4()
    )
    first_file = SimpleNamespace(id=uuid4())
    second_file = SimpleNamespace(id=uuid4())
    file_repo = _FileRepoReturning([second_file, first_file])
    file_cache = {}

    first_result = await load_files_by_requested_ids(
        file_repo=file_repo,
        requested_ids=[first_file.id, second_file.id],
        principal=principal,
        tenant_id=tenant_id,
        file_cache=file_cache,
    )
    second_result = await load_files_by_requested_ids(
        file_repo=file_repo,
        requested_ids=[second_file.id, first_file.id],
        principal=principal,
        tenant_id=tenant_id,
        file_cache=file_cache,
    )

    assert first_result == [first_file, second_file]
    assert second_result == [second_file, first_file]
    assert file_repo.call_count == 1


@pytest.mark.asyncio
async def test_load_files_by_requested_ids_collapses_duplicate_requested_ids() -> None:
    tenant_id = uuid4()
    principal = FlowPrincipal(
        principal_type=PrincipalType.USER, principal_user_id=uuid4()
    )
    first_file = SimpleNamespace(id=uuid4())
    second_file = SimpleNamespace(id=uuid4())
    file_repo = _FileRepoReturning([second_file, first_file])

    files = await load_files_by_requested_ids(
        file_repo=file_repo,
        requested_ids=[first_file.id, second_file.id, first_file.id],
        principal=principal,
        tenant_id=tenant_id,
    )

    assert files == [first_file, second_file]


@pytest.mark.asyncio
async def test_load_files_by_requested_ids_drops_unreturned_ids() -> None:
    tenant_id = uuid4()
    principal = FlowPrincipal(
        principal_type=PrincipalType.USER, principal_user_id=uuid4()
    )
    returned_file = SimpleNamespace(id=uuid4())
    missing_file_id = uuid4()
    file_repo = _FileRepoReturning([returned_file])

    files = await load_files_by_requested_ids(
        file_repo=file_repo,
        requested_ids=[missing_file_id, returned_file.id],
        principal=principal,
        tenant_id=tenant_id,
    )

    assert files == [returned_file]


def test_resolve_input_source_text_all_previous_steps_prefers_state_accumulator():
    run = SimpleNamespace(id=uuid4(), input_payload_json=None)
    cached_result = SimpleNamespace(
        step_order=1, output_payload_json={"text": "from-state"}
    )
    prior_results = [
        SimpleNamespace(step_order=1, output_payload_json={"text": "older"}),
        SimpleNamespace(step_order=2, output_payload_json={"text": "newer"}),
    ]
    state = RunExecutionState(
        completed_by_order={1: cached_result},
        prior_results=[cached_result],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )

    resolved = resolve_input_source_text(
        input_source="all_previous_steps",
        run=run,
        step_order=3,
        prior_results=prior_results,
        state=state,
        logger=MagicMock(),
    )

    assert resolved == "<step_1_output>\nfrom-state\n</step_1_output>\n"


def test_resolve_input_source_text_all_previous_state_excludes_current_and_future():
    run = SimpleNamespace(id=uuid4(), input_payload_json=None)
    state = RunExecutionState(
        completed_by_order={
            1: SimpleNamespace(step_order=1, output_payload_json={"text": "ONE"}),
            3: SimpleNamespace(step_order=3, output_payload_json={"text": "CURRENT"}),
            4: SimpleNamespace(step_order=4, output_payload_json={"text": "FUTURE"}),
        },
        prior_results=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )

    resolved = resolve_input_source_text(
        input_source="all_previous_steps",
        run=run,
        step_order=3,
        prior_results=[],
        state=state,
        logger=MagicMock(),
    )

    assert "<step_1_output>\nONE\n</step_1_output>" in resolved
    assert "CURRENT" not in resolved
    assert "FUTURE" not in resolved


class _FileRepoReturning:
    def __init__(self, files: list[SimpleNamespace]) -> None:
        self._files = files
        self.calls: list[dict[str, object]] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    async def get_list_by_id_for_owner(
        self,
        *,
        ids: list[UUID],
        owner_type: str,
        owner_user_id: UUID | None = None,
        owner_service_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> list[SimpleNamespace]:
        self.calls.append(
            {
                "ids": ids,
                "owner_type": owner_type,
                "owner_user_id": owner_user_id,
                "owner_service_id": owner_service_id,
                "tenant_id": tenant_id,
            }
        )
        return self._files
