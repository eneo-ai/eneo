import json
import re
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.flows.application import flow_authoring_chat, flow_authoring_operations
from eneo.internal_mcp import flows
from eneo.internal_mcp.foundation import ToolContext
from eneo.main.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)


def test_large_read_has_explicit_continuation_and_no_false_complete_claim(monkeypatch):
    monkeypatch.setattr(flows, "default_page_cap", lambda: 1600)
    value = {"prompt": '😀"\n' * 4000}
    serialized = json.dumps(
        value, ensure_ascii=False, default=str, separators=(",", ":")
    )
    collected = ""
    offset = 0
    while True:
        result = flows.page_result(value, flow_id=uuid4(), offset=offset, revision=3)
        assert len(result.content[0].text) <= 1600
        page = json.loads(result.content[0].text)
        assert page["offset"] == offset and page["total_chars"] == len(serialized)
        collected += page["content"]
        if page["next_offset"] is None:
            break
        assert page["next_offset"] > offset
        offset = page["next_offset"]
    assert collected == serialized


@pytest.mark.parametrize(
    "changes,saved",
    [
        (
            {"input_config": {"url": "https://elsewhere.test"}},
            {"input_config": {"auth": {"mode": "bearer", "token": "[REDACTED]"}}},
        ),
        ({"output_config": {"auth": {"token": "secret"}}}, {}),
        ({"input_config": {"tool": {"arguments": {"password": "secret"}}}}, {}),
    ],
)
def test_model_cannot_introduce_credentials_or_retarget_a_saved_credential(
    changes, saved
):
    with pytest.raises(BadRequestException):
        flows.require_safe_model_configuration(changes, saved)


def test_model_can_change_an_uncredentialed_destination():
    flows.require_safe_model_configuration(
        {"input_config": {"url": "https://new.test"}}, {}
    )


@pytest.mark.parametrize(
    "auth",
    [
        {"mode": "api_key", "header_name": "X-API-Key"},
        {"mode": "api_key", "header_name": "X-API-Key", "key": ""},
        {"mode": "bearer_token"},
        {"mode": "basic_auth", "username": "service-user", "password": ""},
    ],
)
def test_model_declares_how_a_connection_signs_in_and_leaves_the_secret_empty(auth):
    # The step is built with the auth mode the service needs; the person
    # enters the key in the editor afterwards.
    flows.require_safe_model_configuration(
        {
            "input_config": {
                "url": "https://api.test/cases",
                "auth": auth,
                "custom_headers": [{"name": "X-Signature", "secret": True}],
            }
        },
        {},
    )


@pytest.mark.parametrize(
    "auth",
    [
        {"mode": "api_key", "header_name": "X-API-Key", "key": "sk-live"},
        {"mode": "bearer_token", "token": "abc"},
        {"mode": "basic_auth", "username": "svc", "password": "pw"},
    ],
)
def test_a_declared_mode_that_carries_its_secret_is_refused(auth):
    with pytest.raises(BadRequestException):
        flows.require_safe_model_configuration(
            {"input_config": {"url": "https://api.test/cases", "auth": auth}}, {}
        )


def test_a_declared_mode_without_its_credential_stays_editable_after_save():
    saved = {
        "url": "https://api.test/cases",
        "auth": {"mode": "api_key", "header_name": "X-Key", "key": ""},
    }
    flows.require_safe_model_configuration(
        {
            "input_config": {
                **saved,
                "auth": {**saved["auth"], "header_name": "Api-Key"},
            }
        },
        {"input_config": saved},
    )
    # Once the person has stored the key, the configuration is the editor's.
    stored = {**saved, "auth": {**saved["auth"], "key": {"$secret": "stored"}}}
    with pytest.raises(BadRequestException):
        flows.require_safe_model_configuration(
            {"input_config": {**saved, "url": "https://elsewhere.test"}},
            {"input_config": stored},
        )


def _transaction_container(order: list[str]) -> MagicMock:
    """A container whose session records how its transaction ends."""

    @asynccontextmanager
    async def begin():
        try:
            yield
        except Exception:
            order.append("rollback")
            raise
        else:
            order.append("commit")

    container = MagicMock()
    container.session.return_value.begin = begin
    container.audit_service.return_value.log_async = AsyncMock(
        side_effect=lambda **_: order.append("audit")
    )
    return container


def _tool_context(container: MagicMock, session_id=None):
    @asynccontextmanager
    async def context(_ctx, **_):
        yield ToolContext(container, SimpleNamespace(), uuid4(), session_id or uuid4())

    return context


async def test_failed_mutation_rolls_back_before_its_error_is_converted(monkeypatch):
    order: list[str] = []
    container = _transaction_container(order)
    chat = SimpleNamespace(flow_id=uuid4(), space_id=uuid4(), editing=True)
    monkeypatch.setattr(flows, "internal_tool_context", _tool_context(container))
    load = AsyncMock(return_value=chat)
    monkeypatch.setattr(flow_authoring_chat, "load_authoring_chat", load)
    monkeypatch.setattr(flow_authoring_chat, "require_authoring_edit", AsyncMock())

    async def operation(*_):
        order.append("write")
        flow_authoring_operations._change_audit(container)[0].add(action="never")  # pyright: ignore[reportPrivateUsage]
        raise BadRequestException("still read", code="flow_form_field_still_read")

    result = await flows._call(MagicMock(), operation, editing=True)
    assert order == ["write", "rollback"]
    assert result.isError is True
    assert json.loads(result.content[0].text)["code"] == "flow_form_field_still_read"
    assert load.await_args.kwargs["lock"] is True


def _stale_chat(monkeypatch, order: list[str], current_revision):
    """A chat in edit mode whose change is refused because the draft moved
    on; ``current_revision`` is what the draft is at now, or an exception
    its read raises."""
    from eneo.flows.flow_api_error_code import FlowApiErrorCode
    from eneo.flows.flow_api_exceptions import FlowBadRequestException

    container = _transaction_container(order)
    chat = SimpleNamespace(flow_id=uuid4(), space_id=uuid4(), editing=True)
    monkeypatch.setattr(flows, "internal_tool_context", _tool_context(container))
    load = AsyncMock(return_value=chat)
    monkeypatch.setattr(flow_authoring_chat, "load_authoring_chat", load)
    monkeypatch.setattr(flow_authoring_chat, "require_authoring_edit", AsyncMock())
    read = AsyncMock(
        side_effect=current_revision
        if isinstance(current_revision, Exception)
        else lambda *_: SimpleNamespace(draft_revision=current_revision)
    )
    monkeypatch.setattr(flow_authoring_operations, "get_flow", read)

    async def operation(*_):
        order.append("write")
        raise FlowBadRequestException(
            "Flödet har ändrats sedan det lästes in. Ladda om sidan.",
            code=FlowApiErrorCode.STALE_REVISION,
        )

    return operation, load, read, chat


async def test_a_stale_change_tells_the_model_the_revision_to_read_again_at(
    monkeypatch,
):
    order: list[str] = []
    operation, load, read, chat = _stale_chat(monkeypatch, order, 9)

    result = await flows._call(MagicMock(), operation, editing=True)

    assert result.isError is True
    refusal = json.loads(result.content[0].text)
    assert refusal["code"] == "stale_revision"
    assert refusal["current_revision"] == 9
    assert "read_flow" in refusal["message"]
    assert "reapply only your own change" in refusal["message"]
    assert "Ladda om" not in refusal["message"]
    # The revision is read after the refused change rolled back, in a
    # transaction of its own, for the chat's own flow.
    assert order == ["write", "rollback", "commit"]
    assert load.await_args.kwargs.get("lock", False) is False
    assert read.await_args.args[0] == chat.flow_id


async def test_a_stale_change_whose_revision_cannot_be_read_is_still_reported(
    monkeypatch, caplog
):
    order: list[str] = []
    operation, *_ = _stale_chat(
        monkeypatch, order, NotFoundException("Flow not found.")
    )

    result = await flows._call(MagicMock(), operation, editing=True)

    refusal = json.loads(result.content[0].text)
    assert refusal["code"] == "stale_revision"
    assert refusal["current_revision"] is None
    (record,) = [r for r in caplog.records if "stale change" in r.getMessage()]
    assert record.error_type == "NotFoundException"


async def test_runtime_and_draft_tools_refuse_an_invalid_configuration_alike(
    monkeypatch,
):
    from eneo.flows.api.flow_models import FlowEditorUpdateRequest

    _runtime_chat(monkeypatch)

    async def operation(*_):
        FlowEditorUpdateRequest.model_validate(
            {
                "expected_revision": 1,
                "definition": {},
                "new_steps": [
                    {
                        "name": "Steg",
                        "configuration": {},
                        "assistant": {"instructions": "Sammanfatta."},
                    }
                ],
            }
        )
        raise AssertionError("the configuration is refused")

    result = await flows._call_runtime(MagicMock(), operation)

    assert result.isError is True
    refusal = json.loads(result.content[0].text)
    # The same refusal _call gives: the shape an assistant takes, and the
    # fields the core's model rejects.
    assert set(refusal) == {"message", "code", "errors"}
    assert '{"prompt": {"text": "..."}}' in refusal["message"]
    assert refusal["errors"]


async def test_a_saved_change_is_audited_after_its_commit(monkeypatch):
    order: list[str] = []
    container = _transaction_container(order)
    chat = SimpleNamespace(flow_id=uuid4(), space_id=uuid4(), editing=True)
    monkeypatch.setattr(flows, "internal_tool_context", _tool_context(container))
    monkeypatch.setattr(
        flow_authoring_chat, "load_authoring_chat", AsyncMock(return_value=chat)
    )
    monkeypatch.setattr(flow_authoring_chat, "require_authoring_edit", AsyncMock())

    async def operation(*_):
        order.append("write")
        flow_authoring_operations._change_audit(container)[0].add(action="saved")  # pyright: ignore[reportPrivateUsage]
        return flows.page_result({"saved": True}, flow_id=chat.flow_id)

    result = await flows._call(MagicMock(), operation, editing=True)
    assert result.isError is not True
    # The tenant's audit settings are read in a transaction of their own.
    assert order == ["write", "commit", "audit", "commit"]


async def test_unbound_token_cannot_read_or_write_any_flow(monkeypatch):
    @asynccontextmanager
    async def context(_ctx, **_):
        yield ToolContext(MagicMock(), SimpleNamespace(), uuid4(), None)

    monkeypatch.setattr(flows, "internal_tool_context", context)
    operation = AsyncMock()
    result = await flows._call(MagicMock(), operation)
    assert result.isError is True
    operation.assert_not_awaited()


async def test_view_mode_never_reaches_the_mutating_operation(monkeypatch):
    monkeypatch.setattr(
        flows, "internal_tool_context", _tool_context(_transaction_container([]))
    )
    monkeypatch.setattr(
        flow_authoring_chat,
        "load_authoring_chat",
        AsyncMock(return_value=SimpleNamespace(editing=False)),
    )
    operation = AsyncMock()
    result = await flows._call(MagicMock(), operation, editing=True)
    assert result.isError is True
    operation.assert_not_awaited()


def test_http_without_credentials_remains_configurable_after_save():
    flows.require_safe_model_configuration(
        {"input_config": {"url": "https://new.test", "auth": {"mode": "none"}}},
        {
            "input_config": {
                "url": "https://old.test",
                "auth": {"mode": "none"},
                "custom_headers": [],
            }
        },
    )


def test_a_malformed_http_config_without_credentials_is_left_to_the_core():
    # The shape a model guessed: no credentials, so the core's own validation
    # answers with the fields to fix instead of a credential refusal.
    flows.require_safe_model_configuration(
        {
            "input_config": {
                "request": {
                    "url": "https://httpbin.org/get?arende={{ flow_input.diarienummer }}",
                    "method": "GET",
                    "auth": {"type": "none"},
                    "headers": {},
                }
            }
        },
        {},
    )


@pytest.mark.parametrize(
    "auth",
    [{"type": "bearer", "token": "abc123"}, {"token": "abc123"}, "bearer"],
)
def test_a_malformed_http_config_with_credentials_is_still_refused(auth):
    with pytest.raises(BadRequestException):
        flows.require_safe_model_configuration(
            {"input_config": {"url": "https://new.test", "auth": auth}}, {}
        )


def test_custom_secret_headers_use_the_core_credential_policy():
    with pytest.raises(BadRequestException):
        flows.require_safe_model_configuration(
            {
                "output_config": {
                    "url": "https://new.test",
                    "auth": {"mode": "none"},
                    "custom_headers": [
                        {"name": "X-Custom", "value": "secret", "secret": True}
                    ],
                }
            },
            {},
        )


def _suggestions_chat(monkeypatch, *, may_trace: bool = False):
    """A view-mode chat whose user may or may not view flow traces, and the
    mocked answer of the suggestions read."""
    from eneo.flows.api import flow_suggestions_router
    from eneo.flows.api.flow_suggestions_models import (
        FLOW_SUGGESTIONS_EXAMPLE,
        FlowSuggestionsPublic,
    )
    from eneo.roles.permissions import Permission

    chat = SimpleNamespace(flow_id=uuid4(), space_id=uuid4(), editing=False)
    container = _transaction_container([])
    container.user.return_value = SimpleNamespace(
        permissions=[Permission.FLOWS_VIEW, Permission.FLOWS_MANAGE]
        + ([Permission.FLOWS_TRACE] if may_trace else [])
    )
    monkeypatch.setattr(flows, "internal_tool_context", _tool_context(container))
    monkeypatch.setattr(
        flow_authoring_chat, "load_authoring_chat", AsyncMock(return_value=chat)
    )
    edit = AsyncMock()
    monkeypatch.setattr(flow_authoring_chat, "require_authoring_edit", edit)
    answer = FlowSuggestionsPublic.model_validate(
        {**FLOW_SUGGESTIONS_EXAMPLE, "flow_id": str(chat.flow_id)}
    )
    read = AsyncMock(return_value=answer)
    monkeypatch.setattr(flow_suggestions_router, "read_flow_suggestions_answer", read)
    return chat, answer, read, edit


async def test_read_flow_suggestions_reports_the_drafts_suggestions_in_view_mode(
    monkeypatch,
):
    chat, answer, read, edit = _suggestions_chat(monkeypatch)

    result = await flows.read_flow_suggestions(MagicMock(), offset=0)

    assert result.isError is not True
    page = json.loads(result.content[0].text)
    assert page["flow_id"] == str(chat.flow_id)
    assert page["draft_revision"] == answer.draft_revision
    assert '"code":"duplicate_read"' in page["content"]
    # Dismissed suggestions are left out, and the page says how many.
    assert '"dismissed_count":1' in page["content"]
    assert read.await_args.kwargs.get("include_dismissed", False) is False
    # A read: the tool asks for this chat's flow, judged from the definition
    # alone, and needs no edit mode.
    assert read.await_args.kwargs["id"] == chat.flow_id
    assert read.await_args.kwargs["runs"] == 0
    edit.assert_not_awaited()


async def test_include_runs_measures_ten_runs_for_a_user_who_may_view_traces(
    monkeypatch,
):
    _chat, _answer, read, _edit = _suggestions_chat(monkeypatch, may_trace=True)

    result = await flows.read_flow_suggestions(MagicMock(), include_runs=True, offset=0)

    assert result.isError is not True
    assert read.await_args.kwargs["runs"] == flows.MCP_MEASURED_RUNS == 10
    assert '"note"' not in json.loads(result.content[0].text)["content"]


async def test_include_runs_without_trace_permission_is_static_with_a_note(
    monkeypatch,
):
    _chat, _answer, read, _edit = _suggestions_chat(monkeypatch, may_trace=False)

    result = await flows.read_flow_suggestions(MagicMock(), include_runs=True, offset=0)

    assert result.isError is not True
    assert read.await_args.kwargs["runs"] == 0
    content = json.loads(json.loads(result.content[0].text)["content"])
    assert "permission to view flow traces" in content["note"]


def _apply_chat(monkeypatch, *, editing: bool):
    from eneo.flows.application import flow_suggestion_apply

    chat = SimpleNamespace(flow_id=uuid4(), space_id=uuid4(), editing=editing)
    monkeypatch.setattr(
        flows, "internal_tool_context", _tool_context(_transaction_container([]))
    )
    monkeypatch.setattr(
        flow_authoring_chat, "load_authoring_chat", AsyncMock(return_value=chat)
    )
    if editing:
        monkeypatch.setattr(flow_authoring_chat, "require_authoring_edit", AsyncMock())
    apply = AsyncMock(
        return_value=flow_suggestion_apply.AppliedSuggestions(
            flow=SimpleNamespace(draft_revision=6),  # pyright: ignore[reportArgumentType]
            applied=("a",),
            skipped=("b",),
        )
    )
    monkeypatch.setattr(flow_suggestion_apply, "apply_flow_suggestions", apply)
    return chat, apply


async def test_apply_flow_suggestions_is_refused_outside_edit_mode(monkeypatch):
    _, apply = _apply_chat(monkeypatch, editing=False)

    result = await flows.apply_flow_suggestions(
        MagicMock(), fingerprints=["a"], expected_revision=4
    )

    assert result.isError is True
    apply.assert_not_awaited()


async def test_apply_flow_suggestions_applies_the_batch_in_edit_mode(monkeypatch):
    chat, apply = _apply_chat(monkeypatch, editing=True)

    result = await flows.apply_flow_suggestions(
        MagicMock(), fingerprints=["a", "b"], expected_revision=4
    )

    assert result.isError is not True
    page = json.loads(result.content[0].text)
    assert page["draft_revision"] == 6
    assert json.loads(page["content"]) == {
        "saved": True,
        "applied": ["a"],
        "skipped": ["b"],
    }
    assert apply.await_args.args[0] == chat.flow_id
    assert apply.await_args.kwargs["fingerprints"] == ["a", "b"]
    assert apply.await_args.kwargs["expected_revision"] == 4


async def test_apply_flow_suggestions_reports_a_stale_suggestion(monkeypatch):
    from eneo.main.exceptions import ConflictException

    _, apply = _apply_chat(monkeypatch, editing=True)
    apply.side_effect = ConflictException("gone", code="flow_suggestion_stale")

    result = await flows.apply_flow_suggestions(
        MagicMock(), fingerprints=["a"], expected_revision=4
    )

    assert result.isError is True
    assert json.loads(result.content[0].text)["code"] == "flow_suggestion_stale"


def _dismissing_chat(monkeypatch, *, editing: bool):
    from datetime import datetime, timezone

    from eneo.flows.application import flow_suggestion_dismissals
    from eneo.flows.domain.flow_suggestion_dismissal import FlowSuggestionDismissal

    chat = SimpleNamespace(flow_id=uuid4(), space_id=uuid4(), editing=editing)
    monkeypatch.setattr(
        flows, "internal_tool_context", _tool_context(_transaction_container([]))
    )
    monkeypatch.setattr(
        flow_authoring_chat, "load_authoring_chat", AsyncMock(return_value=chat)
    )
    if editing:
        monkeypatch.setattr(flow_authoring_chat, "require_authoring_edit", AsyncMock())
    dismiss = AsyncMock(
        return_value=FlowSuggestionDismissal(
            fingerprint=_FINGERPRINT,
            code="duplicate_read",
            dismissed_by=uuid4(),
            dismissed_at=datetime.now(timezone.utc),
        )
    )
    monkeypatch.setattr(flow_suggestion_dismissals, "dismiss_flow_suggestion", dismiss)
    return chat, dismiss


_FINGERPRINT = "9b2d3f1a" * 8


async def test_dismiss_flow_suggestion_is_refused_outside_edit_mode(monkeypatch):
    _, dismiss = _dismissing_chat(monkeypatch, editing=False)

    result = await flows.dismiss_flow_suggestion(
        MagicMock(), fingerprint=_FINGERPRINT, code="duplicate_read"
    )

    assert result.isError is True
    dismiss.assert_not_awaited()


async def test_dismiss_flow_suggestion_dismisses_in_edit_mode(monkeypatch):
    from eneo.flows.domain.flow_suggestions import FlowSuggestionCode

    chat, dismiss = _dismissing_chat(monkeypatch, editing=True)

    result = await flows.dismiss_flow_suggestion(
        MagicMock(), fingerprint=_FINGERPRINT, code="duplicate_read"
    )

    assert result.isError is not True
    assert json.loads(json.loads(result.content[0].text)["content"]) == {
        "dismissed": True,
        "fingerprint": _FINGERPRINT,
        "code": "duplicate_read",
    }
    assert dismiss.await_args.args[0] == chat.flow_id
    assert dismiss.await_args.kwargs["fingerprint"] == _FINGERPRINT
    assert dismiss.await_args.kwargs["code"] is FlowSuggestionCode.DUPLICATE_READ


async def test_dismiss_flow_suggestion_refuses_an_unknown_code_or_fingerprint(
    monkeypatch,
):
    _, dismiss = _dismissing_chat(monkeypatch, editing=True)

    for fingerprint, code in (
        (_FINGERPRINT, "no_such_code"),
        ("abc", "duplicate_read"),
    ):
        result = await flows.dismiss_flow_suggestion(
            MagicMock(), fingerprint=fingerprint, code=code
        )
        assert result.isError is True
    dismiss.assert_not_awaited()


# --- Suggestions a chat change introduces ------------------------------------


_DUPLICATE_PROMPT = "Sammanfatta.\n{{ step_1.output.text }}"


def _draft(prompt: str):
    """A two-step draft, its step 2 prompt as given, with fixed ids so the
    draft before and after a change are the same steps."""
    from eneo.flows.infrastructure.flow_repo import StoredAssistantPrompt
    from tests.unit.flows.application.test_flow_suggestion_service import (
        _flow,
        _step,
    )

    steps = [
        _step(1, id=_DRAFT_IDS[0], assistant_id=_DRAFT_IDS[2]),
        _step(2, id=_DRAFT_IDS[1], assistant_id=_DRAFT_IDS[3]),
    ]
    prompts = {
        _DRAFT_IDS[2]: StoredAssistantPrompt(text="Läs brevet.", description=None),
        _DRAFT_IDS[3]: StoredAssistantPrompt(text=prompt, description=None),
    }
    return _flow(steps), prompts


_DRAFT_IDS = [uuid4() for _ in range(4)]


def _changing_chat(
    monkeypatch,
    *,
    before: str,
    after: str,
    fail: bool = False,
    dismissed: dict | None = None,
    blockers: list[BadRequestException] | Exception | None = None,
):
    """A chat in edit mode whose update_step saves the draft from ``before``
    to ``after`` (the step 2 prompt); ``fail`` breaks the analysis,
    ``dismissed`` are the flow's dismissals by fingerprint, and ``blockers``
    is what publish would refuse the saved draft for (an exception when that
    cannot be read)."""
    container = _transaction_container([])
    container.flow_suggestion_dismissal_repo.return_value.list_for_flow = AsyncMock(
        return_value=dismissed or {}
    )
    chat = SimpleNamespace(flow_id=uuid4(), space_id=uuid4(), editing=True)
    monkeypatch.setattr(flows, "internal_tool_context", _tool_context(container))
    monkeypatch.setattr(
        flow_authoring_chat, "load_authoring_chat", AsyncMock(return_value=chat)
    )
    monkeypatch.setattr(flow_authoring_chat, "require_authoring_edit", AsyncMock())
    # Read before the change, after it, and once more for what blocks publish.
    drafts = [_draft(before), _draft(after), _draft(after)]
    service = container.flow_service.return_value
    service.get_flow = AsyncMock(side_effect=[flow for flow, _ in drafts])
    service.publish_blockers = (
        AsyncMock(side_effect=blockers)
        if isinstance(blockers, Exception)
        else AsyncMock(return_value=blockers or [])
    )
    service.get_flow_assistant_prompts = (
        AsyncMock(side_effect=RuntimeError("unreadable"))
        if fail
        else AsyncMock(side_effect=[prompts for _, prompts in drafts])
    )
    saved_step = SimpleNamespace(
        id=_DRAFT_IDS[1],
        assistant_id=_DRAFT_IDS[3],
        step_order=2,
        user_description="Steg 2",
    )
    read = MagicMock(id=_DRAFT_IDS[1], assistant_id=_DRAFT_IDS[3])
    read.model_dump.return_value = {}
    monkeypatch.setattr(
        flow_authoring_operations,
        "get_flow",
        AsyncMock(return_value=SimpleNamespace(steps=[read])),
    )
    save = AsyncMock(return_value=SimpleNamespace(steps=[saved_step], draft_revision=5))
    monkeypatch.setattr(flow_authoring_operations, "apply_editor_update", save)
    # The step's assistant as saved, read when a change touches it.
    from eneo.flows.api import flow_assistant_router

    assistant = MagicMock()
    assistant.model_dump.return_value = {"prompt": {"text": before}}
    monkeypatch.setattr(
        flow_assistant_router, "get_flow_assistant", AsyncMock(return_value=assistant)
    )
    return save


async def _update_step():
    result = await flows.update_step(
        MagicMock(),
        expected_revision=4,
        step_id=_DRAFT_IDS[1],
        changes={"user_description": "Steg 2"},
    )
    assert result.isError is not True
    return json.loads(result.content[0].text)


async def test_a_change_that_adds_a_duplicate_read_reports_it(monkeypatch):
    _changing_chat(monkeypatch, before="Sammanfatta.", after=_DUPLICATE_PROMPT)

    page = await _update_step()

    (introduced,) = page["introduced_suggestions"]
    assert introduced["code"] == "duplicate_read"
    assert introduced["fix_kind"] == "patch"
    assert introduced["steps"] == [
        {"step_order": 2, "name": "Steg 2"},
        {"step_order": 1, "name": "Steg 1"},
    ]
    assert "patch" not in introduced
    assert page["suggestion_count"] == 1
    assert json.loads(page["content"])["saved"] is True


async def test_a_change_that_adds_nothing_reports_an_empty_list(monkeypatch):
    _changing_chat(monkeypatch, before=_DUPLICATE_PROMPT, after=_DUPLICATE_PROMPT)

    page = await _update_step()

    assert page["introduced_suggestions"] == []
    assert page["suggestion_count"] == 1


async def test_a_change_that_fixes_a_suggestion_reports_none_and_fewer(monkeypatch):
    _changing_chat(monkeypatch, before=_DUPLICATE_PROMPT, after="Sammanfatta.")

    page = await _update_step()

    assert page["introduced_suggestions"] == []
    assert page["suggestion_count"] == 0


async def test_a_dismissed_suggestion_a_change_brings_back_is_not_reported(
    monkeypatch,
):
    from datetime import datetime, timezone

    from eneo.flows.application.flow_suggestion_service import flow_suggestions
    from eneo.flows.domain.flow_suggestion_dismissal import FlowSuggestionDismissal

    flow, prompts = _draft(_DUPLICATE_PROMPT)
    (duplicate,) = flow_suggestions(flow, prompts=prompts)
    _changing_chat(
        monkeypatch,
        before="Sammanfatta.",
        after=_DUPLICATE_PROMPT,
        dismissed={
            duplicate.fingerprint: FlowSuggestionDismissal(
                fingerprint=duplicate.fingerprint,
                code=duplicate.code.value,
                dismissed_by=None,
                dismissed_at=datetime.now(timezone.utc),
            )
        },
    )

    page = await _update_step()

    assert page["introduced_suggestions"] == []
    assert page["suggestion_count"] == 0


async def test_a_failed_analysis_still_saves_and_reports_nothing(monkeypatch, caplog):
    save = _changing_chat(
        monkeypatch, before="Sammanfatta.", after=_DUPLICATE_PROMPT, fail=True
    )

    page = await _update_step()

    save.assert_awaited_once()
    assert json.loads(page["content"])["saved"] is True
    assert "introduced_suggestions" not in page
    assert "suggestion_count" not in page
    # Logged by its kind, without the content it read.
    assert "could not be computed" in caplog.text
    assert "unreadable" not in caplog.text


async def test_a_change_reports_what_stands_between_the_draft_and_publishing(
    monkeypatch,
):
    from eneo.flows.domain.flow_step_validation import FlowStepValidationError

    _changing_chat(
        monkeypatch,
        before="Sammanfatta.",
        after="Sammanfatta.",
        blockers=[
            FlowStepValidationError(
                "Step 2: the speaker step has no source of names.",
                step_order=2,
                context={"issue_code": "flow_step_invalid", "step_order": 2},
            ),
            BadRequestException(
                "Choose which speaker identification service the flow uses.",
                code="flow_speaker_service_not_chosen",
            ),
        ],
    )

    page = await _update_step()

    assert page["publish_blockers"] == [
        {
            "code": "flow_step_invalid",
            "message": "Step 2: the speaker step has no source of names.",
            "step": {"step_order": 2, "name": "Steg 2"},
        },
        {
            "code": "flow_speaker_service_not_chosen",
            "message": "Choose which speaker identification service the flow uses.",
        },
    ]
    assert page["publish_blocker_count"] == 2
    assert page["publish_blockers_complete"] is True
    assert "publish_blockers_note" not in page
    assert json.loads(page["content"])["saved"] is True


async def test_a_draft_with_nothing_in_the_way_reports_no_publish_blockers(
    monkeypatch,
):
    _changing_chat(monkeypatch, before="Sammanfatta.", after="Sammanfatta.")

    page = await _update_step()

    assert page["publish_blockers"] == []
    assert page["publish_blocker_count"] == 0
    assert page["publish_blockers_complete"] is True


async def test_the_same_refusal_met_twice_is_one_blocker(monkeypatch):
    from eneo.flows.domain.flow_step_validation import FlowStepValidationError

    def refusal():
        return FlowStepValidationError(
            "Step 2: input_bindings.source_refs[0] has unsupported key 'step'.",
            step_order=2,
            code="flow_input_binding_unsupported_key",
        )

    _changing_chat(
        monkeypatch,
        before="Sammanfatta.",
        after="Sammanfatta.",
        blockers=[refusal(), refusal(), refusal()],
    )

    page = await _update_step()

    assert len(page["publish_blockers"]) == page["publish_blocker_count"] == 1


async def test_a_change_lists_the_first_publish_blockers_and_counts_them_all(
    monkeypatch,
):
    _changing_chat(
        monkeypatch,
        before="Sammanfatta.",
        after="Sammanfatta.",
        blockers=[BadRequestException(f"Refusal {number}.") for number in range(12)],
    )

    page = await _update_step()

    assert [blocker["message"] for blocker in page["publish_blockers"]] == [
        f"Refusal {number}." for number in range(flows.MAX_REPORTED_PUBLISH_BLOCKERS)
    ]
    assert page["publish_blocker_count"] == 12
    # The rest is not silently dropped: the page says where all of them are.
    assert page["publish_blockers_complete"] is False
    assert 'read_flow section "blockers"' in page["publish_blockers_note"]


@pytest.mark.parametrize("cap", range(1000, 1400, 9))
async def test_a_full_page_says_its_publish_blockers_are_cut(monkeypatch, cap):
    monkeypatch.setattr(flows, "default_page_cap", lambda: cap)
    _changing_chat(
        monkeypatch,
        before="Sammanfatta.",
        after="Sammanfatta.",
        blockers=[BadRequestException(f"Refusal {n}. " + "x" * 400) for n in range(3)],
    )

    page = await _update_step()

    assert len(page["publish_blockers"]) < page["publish_blocker_count"] == 3
    assert page["publish_blockers_complete"] is False
    assert 'read_flow section "blockers"' in page["publish_blockers_note"]
    # The note is part of the page it fits in.
    assert len(json.dumps(page, ensure_ascii=False)) <= cap


@pytest.mark.parametrize(
    "blockers",
    [
        [BadRequestException(f"Refusal {n}. " + "x" * 200) for n in range(3)],
        [],
        RuntimeError("unreadable"),
    ],
    ids=["computed", "empty", "unreadable"],
)
@pytest.mark.parametrize("cap", [800, 900, 1000])
async def test_a_crowded_change_result_stays_within_its_page(
    monkeypatch, blockers, cap
):
    monkeypatch.setattr(flows, "default_page_cap", lambda: cap)
    _changing_chat(
        monkeypatch, before="Sammanfatta.", after=_DUPLICATE_PROMPT, blockers=blockers
    )

    page = await _update_step()

    # The optional lists and the note give way; the counters and the flag stay.
    assert len(json.dumps(page, ensure_ascii=False)) <= cap
    assert page["suggestion_count"] >= 1
    if isinstance(blockers, Exception):
        assert page["publish_blockers"] is page["publish_blocker_count"] is None
        assert page["publish_blockers_complete"] is False
    else:
        assert page["publish_blocker_count"] == len(blockers)
        assert page["publish_blockers_complete"] is (
            len(page["publish_blockers"]) == len(blockers)
        )


async def test_unreadable_publish_blockers_still_save_and_say_so(monkeypatch, caplog):
    save = _changing_chat(
        monkeypatch,
        before="Sammanfatta.",
        after="Sammanfatta.",
        blockers=RuntimeError("unreadable"),
    )

    page = await _update_step()

    save.assert_awaited_once()
    assert json.loads(page["content"])["saved"] is True
    # Never silence: the page says the blockers could not be read now.
    assert page["publish_blockers"] is None
    assert page["publish_blocker_count"] is None
    assert page["publish_blockers_complete"] is False
    assert "could not be read" in page["publish_blockers_note"]
    # The suggestions are reported all the same.
    assert page["introduced_suggestions"] == []
    # Logged by its kind, without the content it read.
    assert "Publish blockers could not be computed" in caplog.text
    assert "unreadable" not in caplog.text


_PARTICIPANTS_FORM = {
    "fields": [{"name": "deltagare", "type": "list", "label": "Deltagare"}]
}


def _adding_chat(monkeypatch, steps, *, metadata_json=None):
    """A chat in edit mode on a draft of ``steps`` whose save is recorded;
    the saved draft has the steps in the order the update gives them."""
    from eneo.flows.api import flow_definition_access
    from tests.unit.flows.application.test_flow_step_kinds import _flow

    save = _changing_chat(monkeypatch, before="Sammanfatta.", after="Sammanfatta.")
    flow = _flow(steps, metadata_json=metadata_json)
    monkeypatch.setattr(
        flow_definition_access,
        "require_flow_current_definition_access",
        AsyncMock(return_value=SimpleNamespace(flow=flow)),
    )

    def saved(_id, _request, update, _container, **_):
        from eneo.flows.domain.flow import FlowStep

        by_id = {str(step.id): step for step in steps}
        added = FlowStep.model_validate(
            {
                **update.new_steps[0].configuration.model_dump(exclude_unset=True),
                "id": _ADDED_ID,
                "assistant_id": uuid4(),
                "step_order": 1,
                "user_description": update.new_steps[0].name,
            }
        )
        order = [
            by_id[str(slot.step_id)] if slot.step_id is not None else added
            for slot in update.step_order
        ]
        return SimpleNamespace(
            steps=[
                step.model_copy(update={"step_order": number})
                for number, step in enumerate(order, start=1)
            ],
            draft_revision=update.expected_revision + 1,
        )

    save.side_effect = saved
    return save


_ADDED_ID = uuid4()


async def _add(**arguments):
    result = await flows.add_step(MagicMock(), expected_revision=4, **arguments)
    return result, json.loads(result.content[0].text)


async def test_a_step_is_added_by_its_kind_in_one_revision_at_its_place(monkeypatch):
    from tests.unit.flows.application.test_flow_step_kinds import _step

    first = _step(1)
    save = _adding_chat(monkeypatch, [first, _step(2)])

    result, page = await _add(
        name="Fakta",
        kind="structured",
        position=1,
        values={
            "instruction": "Ta fram beslutet.",
            "example": '{"beslut": "Bifall"}',
        },
    )

    assert result.isError is not True, page
    save.assert_awaited_once()
    update = save.await_args.args[2]
    # Saved against the revision the chat read.
    assert update.expected_revision == 4
    assert update.assistants == []
    (new_step,) = update.new_steps
    assert new_step.assistant.prompt.text == "Ta fram beslutet."
    content = json.loads(page["content"])
    assert content["saved"] is True
    assert content["step_id"] == str(_ADDED_ID)
    assert content["step"]["step_order"] == 1
    assert content["step"]["input_source"] == "flow_input"
    assert content["step"]["output_type"] == "json"
    assert content["step"]["output_fields"] == ["beslut"]
    assert content["step"]["review"] is False
    # The old first step now reads the new one; the answer says so.
    assert content["hand_over"] == [
        {
            "step_id": str(first.id),
            "step_order": 2,
            "name": "Step 1",
            "changes": {"input_source": "previous_step"},
        }
    ]
    assert page["draft_revision"] == 5
    assert "publish_blockers" in page


async def test_a_step_is_added_together_with_the_run_form_field_it_reads(
    monkeypatch,
):
    from tests.unit.flows.application.test_flow_step_kinds import _step

    kept = {"transcription_enabled": True, "transcription_language": "sv"}
    transcribing = _step(
        1,
        input_type="audio",
        output_mode="transcribe_only",
        input_config={
            "runtime_input": {
                "enabled": True,
                "required": True,
                "input_format": "audio",
            }
        },
    )
    save = _adding_chat(monkeypatch, [transcribing], metadata_json={"wizard": kept})

    result, page = await _add(
        name="Granska transkript",
        kind="speakers",
        values={"participants_field": "deltagare"},
        settings={"metadata_json": {"form_schema": _PARTICIPANTS_FORM}},
    )

    assert result.isError is not True, page
    # One revision holds the step and the field; the saved settings are kept.
    save.assert_awaited_once()
    update = save.await_args.args[2]
    assert update.definition.metadata_json == {
        "wizard": kept,
        "form_schema": _PARTICIPANTS_FORM,
    }
    (step,) = update.new_steps
    assert step.name == "Granska transkript"
    assert step.configuration.output_config == {
        "speaker_mapping": {
            "participants_field": "deltagare",
            "speaker_count_field": None,
            "infer_names": False,
        }
    }
    assert json.loads(page["content"])["step"]["review"] is True


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (
            {"settings": {"steps": []}, "values": {"instruction": "Läs."}},
            "can be changed in settings",
        ),
        ({"values": {"url": "https://example.org/"}}, "It does not use url"),
        ({"values": {}}, "It needs instruction"),
    ],
)
async def test_a_step_that_cannot_be_added_as_asked_is_refused_unsaved(
    monkeypatch, arguments, message
):
    save = _adding_chat(monkeypatch, [])

    result, page = await _add(name="Sammanfatta", kind="ai", **arguments)

    assert result.isError is True
    assert message in page["message"]
    save.assert_not_awaited()


async def test_a_credential_sent_with_a_new_step_is_refused_unsaved(monkeypatch):
    from tests.unit.flows.application.test_flow_step_kinds import _step

    save = _adding_chat(monkeypatch, [_step(1)])

    result, page = await _add(
        name="Skicka",
        kind="send_http",
        values={
            "url": "https://example.org/hook",
            "http": {"auth": {"mode": "bearer_token", "token": "hemligt"}},
        },
    )

    assert result.isError is True
    assert "A credential never passes the chat" in page["message"]
    assert "hemligt" not in result.content[0].text
    save.assert_not_awaited()


async def test_add_step_offers_kinds_and_closed_values_in_its_schema():
    from eneo.flows.domain.step_kinds import STEP_KIND_DESCRIPTIONS, FlowStepKind

    (tool,) = [tool for tool in await flows.mcp.list_tools() if tool.name == "add_step"]
    schema = tool.inputSchema
    kinds = schema["$defs"]["FlowStepKind"]["enum"]
    assert kinds == [kind.value for kind in FlowStepKind]
    (values, _null) = schema["properties"]["values"]["anyOf"]
    assert values["additionalProperties"] is False
    assert "instruction" in values["properties"]
    # Its parts are inline, so the shape reads without references.
    upload = values["properties"]["upload"]["anyOf"][0]
    assert upload["properties"]["format"]["enum"] == ["document", "file"]
    assert "$ref" not in json.dumps(values)
    assert "configuration" not in schema["properties"]
    assert "assistant_changes" not in schema["properties"]
    assert schema["additionalProperties"] is False
    description = " ".join((tool.description or "").split())
    for kind, text in STEP_KIND_DESCRIPTIONS.items():
        assert f"{kind.value} ({text})" in description


async def test_a_value_no_kind_has_is_refused_without_its_value(monkeypatch):
    save = _adding_chat(monkeypatch, [])

    result, page = await _add(
        name="Sammanfatta",
        kind="ai",
        values={"instruction": "Läs.", "api_token": "hemligt"},
    )

    assert result.isError is True
    assert "It names api_token, which is not a field here" in page["message"]
    assert "hemligt" not in result.content[0].text
    save.assert_not_awaited()


async def _through_the_server(tool_name, /, **arguments):
    """The text a tool call answers with when the tool server takes it: the
    server checks the arguments before the tool runs."""
    from mcp.server.fastmcp.exceptions import ToolError

    tool = flows.mcp._tool_manager.get_tool(tool_name)
    try:
        result = await tool.run(arguments, context=MagicMock())
    except ToolError as error:
        return True, str(error)
    return bool(result.isError), result.content[0].text


@pytest.mark.parametrize(
    "argument",
    ["review", "upload", "configuration", "assistant_changes"],
)
async def test_an_argument_add_step_does_not_have_is_refused_unsaved(
    monkeypatch, argument
):
    save = _adding_chat(monkeypatch, [])

    refused, text = await _through_the_server(
        "add_step",
        expected_revision=4,
        name="Sammanfatta",
        kind="ai",
        values={"instruction": "Läs."},
        **{argument: {"mode": "MARKOR-1"}},
    )

    assert refused, text
    assert argument in text
    assert "MARKOR-1" not in text
    save.assert_not_awaited()


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        (
            "add_step",
            {"name": "Sammanfatta", "kind": "ai", "values": ["MARKOR-2"]},
        ),
        ("add_step", {"name": "Sammanfatta", "kind": "MARKOR-2"}),
        ("update_steps", {"edits": ["MARKOR-2"]}),
        ("update_steps", {"edits": [{"step_id": "MARKOR-2"}]}),
    ],
)
async def test_a_wrongly_shaped_argument_is_refused_without_its_value(
    monkeypatch, name, arguments
):
    save = _adding_chat(monkeypatch, [])

    refused, text = await _through_the_server(name, expected_revision=4, **arguments)

    assert refused, text
    assert "MARKOR-2" not in text
    save.assert_not_awaited()


async def test_an_unknown_key_in_http_is_refused_without_its_value(monkeypatch):
    from tests.unit.flows.application.test_flow_step_kinds import _step

    save = _adding_chat(monkeypatch, [_step(1)])

    refused, text = await _through_the_server(
        "add_step",
        expected_revision=4,
        name="Skicka",
        kind="send_http",
        values={"url": "https://example.org/hook", "http": {"losenord": "MARKOR-3"}},
    )

    assert refused, text
    assert "losenord" in text
    assert "MARKOR-3" not in text
    save.assert_not_awaited()


async def test_a_url_inside_http_is_refused_unsaved(monkeypatch):
    from tests.unit.flows.application.test_flow_step_kinds import _step

    save = _adding_chat(monkeypatch, [_step(1)])

    result, page = await _add(
        name="Hämta",
        kind="fetch_http",
        values={
            "url": "https://example.org/a",
            "http": {"url": "https://example.org/MARKOR-4"},
        },
    )

    assert result.isError is True
    assert "url" in page["message"]
    assert "MARKOR-4" not in result.content[0].text
    save.assert_not_awaited()


def test_every_draft_changing_tool_reports_introduced_suggestions():
    import inspect

    changing = {
        name
        for name, tool in vars(flows).items()
        if inspect.iscoroutinefunction(tool)
        and "changes_draft=True" in inspect.getsource(tool)
    }

    assert changing == {
        "update_flow_settings",
        "update_step",
        "update_steps",
        "contract_from_example",
        "add_step",
        "move_step",
        "remove_step",
        "apply_flow_suggestions",
    }


async def test_an_example_gives_the_step_its_contract_and_is_not_kept(monkeypatch):
    save = _changing_chat(monkeypatch, before="Sammanfatta.", after="Sammanfatta.")

    result = await flows.contract_from_example(
        MagicMock(),
        expected_revision=4,
        step_id=_DRAFT_IDS[1],
        example=(
            '{"beslut": "Bifall", "belopp": 4500, "a.b": [], "n": null,'
            ' "sak": {"nr": "1"}, "c.d": "x"}'
        ),
    )

    assert result.isError is not True
    page = json.loads(result.content[0].text)
    body = json.loads(page["content"])
    assert body["saved"] is True
    # word: whether a Word field may read the field (publish's rule): a list,
    # an object and a field that may be null cannot be.
    assert body["fields"] == [
        {"name": "beslut", "type": "string", "variable": True, "word": True},
        {"name": "belopp", "type": "number", "variable": True, "word": True},
        {"name": "a.b", "type": "array", "variable": False, "word": False},
        {"name": "n", "type": ["string", "null"], "variable": True, "word": False},
        {"name": "sak", "type": "object", "variable": True, "word": False},
        {"name": "c.d", "type": "string", "variable": False, "word": False},
    ]
    assert body["notes"] == ["empty_list", "null_value"]
    request = save.await_args.args[2]
    (edit,) = request.step_edits
    assert edit.changes.output_type == "json"
    assert edit.changes.output_contract["required"] == [
        "beslut",
        "belopp",
        "a.b",
        "n",
        "sak",
        "c.d",
    ]
    # The contract carries the fields' types, never the example's values.
    assert "Bifall" not in json.dumps(request.model_dump(mode="json"))
    # word says what publish accepts as a Word field's read of the field.
    for field in body["fields"]:
        assert (
            _word_field_publishes(edit.changes.output_contract, field["name"])
            is field["word"]
        ), field


def _word_field_publishes(contract, name):
    from eneo.flows.flow_validators import publish_step_refusals
    from tests.unit.flows.application.test_flow_suggestion_service import _step

    steps = [
        _step(1, output_type="json", output_contract=contract),
        _step(
            2,
            output_mode="template_fill",
            output_type="docx",
            output_config={
                "template_asset_id": str(uuid4()),
                "placeholders": ["falt"],
                "bindings": {"falt": "{{ step_1.output.structured." + name + " }}"},
            },
        ),
    ]
    return not publish_step_refusals(
        steps, metadata_json=None, prompt_templates={1: "Ta fram fakta.", 2: ""}
    )


async def test_an_example_that_gives_no_contract_is_refused_without_saving(monkeypatch):
    save = _changing_chat(monkeypatch, before="Sammanfatta.", after="Sammanfatta.")

    result = await flows.contract_from_example(
        MagicMock(), expected_revision=4, step_id=_DRAFT_IDS[1], example="[1]"
    )

    assert result.isError is True
    assert "JSON object" in result.content[0].text
    save.assert_not_awaited()


async def test_read_run_summarises_a_run_from_its_audited_reads(monkeypatch):
    from eneo.flows.api import flow_run_lifecycle_router, flow_run_steps_router

    container = _transaction_container([])
    chat = SimpleNamespace(flow_id=uuid4(), space_id=uuid4(), editing=False)
    monkeypatch.setattr(flows, "internal_tool_context", _tool_context(container))
    monkeypatch.setattr(
        flow_authoring_chat, "load_authoring_chat", AsyncMock(return_value=chat)
    )
    monkeypatch.setattr(
        flow_authoring_chat,
        "FlowAuthoringChatPublic",
        SimpleNamespace(model_validate=lambda item: item),
    )
    run_id = uuid4()
    detail = SimpleNamespace(
        id=run_id,
        status="completed",
        flow_version=2,
        purpose="production",
        started_at=None,
        finished_at=None,
        token_usage=None,
        error=None,
        result=None,
    )
    step = SimpleNamespace(
        step_order=1,
        status="completed",
        current_attempt_no=1,
        started_at=None,
        finished_at=None,
        num_tokens_input=5,
        num_tokens_output=7,
        effective_prompt_truncated=False,
        long_material=None,
        diagnostics=[],
        error_code=None,
        error_message=None,
    )
    get_run = AsyncMock(return_value=detail)
    list_steps = AsyncMock(return_value=[step])
    graph = AsyncMock(
        return_value=SimpleNamespace(
            nodes=[
                SimpleNamespace(step_order=None, label="Start"),
                SimpleNamespace(step_order=1, label="Sammanfatta"),
            ]
        )
    )
    monkeypatch.setattr(flow_run_lifecycle_router, "get_flow_run", get_run)
    monkeypatch.setattr(flow_run_steps_router, "list_flow_run_steps", list_steps)
    monkeypatch.setattr(flow_run_steps_router, "get_flow_graph", graph)
    repo = container.flow_run_review_checkpoint_repo.return_value
    repo.list_review_checkpoints_for_run = AsyncMock(
        return_value=[
            SimpleNamespace(
                id=uuid4(),
                step_order=1,
                attempt_no=1,
                state="approved",
                review_mode="view",
            )
        ]
    )
    container.user.return_value = SimpleNamespace(tenant_id=uuid4())

    result = await flows.read_run(MagicMock(), run_id=run_id)

    assert result.isError is not True
    page = json.loads(result.content[0].text)
    summary = json.loads(page["content"])
    assert summary["run_id"] == str(run_id)
    assert summary["steps"] == [
        {
            "step_order": 1,
            "name": "Sammanfatta",
            "status": "completed",
            "attempts": 1,
            "duration_seconds": None,
            "tokens": {"input": 5, "output": 7},
            "prompt_truncated": False,
            "coverage": None,
            "diagnostics": [],
            "error": None,
            "review": {
                "state": "approved",
                "attempt": 1,
                "mode": "view",
                "open": False,
            },
        }
    ]
    assert summary["open_review"] is None
    assert result.structuredContent == {
        "flow_id": str(chat.flow_id),
        "run_id": str(run_id),
    }
    # Every read goes through the audited router reads for this flow's run.
    for read in (get_run, list_steps, graph):
        assert read.await_args.kwargs["id"] == chat.flow_id
        assert read.await_args.kwargs["run_id"] == run_id


def _runtime_chat(monkeypatch):
    """A chat whose runtime tools reach the flow's run endpoints."""
    container = _transaction_container([])
    chat = SimpleNamespace(flow_id=uuid4(), space_id=uuid4(), editing=False)
    monkeypatch.setattr(flows, "internal_tool_context", _tool_context(container))
    monkeypatch.setattr(
        flow_authoring_chat, "load_authoring_chat", AsyncMock(return_value=chat)
    )
    monkeypatch.setattr(
        flow_authoring_chat,
        "FlowAuthoringChatPublic",
        SimpleNamespace(model_validate=lambda item: item),
    )
    return container, chat


async def test_retry_run_starts_the_failed_run_again_and_names_the_new_run(monkeypatch):
    from eneo.flows.api import flow_run_retry_router

    _, chat = _runtime_chat(monkeypatch)
    source_id, new_id = uuid4(), uuid4()
    public = MagicMock()
    public.run = SimpleNamespace(id=new_id)
    public.source_run_id = source_id
    public.created = True
    public.model_dump.return_value = {
        "run": {"id": str(new_id), "status": "queued"},
        "created": True,
        "source_run_id": str(source_id),
        "first_executed_step_order": 2,
        "reused_step_orders": [1],
    }
    retry = AsyncMock(return_value=public)
    monkeypatch.setattr(flow_run_retry_router, "retry_flow_run_from_failed_step", retry)

    result = await flows.retry_run(MagicMock(), run_id=source_id, idempotency_key="k-1")

    assert result.isError is not True
    kwargs = retry.await_args.kwargs
    assert kwargs["id"] == chat.flow_id
    assert kwargs["run_id"] == source_id
    assert kwargs["idempotency_key"] == "k-1"
    page = json.loads(result.content[0].text)
    assert json.loads(page["content"])["reused_step_orders"] == [1]
    assert result.structuredContent == {
        "flow_id": str(chat.flow_id),
        "run_id": str(new_id),
        "source_run_id": str(source_id),
        "created": True,
    }


async def test_a_refused_retry_is_an_error_the_model_can_read(monkeypatch):
    from eneo.flows.api import flow_run_retry_router

    _runtime_chat(monkeypatch)
    monkeypatch.setattr(
        flow_run_retry_router,
        "retry_flow_run_from_failed_step",
        AsyncMock(
            side_effect=ConflictException(
                "The source run's flow version is no longer published."
            )
        ),
    )

    result = await flows.retry_run(MagicMock(), run_id=uuid4(), idempotency_key="k-2")

    assert result.isError is True
    assert "no longer published" in result.content[0].text


def test_every_tool_that_needs_edit_mode_is_withheld_while_the_chat_asks():
    import inspect

    needs_edit = {
        name
        for name, tool in vars(flows).items()
        if inspect.iscoroutinefunction(tool)
        and (
            "changes_draft=True" in inspect.getsource(tool)
            or "editing=True" in inspect.getsource(tool)
        )
    }

    assert needs_edit == flows.EDIT_MODE_TOOLS


async def test_a_turn_in_ask_mode_gets_no_tool_that_changes_the_flow():
    asking = await flows.build_flows_mcp_server(
        token="t", tenant_id=uuid4(), editing=False
    )
    editing = await flows.build_flows_mcp_server(
        token="t", tenant_id=uuid4(), editing=True
    )
    offered = {tool.name for tool in asking.tools}
    assert offered.isdisjoint(flows.EDIT_MODE_TOOLS)
    assert {"read_flow", "run_flow", "read_flow_suggestions"} <= offered
    assert {tool.name for tool in editing.tools} - offered == flows.EDIT_MODE_TOOLS


async def test_the_chat_has_no_tool_to_unpublish_a_flow():
    """Taking a published flow out of service is the person's action in the
    editor; the chat can only say so and wait."""
    editing = await flows.build_flows_mcp_server(
        token="t", tenant_id=uuid4(), editing=True
    )
    assert "unpublish_flow" not in {tool.name for tool in editing.tools}
    assert "publish_flow" in {tool.name for tool in editing.tools}


# --- Reading the flow by section ---------------------------------------------


_STEP_2_PROMPT = "Sammanfatta {{ step_1.output.text }}."


def _reading_chat(monkeypatch, blockers=()):
    """A view-mode chat over the example flow: step 2 reads step 1 as its
    input and again in its prompt; publish would refuse it for
    ``blockers``."""
    from eneo.flows.api.flow_models import FLOW_PUBLIC_EXAMPLE, FlowPublic
    from eneo.flows.infrastructure.flow_repo import StoredAssistantPrompt
    from tests.unit.flows.application.test_flow_suggestion_service import (
        _flow,
        _step,
    )

    public = FlowPublic.model_validate(FLOW_PUBLIC_EXAMPLE)
    saved = _flow(
        [
            _step(
                step.step_order,
                id=step.id,
                assistant_id=step.assistant_id,
                user_description=step.user_description,
                input_source=step.input_source.value,
                input_type=step.input_type.value,
                output_mode=step.output_mode.value,
                output_type=step.output_type.value,
            )
            for step in public.steps
        ]
    )
    prompts = {
        public.steps[1].assistant_id: StoredAssistantPrompt(
            text=_STEP_2_PROMPT, description=None
        )
    }
    container = _transaction_container([])
    chat = SimpleNamespace(flow_id=public.id, space_id=uuid4(), editing=False)
    monkeypatch.setattr(flows, "internal_tool_context", _tool_context(container))
    monkeypatch.setattr(
        flow_authoring_chat, "load_authoring_chat", AsyncMock(return_value=chat)
    )
    service = container.flow_service.return_value
    service.get_flow = AsyncMock(return_value=saved)
    service.get_flow_assistant_prompts = AsyncMock(return_value=prompts)
    service.publish_blockers = (
        AsyncMock(side_effect=blockers)
        if isinstance(blockers, Exception)
        else AsyncMock(return_value=list(blockers))
    )
    monkeypatch.setattr(
        flow_authoring_operations, "get_flow", AsyncMock(return_value=public)
    )
    return public


async def _read(**kwargs):
    result = await flows.read_flow(MagicMock(), **kwargs)
    assert result.isError is not True, result.content[0].text
    page = json.loads(result.content[0].text)
    assert page["next_offset"] is None
    return page, json.loads(page["content"])


async def test_the_overview_lists_every_step_with_its_reads_and_readers(monkeypatch):
    public = _reading_chat(monkeypatch)

    page, content = await _read()

    assert page["draft_revision"] == public.draft_revision
    assert content["name"] == public.name
    assert "run_form_fields" in content
    first, second = content["steps"]
    assert first["step_order"] == 1 and first["id"] == str(public.steps[0].id)
    assert first["output_fields"] is None and first["review"] is False
    # Short: no prompt and no configuration columns in the overview.
    assert "prompt" not in second and "input_config" not in second
    assert [(read["step_order"], read["value"]) for read in second["reads"]] == [
        (1, "{{step_1.output.text}}"),
        (1, "{{step_1.output.text}}"),
    ]
    assert second["reads"][1]["where"] == "in its prompt ({{ step_1.output.text }})"
    assert [reader["step_order"] for reader in first["readers"]] == [2, 2]
    assert first["readers"][0]["name"] == public.steps[1].user_description
    assert second["readers"] == []
    # Every step says what services it talks to, here none.
    assert first["connections"] == [] and second["connections"] == []


async def test_the_steps_section_gives_the_chosen_steps_in_full_with_prompts(
    monkeypatch,
):
    public = _reading_chat(monkeypatch)

    _page, content = await _read(section="steps", steps=[2])

    (step,) = content["steps"]
    assert step["id"] == str(public.steps[1].id)
    assert step["prompt"] == _STEP_2_PROMPT
    assert "input_bindings" in step and "output_config" in step
    assert len(step["reads"]) == 2


async def test_the_blockers_section_lists_every_publish_blocker(monkeypatch):
    _reading_chat(
        monkeypatch,
        blockers=[BadRequestException(f"Refusal {n}.") for n in range(12)],
    )

    _page, content = await _read(section="blockers")

    assert [blocker["message"] for blocker in content["publish_blockers"]] == [
        f"Refusal {n}." for n in range(12)
    ]
    assert content["publish_blocker_count"] == 12


async def test_blockers_that_cannot_be_read_are_refused_and_say_so(monkeypatch):
    _reading_chat(monkeypatch, blockers=RuntimeError("unreadable"))

    result = await flows.read_flow(MagicMock(), section="blockers")

    assert result.isError is True
    assert "could not be read" in json.loads(result.content[0].text)["message"]


async def test_more_blockers_than_a_page_holds_are_read_in_full_page_by_page(
    monkeypatch,
):
    monkeypatch.setattr(flows, "default_page_cap", lambda: 2000)
    messages = [f"Refusal {n}. " + "x" * 200 for n in range(40)]
    _reading_chat(monkeypatch, blockers=[BadRequestException(m) for m in messages])

    text, offset, pages = "", 0, 0
    while offset is not None:
        result = await flows.read_flow(MagicMock(), section="blockers", offset=offset)
        page = json.loads(result.content[0].text)
        text, offset, pages = text + page["content"], page["next_offset"], pages + 1

    assert pages > 1
    content = json.loads(text)
    assert [blocker["message"] for blocker in content["publish_blockers"]] == messages
    assert content["publish_blocker_count"] == 40


async def test_a_step_number_the_flow_lacks_is_refused(monkeypatch):
    _reading_chat(monkeypatch)

    result = await flows.read_flow(MagicMock(), steps=[2, 7])

    assert result.isError is True
    assert "No step 7" in json.loads(result.content[0].text)["message"]


async def test_the_settings_section_leaves_the_steps_out(monkeypatch):
    public = _reading_chat(monkeypatch)

    _page, content = await _read(section="settings")

    assert "steps" not in content
    assert content["permissions"] == public.permissions.model_dump(mode="json")
    assert content["draft_revision"] == public.draft_revision


_OFFER = {
    "transcription_models": [{"name": "Filer", "streams_live": False, "default": True}],
    "speaker_services": [],
}


@pytest.mark.parametrize("section", ["overview", "settings"])
async def test_a_read_says_what_the_space_offers_for_transcription(
    monkeypatch, section
):
    _reading_chat(monkeypatch)
    monkeypatch.setattr(flows, "_transcription_offer", AsyncMock(return_value=_OFFER))

    _page, content = await _read(section=section)

    assert content["transcription_offer"] == _OFFER


async def test_a_space_that_cannot_be_read_leaves_the_offer_out_of_the_read(caplog):
    container = _transaction_container([])
    container.space_service.return_value.get_space = AsyncMock(
        side_effect=RuntimeError("unreadable")
    )

    assert await flows._transcription_offer(container, uuid4()) is None
    # Logged by its kind, without the content it read.
    assert "transcription offer could not be read" in caplog.text
    assert "unreadable" not in caplog.text


async def test_the_all_section_is_the_whole_definition(monkeypatch):
    public = _reading_chat(monkeypatch)

    _page, content = await _read(section="all")

    assert content == public.model_dump(mode="json")


# --- Several steps in one change -----------------------------------------------


async def test_update_steps_saves_every_edit_and_the_settings_in_one_revision(
    monkeypatch,
):
    save = _changing_chat(monkeypatch, before="Sammanfatta.", after=_DUPLICATE_PROMPT)

    result = await flows.update_steps(
        MagicMock(),
        expected_revision=4,
        edits=[
            {
                "step_id": str(_DRAFT_IDS[1]),
                "changes": {"user_description": "Steg 2"},
                "assistant_changes": {"prompt": {"text": _DUPLICATE_PROMPT}},
            }
        ],
        settings={"description": "Ny beskrivning"},
    )

    assert result.isError is not True, result.content[0].text
    save.assert_awaited_once()
    request = save.await_args.args[2]
    assert request.expected_revision == 4
    assert [edit.step_id for edit in request.step_edits] == [_DRAFT_IDS[1]]
    assert request.step_edits[0].changes.user_description == "Steg 2"
    assert [(a.assistant_id, a.step_id) for a in request.assistants] == [
        (_DRAFT_IDS[3], _DRAFT_IDS[1])
    ]
    assert request.definition.description == "Ny beskrivning"
    page = json.loads(result.content[0].text)
    assert page["draft_revision"] == 5
    changes = [
        {"field": "user_description", "before": None, "after": "Steg 2"},
        {
            "field": "assistant.prompt",
            "before": "Sammanfatta.",
            "after": _DUPLICATE_PROMPT,
        },
    ]
    assert json.loads(page["content"]) == {
        "saved": True,
        "steps": [
            {
                "step_id": str(_DRAFT_IDS[1]),
                "step_order": 2,
                "name": "Steg 2",
                "assistant_id": str(_DRAFT_IDS[3]),
                "changes": changes,
            }
        ],
    }
    # The affected steps, with each field before and after, travel with the
    # call for the chat's change card.
    assert result.structuredContent == {
        "flow_id": page["flow_id"],
        "draft_revision": 5,
        "changes": [
            {
                "step_id": str(_DRAFT_IDS[1]),
                "step_order": 2,
                "name": "Steg 2",
                "fields": changes,
            }
        ],
    }
    # A batch reports what it introduced like any other change.
    assert [item["code"] for item in page["introduced_suggestions"]] == [
        "duplicate_read"
    ]


@pytest.mark.parametrize(
    "edits,settings",
    [
        ([], None),
        ([{"step_id": str(_DRAFT_IDS[1])}], None),
        (
            [
                {"step_id": str(_DRAFT_IDS[1]), "changes": {"user_description": "a"}},
                {"step_id": str(_DRAFT_IDS[1]), "changes": {"user_description": "b"}},
            ],
            None,
        ),
        ([{"step_id": str(_DRAFT_IDS[1]), "edits": {}}], None),
        ([{"step_id": str(uuid4()), "changes": {"user_description": "a"}}], None),
        ([{"step_id": str(_DRAFT_IDS[1]), "changes": {"step_order": 1}}], None),
        (
            [
                {
                    "step_id": str(_DRAFT_IDS[1]),
                    "changes": {"output_config": {"auth": {"token": "secret"}}},
                }
            ],
            None,
        ),
        ([], {"published_version": 2}),
    ],
)
async def test_update_steps_refuses_a_bad_batch_without_saving(
    monkeypatch, edits, settings
):
    save = _changing_chat(monkeypatch, before="Sammanfatta.", after="Sammanfatta.")

    result = await flows.update_steps(
        MagicMock(), expected_revision=4, edits=edits, settings=settings
    )

    assert result.isError is True
    save.assert_not_awaited()


async def test_update_steps_states_the_shape_of_an_edit_in_its_schema():
    (tool,) = [t for t in await flows.mcp.list_tools() if t.name == "update_steps"]
    edit = tool.inputSchema["properties"]["edits"]["items"]

    assert set(edit["properties"]) == {"step_id", "changes", "assistant_changes"}
    assert edit["required"] == ["step_id"]
    assert edit["additionalProperties"] is False


async def test_an_edit_of_another_shape_is_refused_without_its_value(monkeypatch):
    save = _changing_chat(monkeypatch, before="Sammanfatta.", after="Sammanfatta.")

    result = await flows.update_steps(
        MagicMock(),
        expected_revision=4,
        edits=[{"step_id": str(_DRAFT_IDS[1]), "token": "hemligt"}],
    )

    assert result.isError is True
    assert "An edit has step_id, changes and assistant_changes only" in (
        result.content[0].text
    )
    assert "hemligt" not in result.content[0].text
    save.assert_not_awaited()


def test_an_assistant_given_a_field_it_lacks_is_told_its_shape():
    from pydantic import ValidationError

    from eneo.flows.api.flow_models import FlowEditorUpdateRequest

    with pytest.raises(ValidationError) as refused:
        FlowEditorUpdateRequest.model_validate(
            {
                "expected_revision": 1,
                "definition": {},
                "new_steps": [
                    {
                        "name": "Sammanfatta",
                        "configuration": {},
                        "assistant": {"instructions": "Sammanfatta brevet."},
                    }
                ],
            }
        )
    errors = refused.value.errors(include_input=False, include_context=False)

    assert '{"prompt": {"text": "..."}}' in flows.invalid_message(errors)
    # Any other invalid configuration keeps the plain refusal.
    assert flows.invalid_message([]) == "The submitted configuration is invalid."
    # The tool that takes an assistant says its shape up front.
    assert '{"prompt": {"text": ' in (flows.update_step.__doc__ or "")


@pytest.mark.parametrize(
    "update",
    [
        {
            "new_steps": [
                {
                    "name": "Transkribera",
                    "configuration": {
                        "kind": "transcribe_only",
                        "output_mode": "transcribe_only",
                    },
                }
            ]
        },
        {"step_edits": [{"step_id": str(uuid4()), "changes": {"kind": "ai"}}]},
    ],
    ids=["a new step", "a saved step"],
)
def test_a_step_given_a_field_it_lacks_is_told_which_and_what_a_step_takes(update):
    from pydantic import ValidationError

    from eneo.flows.api.flow_models import FlowEditorUpdateRequest

    with pytest.raises(ValidationError) as refused:
        FlowEditorUpdateRequest.model_validate(
            {"expected_revision": 1, "definition": {}, **update}
        )
    errors = refused.value.errors(include_input=False, include_context=False)

    message = flows.invalid_message(errors)

    assert "It names kind, which is not a field here" in message
    assert "leave it out and make the call again" in message
    assert "A step is described by these fields and no other: " in message
    for field in ("input_source", "input_type", "output_mode", "output_type"):
        assert field in message
    # The core gives a step its identity and place; they are not offered.
    assert "assistant_id" not in message
    assert "step_order" not in message
    # Nothing is said of an assistant that was not part of the mistake.
    assert "An assistant takes" not in message


def test_a_step_is_added_by_its_kind_and_changed_by_its_fields():
    assert "with its kind" not in (flows.read_flow.__doc__ or "")
    assert "A saved step is changed with update_step, never by a kind" in " ".join(
        (flows.add_step.__doc__ or "").split()
    )


# --- A Word step keeps its template ------------------------------------------


_WORD_STEP = {
    "output_mode": "template_fill",
    "output_config": {
        "template_asset_id": "7b0e2f0a-8d4c-4c3e-9f51-2b6a1f0c9d11",
        "template_name": "Beslut.docx",
        "placeholders": ["namn"],
        "bindings": {},
    },
}


_TEMPLATE_ID = _WORD_STEP["output_config"]["template_asset_id"]


@pytest.mark.parametrize(
    "output_config",
    [
        {"bindings": {"namn": "{{ flow_input.namn }}"}},
        {"template_asset_id": None, "bindings": {}},
        {"template_asset_id": " ", "bindings": {}},
        {"template_asset_id": "0f7c1d2e-3b4a-4c5d-8e6f-7a8b9c0d1e2f", "bindings": {}},
    ],
)
def test_an_object_without_the_word_steps_template_is_refused(output_config):
    with pytest.raises(BadRequestException) as refused:
        flows.require_kept_template({"output_config": output_config}, _WORD_STEP)

    # It says how to keep the template and how to remove it on purpose.
    assert _TEMPLATE_ID in str(refused.value)
    assert "null" in str(refused.value)


@pytest.mark.parametrize(
    "changes",
    [
        # The id alone keeps the template: the save refills its field names
        # and publish reads its name and checksum itself.
        {
            "output_config": {
                "template_asset_id": _TEMPLATE_ID,
                "bindings": {"namn": ""},
            }
        },
        # null removes the template on purpose.
        {"output_config": None},
        # A step that stops filling a template takes its template with it.
        {"output_mode": "pass_through", "output_config": {}},
        {"user_description": "Beslut"},
    ],
)
def test_a_change_that_keeps_or_removes_the_template_on_purpose_is_saved(changes):
    flows.require_kept_template(changes, _WORD_STEP)


# --- What a step reads ---------------------------------------------------------


async def _descriptions() -> dict[str, str]:
    return {
        tool.name: " ".join((tool.description or "").split())
        for tool in await flows.mcp.list_tools()
    }


async def test_a_step_that_mostly_copies_its_input_is_worth_trying_without_a_model():
    description = (await _descriptions())["read_flow_suggestions"]

    # What the check measured, not a verdict that the step only copies.
    assert "only copies its inputs" not in description
    assert "most of the step's output was its input copied" in description
    assert (
        "a step without a model is worth trying when the step's own part is not "
        "needed" in description
    )


async def test_update_step_states_the_shape_of_what_a_step_reads():
    from eneo.flows.input_binding_contract_rules import (
        SOURCE_REF_KEYS,
        SUPPORTED_INPUT_BINDING_KEYS,
    )

    descriptions = await _descriptions()
    shape = descriptions["update_step"]

    # Every key the step rules accept is named where the chat reads it.
    for key in SUPPORTED_INPUT_BINDING_KEYS | SOURCE_REF_KEYS:
        assert key in shape, key
    assert "input_contract" in shape
    for example in [*flows.INPUT_BINDINGS_EXAMPLES.values(), flows.JSON_READ_EXAMPLE]:
        assert json.dumps(example, ensure_ascii=False) in shape
    # What a json step's projection excludes, and when no contract is sent.
    assert "no question and no item_template" in shape
    assert "With other input_bindings send no input_contract" in shape
    assert "a json step without input_bindings may keep its own" in shape
    assert "otherwise send no input_contract" not in shape
    # Both configs are replaced whole.
    assert "input_config and output_config are each replaced whole" in shape
    # The other tools that take a step's fields point to it, without a copy.
    for name in ("add_step", "update_steps"):
        assert "update_step" in descriptions[name]
        assert '"source_refs"' not in descriptions[name]


@pytest.mark.parametrize("name", ["fields", "text", "json"])
def test_each_read_update_step_shows_is_saved_and_published(name):
    from eneo.flows.flow_validators import publish_step_refusals, validate_steps
    from eneo.flows.input_binding_contract_rules import (
        derive_structured_projection_contract,
    )
    from tests.unit.flows.application.test_flow_suggestion_service import _step

    facts = {
        "type": "object",
        "properties": {
            "beslut": {"type": "string"},
            "datum": {"type": "string"},
            "deltagare": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["beslut", "datum", "deltagare"],
    }
    reader = (
        flows.JSON_READ_EXAMPLE
        if name == "json"
        else {"input_bindings": flows.INPUT_BINDINGS_EXAMPLES[name]}
    )
    steps = [
        _step(1, output_type="json", output_contract=facts),
        _step(2, **reader),
    ]
    prompts = {1: "Ta fram fakta ur protokollet.", 2: "Skriv ett beslutsbrev."}
    if name == "json":
        # The contract shown is the one the step rules derive.
        assert reader["input_contract"] == derive_structured_projection_contract(
            input_bindings=reader["input_bindings"],
            source_contracts_by_step_ref={"step_1": facts},
        )

    validate_steps(steps, metadata_json=None, prompt_templates=prompts)
    assert (
        publish_step_refusals(steps, metadata_json=None, prompt_templates=prompts) == []
    )


# --- The examples the chat reads -------------------------------------------------

# The assistant's own fields as add_step and update_step show them.
_ASSISTANT_EXAMPLES = [{"prompt": {"text": "Sammanfatta brevet."}}]
# Shapes of a tool's arguments that hold no configuration, by why.
_ARGUMENT_SHAPES = {
    '{"old name": "new name"}': "form_field_renames maps the form's own names",
    '{"step_id": ..., "changes": {...}': "update_steps' call shape",
}


async def test_every_example_the_chat_reads_is_one_the_rules_are_held_to():
    from eneo.flows.api.flow_models import FlowAssistantUpdateRequest

    texts = [
        flow_authoring_chat.AUTHORING_INSTRUCTIONS,
        *(await _descriptions()).values(),
    ]
    validated = [
        *flow_authoring_chat.CONFIGURATION_EXAMPLES.values(),
        *flows.INPUT_BINDINGS_EXAMPLES.values(),
        flows.JSON_READ_EXAMPLE,
        *_ASSISTANT_EXAMPLES,
    ]
    for example in _ASSISTANT_EXAMPLES:
        FlowAssistantUpdateRequest.model_validate(example)

    decoder = json.JSONDecoder()
    found = []
    for text in texts:
        flat = " ".join(text.split())
        end = 0
        for opener in re.finditer(r'[{\[]\s*"', flat):
            if opener.start() < end:
                continue  # inside the example just read
            if any(
                flat.startswith(shape, opener.start()) for shape in _ARGUMENT_SHAPES
            ):
                end = opener.end()
                continue
            try:
                value, length = decoder.raw_decode(flat, opener.start())
            except json.JSONDecodeError:
                pytest.fail(
                    f"Not an example the code can read: {flat[opener.start() :][:80]}"
                )
            end = length
            found.append(value)
            assert value in validated, value
            # A placeholder is a value the rules accept and a model can save.
            assert '"..."' not in json.dumps(value), value
    # Every example kept as data is one the chat reads.
    for example in validated:
        assert example in found, example


def _configured_flows(examples):
    """Flows that put each configuration example where its rules run."""
    from tests.unit.flows.application.test_flow_suggestion_service import _step

    form = {
        "fields": [
            examples["form_field"],
            {"name": "datum", "type": "date", "label": "Datum", "required": True},
            {"name": "arende", "type": "text", "label": "Ärende", "required": True},
        ]
    }
    upload = [
        _step(
            1,
            input_type="document",
            input_config={
                "runtime_input": {"enabled": True, "input_format": "document"},
                "long_material": examples["long_material"],
            },
        ),
        _step(
            2,
            output_mode="template_fill",
            output_type="docx",
            output_config={
                "template_asset_id": str(uuid4()),
                "placeholders": ["datum"],
                "bindings": examples["word_bindings"],
            },
        ),
    ]
    request = examples["http_request"]
    deliveries = [
        [
            _step(1, input_source="http_get", input_type="json", input_config=request),
            _step(2),
            _step(
                3,
                output_mode="http_post",
                output_config={
                    **request,
                    "auth": examples[auth],
                    "body": examples[body],
                    "custom_headers": [examples["secret_header"]],
                },
            ),
        ]
        for auth in ("auth_none", "auth_bearer_token", "auth_api_key", "auth_basic")
        for body in ("body_auto", "body_template", "body_none")
    ]
    return [
        (upload, {"form_schema": form}),
        *((steps, {"form_schema": form}) for steps in deliveries),
    ]


def _refusals(steps, metadata):
    """What a draft save and a publish refuse ``steps`` for, by the step rules
    and the run form's."""
    from eneo.flows.flow_validators import draft_step_refusals, publish_step_refusals
    from eneo.flows.flow_validators_form import validate_form_schema

    validate_form_schema(metadata)
    prompts = {
        step.step_order: (
            "Sammanfatta underlaget."
            if step.output_mode in ("pass_through", "http_post")
            else ""
        )
        for step in steps
    }
    return (
        draft_step_refusals(steps, metadata_json=metadata),
        publish_step_refusals(steps, metadata_json=metadata, prompt_templates=prompts),
    )


class _Placed(dict):
    """The examples, recording which ones a flow places."""

    def __init__(self, examples):
        super().__init__(examples)
        self.placed = set()

    def __getitem__(self, name):
        self.placed.add(name)
        return super().__getitem__(name)


def test_each_configuration_example_is_saved_and_published():
    examples = _Placed(flow_authoring_chat.CONFIGURATION_EXAMPLES)
    configured = _configured_flows(examples)
    # Every example is placed where its rules run.
    assert examples.placed == set(flow_authoring_chat.CONFIGURATION_EXAMPLES)
    for steps, metadata in configured:
        draft, publish = _refusals(steps, metadata)

        assert draft == []
        # A declared auth mode waits only for the credential the person enters.
        assert all("HTTP_MISSING_AUTH" in str(refusal) for refusal in publish), publish


@pytest.mark.parametrize(
    ("name", "broken"),
    [
        ("long_material", {"mode": "summary"}),
        ("word_bindings", {"datum": "{{ flow_input.datum }} och mer"}),
        ("http_request", {"url": "...", "auth": {"mode": "none"}}),
        ("form_field", {"name": "deltagare", "type": "lista", "label": "Deltagare"}),
    ],
)
def test_an_example_the_rules_refuse_fails_the_check(name, broken):
    from pydantic import ValidationError

    examples = {**flow_authoring_chat.CONFIGURATION_EXAMPLES, name: broken}

    def refused(steps, metadata):
        try:
            draft, publish = _refusals(steps, metadata)
        except (BadRequestException, ValidationError):
            return True
        return bool(draft) or any(
            "HTTP_MISSING_AUTH" not in str(refusal) for refusal in publish
        )

    try:
        configured = _configured_flows(examples)
    except ValidationError:
        return  # the step model refuses it
    assert any(refused(*flow) for flow in configured)


def test_a_refused_read_names_the_shape_the_step_rules_take():
    from eneo.flows.domain.flow_step_validation import FlowStepValidationError
    from eneo.flows.input_binding_contract_rules import (
        FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
        SOURCE_REF_KEYS,
    )

    result = flows._error_result(
        FlowStepValidationError(
            "Step 2: input_bindings.source_refs[0] has unsupported key 'step'.",
            step_order=2,
            code=FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
        )
    )

    refusal = json.loads(result.content[0].text)
    assert refusal["code"] == FLOW_INPUT_BINDING_UNSUPPORTED_KEY
    assert refusal["message"].startswith("Step 2: input_bindings.source_refs[0]")
    for key in SOURCE_REF_KEYS:
        assert key in refusal["message"], key
    assert "update_step" in refusal["message"]


def test_a_refusal_that_names_no_unsupported_key_gets_no_shape_hint():
    from eneo.flows.domain.flow_step_validation import FlowStepValidationError
    from eneo.flows.input_binding_contract_rules import (
        FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
    )

    message = (
        "Step 2: Input binding path 'step_1.output.structured.x' requires the "
        "referenced step to declare output_contract."
    )
    result = flows._error_result(
        FlowStepValidationError(
            message, step_order=2, code=FLOW_INPUT_BINDING_UNSUPPORTED_KEY
        )
    )

    assert json.loads(result.content[0].text)["message"] == message


# --- What each tool declares ---------------------------------------------------


_ACTING_TOOLS = {"run_flow", "retry_run", "cancel_run", "review_run", "publish_flow"}
_READING_TOOLS = {
    "read_flow",
    "read_step_assistant",
    "read_step_kinds",
    "read_tool_options",
    "read_flow_suggestions",
    "read_run",
    "read_review",
}


async def test_the_tools_that_act_beyond_the_draft_declare_destructive_hint():
    """The chat asks the person before each call of a tool that declares
    destructiveHint; every tool states both hints so the protocol's
    defaults never decide."""
    tools = {tool.name: tool.annotations for tool in await flows.mcp.list_tools()}

    assert all(annotations is not None for annotations in tools.values())
    acting = {name for name, hints in tools.items() if hints.destructiveHint is True}
    reading = {name for name, hints in tools.items() if hints.readOnlyHint is True}
    assert acting == _ACTING_TOOLS
    assert reading == _READING_TOOLS
    for name in set(tools) - _ACTING_TOOLS - _READING_TOOLS:
        assert (tools[name].readOnlyHint, tools[name].destructiveHint) == (
            False,
            False,
        ), name
    assert flows.EDIT_MODE_TOOLS <= set(tools) - _READING_TOOLS


async def test_the_model_reads_each_tool_description_without_the_codes_indentation():
    # The descriptions reach the model in every round; indentation is only
    # the source's layout.
    for tool in await flows.mcp.list_tools():
        description = tool.description or ""
        assert description.strip(), tool.name
        assert "\n " not in description, tool.name


# --- Settings keep what the change leaves out ---------------------------------


_SAVED_METADATA = {
    "form_schema": {"fields": [{"name": "kommun", "type": "text"}]},
    "wizard": {"transcription_enabled": True},
    "evidence_export": {"enabled": True},
}


def _settings_chat(monkeypatch):
    """A chat in edit mode over a flow saved with ``_SAVED_METADATA``."""
    container = _transaction_container([])
    chat = SimpleNamespace(flow_id=uuid4(), space_id=uuid4(), editing=True)
    monkeypatch.setattr(flows, "internal_tool_context", _tool_context(container))
    monkeypatch.setattr(
        flow_authoring_chat, "load_authoring_chat", AsyncMock(return_value=chat)
    )
    monkeypatch.setattr(flow_authoring_chat, "require_authoring_edit", AsyncMock())
    monkeypatch.setattr(
        flow_authoring_operations,
        "get_flow",
        AsyncMock(
            return_value=SimpleNamespace(steps=[], metadata_json=_SAVED_METADATA)
        ),
    )
    save = AsyncMock(return_value=SimpleNamespace(steps=[], draft_revision=5))
    monkeypatch.setattr(flow_authoring_operations, "apply_editor_update", save)
    return save


async def test_update_flow_settings_merges_metadata_over_the_saved_one(monkeypatch):
    save = _settings_chat(monkeypatch)
    form = {"fields": [{"name": "ort", "type": "text"}]}

    result = await flows.update_flow_settings(
        MagicMock(),
        expected_revision=4,
        changes={
            "metadata_json": {"form_schema": form, "evidence_export": None},
            "form_field_renames": {"kommun": "ort"},
        },
    )

    assert result.isError is not True, result.content[0].text
    definition = save.await_args.args[2].definition
    # The key sent replaces its saved value, the one sent as null is
    # removed, and the one left out is kept.
    assert definition.metadata_json == {
        "form_schema": form,
        "wizard": {"transcription_enabled": True},
    }
    assert definition.form_field_renames == {"kommun": "ort"}
    assert save.await_args.kwargs["audit_context"] == {"origin": "authoring_chat"}


async def test_update_flow_settings_without_metadata_leaves_it_unsent(monkeypatch):
    save = _settings_chat(monkeypatch)

    await flows.update_flow_settings(
        MagicMock(), expected_revision=4, changes={"description": "Ny"}
    )

    definition = save.await_args.args[2].definition
    assert "metadata_json" not in definition.model_fields_set
    assert definition.description == "Ny"


async def test_update_steps_merges_its_settings_metadata_the_same_way(monkeypatch):
    save = _settings_chat(monkeypatch)

    result = await flows.update_steps(
        MagicMock(),
        expected_revision=4,
        edits=[],
        settings={"metadata_json": {"wizard": {"transcription_enabled": False}}},
    )

    assert result.isError is not True, result.content[0].text
    assert save.await_args.args[2].definition.metadata_json == {
        **_SAVED_METADATA,
        "wizard": {"transcription_enabled": False},
    }
    assert save.await_args.kwargs["audit_context"] == {"origin": "authoring_chat"}


# --- Which kinds may stand at a place -----------------------------------------


def _kinds_chat(monkeypatch, flow):
    from eneo.flows.api import flow_definition_access

    container = _transaction_container([])
    container.flow_service.return_value.get_flow_assistant_prompts = AsyncMock(
        return_value={}
    )
    chat = SimpleNamespace(flow_id=flow.id, space_id=uuid4(), editing=False)
    monkeypatch.setattr(flows, "internal_tool_context", _tool_context(container))
    monkeypatch.setattr(
        flow_authoring_chat, "load_authoring_chat", AsyncMock(return_value=chat)
    )
    monkeypatch.setattr(
        flow_definition_access,
        "require_flow_current_definition_access",
        AsyncMock(return_value=SimpleNamespace(flow=flow)),
    )


async def test_read_step_kinds_says_which_kinds_may_stand_first_and_why_not(
    monkeypatch,
):
    from tests.unit.flows.application.test_flow_step_kinds import _flow, _step

    flow = _flow([_step(1), _step(2)])
    _kinds_chat(monkeypatch, flow)

    result = await flows.read_step_kinds(MagicMock(), position=1)

    assert result.isError is not True, result.content[0].text
    page = json.loads(result.content[0].text)
    assert page["next_offset"] is None
    assert page["draft_revision"] == flow.draft_revision
    answer = json.loads(page["content"])
    assert answer["position"] == 1
    kinds = {item["kind"]: item for item in answer["kinds"]}
    assert list(kinds) == [kind.value for kind in flows.FlowStepKind]
    transcribe = kinds["transcribe"]
    assert transcribe["allowed"] is True
    assert transcribe["gives"] == "text"
    assert "review" not in transcribe
    assert transcribe["hand_over"] == [
        {"step_order": 2, "changes": {"input_source": "previous_step"}}
    ]
    review = kinds["review"]
    assert review["allowed"] is False
    assert review["refusals"][0]["code"] == "typed_io_invalid_input_source_position"
    assert review["review"] is True
    assert kinds["structured"]["needs"] == ["instruction", "example"]
    assert "upload" in kinds["structured"]["may_take"]
    # Allowed here is not saved: the space's checks come with the save.
    assert "checked when the step is saved" in answer["note"]


async def test_read_step_kinds_reads_after_the_last_step_by_default(monkeypatch):
    from tests.unit.flows.application.test_flow_step_kinds import _flow, _step

    _kinds_chat(monkeypatch, _flow([_step(1)]))

    result = await flows.read_step_kinds(MagicMock())

    answer = json.loads(json.loads(result.content[0].text)["content"])
    assert answer["position"] == 2
    kinds = {item["kind"]: item for item in answer["kinds"]}
    assert kinds["send_http"]["allowed"] is True
    assert kinds["transcribe"]["allowed"] is False


async def test_read_step_kinds_refuses_a_place_the_flow_lacks(monkeypatch):
    from tests.unit.flows.application.test_flow_step_kinds import _flow, _step

    _kinds_chat(monkeypatch, _flow([_step(1)]))

    result = await flows.read_step_kinds(MagicMock(), position=3)

    assert result.isError is True
    assert "position must be between 1 and 2" in result.content[0].text


@pytest.mark.parametrize("draft", ["already broken", "published"])
async def test_a_long_step_kinds_answer_is_read_page_by_page(monkeypatch, draft):
    from tests.unit.flows.application.test_flow_step_kinds import DRAFTS

    flow, _ = DRAFTS[draft]()
    _kinds_chat(monkeypatch, flow)
    monkeypatch.setattr(flows, "default_page_cap", lambda: 2000)

    content, offset = "", 0
    while offset is not None:
        result = await flows.read_step_kinds(MagicMock(), position=1, offset=offset)
        assert result.isError is not True, result.content[0].text
        page = json.loads(result.content[0].text)
        assert len(result.content[0].text) <= 2000
        content += page["content"]
        offset = page["next_offset"]

    kinds = json.loads(content)["kinds"]
    assert len(kinds) == len(flows.FlowStepKind)
    if draft == "published":
        assert not any(item["allowed"] for item in kinds)
