"""The editor reserves one revision before changing any managed assistant."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.audit.domain.action_types import ActionType
from eneo.flows.api.flow_models import FlowEditorUpdateRequest
from eneo.flows.application.flow_authoring_operations import apply_editor_update
from eneo.main.exceptions import BadRequestException
from tests.unittests.flows.test_flow_router import (
    _enable_space_access,
    _flow,
    _request,
    _user,
)


def editor_context():
    container = MagicMock()
    flow = _flow(uuid4())
    user = _user()
    flow.tenant_id = user.tenant_id
    flow.owner_user_id = user.id
    flow.published_version = None
    flow.draft_revision = 4
    service = AsyncMock()
    service.get_flow.return_value = flow
    service.update_flow.return_value = flow.model_copy(update={"draft_revision": 5})
    service.update_reserved_flow_assistant.return_value = (
        SimpleNamespace(id=flow.steps[0].assistant_id, name="Step"),
        [],
    )
    service.get_flow_assistant_prompts.return_value = {}
    container.flow_service.return_value = service
    container.user.return_value = user
    container.audit_service.return_value = AsyncMock()
    _enable_space_access(container)
    return container, service, flow


def test_revision_is_required_and_conflicting_inner_revision_is_refused():
    with pytest.raises(ValidationError):
        FlowEditorUpdateRequest.model_validate({"definition": {}})
    with pytest.raises(ValidationError, match="revisions must agree"):
        FlowEditorUpdateRequest.model_validate(
            {"expected_revision": 4, "definition": {"expected_revision": 3}}
        )
    assistant_id = str(uuid4())
    with pytest.raises(ValidationError, match="only be updated once"):
        FlowEditorUpdateRequest.model_validate(
            {
                "expected_revision": 4,
                "definition": {},
                "assistants": [{"assistant_id": assistant_id, "changes": {}}] * 2,
            }
        )


async def test_stale_revision_writes_neither_assistant_nor_audit():
    container, service, flow = editor_context()
    service.reserve_draft_revision.side_effect = BadRequestException(
        "stale", code="stale_revision"
    )
    with pytest.raises(BadRequestException, match="stale"):
        await apply_editor_update(
            flow.id,
            _request(),
            FlowEditorUpdateRequest.model_validate(
                {
                    "expected_revision": 3,
                    "definition": {},
                    "assistants": [
                        {
                            "assistant_id": str(flow.steps[0].assistant_id),
                            "changes": {"prompt": {"text": "new"}},
                        }
                    ],
                }
            ),
            container,
        )
    service.update_reserved_flow_assistant.assert_not_awaited()
    service.update_flow.assert_not_awaited()
    container.audit_service().log_async.assert_not_awaited()


async def test_joint_update_preserves_unedited_step_rows_and_audits_both_entities():
    container, service, flow = editor_context()
    update = FlowEditorUpdateRequest.model_validate(
        {
            "expected_revision": 4,
            "definition": {"description": "New description"},
            "assistants": [
                {
                    "assistant_id": str(flow.steps[0].assistant_id),
                    "changes": {"prompt": {"text": "new"}},
                }
            ],
        }
    )
    result = await apply_editor_update(flow.id, _request(), update, container)
    assert result.draft_revision == 5
    service.reserve_draft_revision.assert_awaited_once_with(
        flow_id=flow.id, expected_revision=4
    )
    assistant_call = service.update_reserved_flow_assistant.await_args
    assert (
        assistant_call.kwargs["reservation"]
        is service.reserve_draft_revision.return_value
    )
    assert assistant_call.kwargs["classification_judged_by_flow_update"] is True
    saved = service.update_flow.await_args.kwargs
    assert saved["expected_revision"] == 4
    assert saved["steps"] == flow.steps
    assert saved["unchanged_step_ids"] == frozenset({flow.steps[0].id})
    actions = [
        call.kwargs["action"]
        for call in container.audit_service().log_async.await_args_list
    ]
    assert actions == [ActionType.ASSISTANT_UPDATED, ActionType.FLOW_UPDATED]


async def test_final_validation_error_reaches_transaction_owner_and_audits_nothing():
    container, service, flow = editor_context()
    service.update_flow.side_effect = BadRequestException(
        "invalid final classification"
    )
    with pytest.raises(BadRequestException, match="invalid final classification"):
        await apply_editor_update(
            flow.id,
            _request(),
            FlowEditorUpdateRequest.model_validate(
                {
                    "expected_revision": 4,
                    "definition": {},
                    "assistants": [
                        {
                            "assistant_id": str(flow.steps[0].assistant_id),
                            "changes": {"prompt": {"text": "never saved"}},
                        }
                    ],
                }
            ),
            container,
        )
    service.update_reserved_flow_assistant.assert_awaited()
    container.audit_service().log_async.assert_not_awaited()


async def test_sparse_step_patch_carries_other_steps_as_stored():
    from tests.unittests.flows.test_flow_router import _flow_step

    container, service, flow = editor_context()
    flow.steps.append(_flow_step(uuid4(), 2))
    flow.steps[1].input_config = {"inactive_saved_setting": "keep exactly"}
    update = FlowEditorUpdateRequest.model_validate(
        {
            "expected_revision": 4,
            "definition": {},
            "step_edits": [
                {
                    "step_id": str(flow.steps[0].id),
                    "changes": {"user_description": "Renamed"},
                }
            ],
        }
    )
    await apply_editor_update(flow.id, _request(), update, container)
    saved = service.update_flow.await_args.kwargs
    assert saved["steps"][0].user_description == "Renamed"
    assert saved["steps"][0].assistant_id == flow.steps[0].assistant_id
    assert saved["steps"][1] is flow.steps[1]
    assert saved["unchanged_step_ids"] == frozenset({flow.steps[1].id})


async def test_an_assistant_change_naming_a_step_that_uses_another_is_refused():
    from eneo.main.exceptions import NotFoundException

    container, service, flow = editor_context()
    with pytest.raises(NotFoundException):
        await apply_editor_update(
            flow.id,
            _request(),
            FlowEditorUpdateRequest.model_validate(
                {
                    "expected_revision": 4,
                    "definition": {},
                    "assistants": [
                        {
                            "assistant_id": str(uuid4()),
                            "step_id": str(flow.steps[0].id),
                            "changes": {"prompt": {"text": "new"}},
                        }
                    ],
                }
            ),
            container,
        )
    service.update_reserved_flow_assistant.assert_not_awaited()
    container.audit_service().log_async.assert_not_awaited()


async def test_an_assistant_change_for_a_step_with_its_own_assistant_edits_it_in_place():
    container, service, flow = editor_context()
    await apply_editor_update(
        flow.id,
        _request(),
        FlowEditorUpdateRequest.model_validate(
            {
                "expected_revision": 4,
                "definition": {},
                "assistants": [
                    {
                        "assistant_id": str(flow.steps[0].assistant_id),
                        "step_id": str(flow.steps[0].id),
                        "changes": {"prompt": {"text": "new"}},
                    }
                ],
            }
        ),
        container,
    )
    service.copy_reserved_flow_assistant.assert_not_awaited()
    call = service.update_reserved_flow_assistant.await_args
    assert call.kwargs["assistant_id"] == flow.steps[0].assistant_id


async def test_an_audit_context_names_itself_in_every_entry_of_the_change():
    container, _, flow = editor_context()
    context = {"origin": "suggestion", "suggestion_code": "duplicate_read"}
    await apply_editor_update(
        flow.id,
        _request(),
        FlowEditorUpdateRequest.model_validate(
            {
                "expected_revision": 4,
                "definition": {"description": "New description"},
                "assistants": [
                    {
                        "assistant_id": str(flow.steps[0].assistant_id),
                        "changes": {"prompt": {"text": "new"}},
                    }
                ],
            }
        ),
        container,
        audit_context=context,
    )
    entries = [
        call.kwargs for call in container.audit_service().log_async.await_args_list
    ]
    assert [entry["action"] for entry in entries] == [
        ActionType.ASSISTANT_UPDATED,
        ActionType.FLOW_UPDATED,
    ]
    # The context wins over the entry's own origin and keeps its other keys.
    assistant_extra = entries[0]["metadata"]["extra"]
    assert assistant_extra == {"flow_id": str(flow.id), **context}
    assert entries[1]["metadata"]["extra"] == context


async def test_without_an_audit_context_the_entries_are_as_the_editor_writes_them():
    container, _, flow = editor_context()
    await apply_editor_update(
        flow.id,
        _request(),
        FlowEditorUpdateRequest.model_validate(
            {
                "expected_revision": 4,
                "definition": {"description": "New description"},
                "assistants": [
                    {
                        "assistant_id": str(flow.steps[0].assistant_id),
                        "changes": {"prompt": {"text": "new"}},
                    }
                ],
            }
        ),
        container,
    )
    entries = [
        call.kwargs for call in container.audit_service().log_async.await_args_list
    ]
    assert entries[0]["metadata"]["extra"] == {
        "flow_id": str(flow.id),
        "origin": "flow_managed",
    }
    assert "extra" not in entries[1]["metadata"]
