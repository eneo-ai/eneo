import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.flows.application import flow_authoring_chat, flow_authoring_operations
from eneo.internal_mcp import flows
from eneo.internal_mcp.foundation import ToolContext
from eneo.main.exceptions import BadRequestException


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
        raise BadRequestException("stale", code="stale_revision")

    result = await flows._call(MagicMock(), operation, editing=True)
    assert order == ["write", "rollback"]
    assert result.isError is True
    assert json.loads(result.content[0].text)["code"] == "stale_revision"
    assert load.await_args.kwargs["lock"] is True


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
):
    """A chat in edit mode whose update_step saves the draft from ``before``
    to ``after`` (the step 2 prompt); ``fail`` breaks the analysis, and
    ``dismissed`` are the flow's dismissals by fingerprint."""
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
    drafts = [_draft(before), _draft(after)]
    service = container.flow_service.return_value
    service.get_flow = AsyncMock(side_effect=[flow for flow, _ in drafts])
    service.get_flow_assistant_prompts = (
        AsyncMock(side_effect=RuntimeError("unreadable"))
        if fail
        else AsyncMock(side_effect=[prompts for _, prompts in drafts])
    )
    saved_step = SimpleNamespace(id=_DRAFT_IDS[1], assistant_id=_DRAFT_IDS[3])
    read = MagicMock(id=_DRAFT_IDS[1], assistant_id=_DRAFT_IDS[3])
    read.model_dump.return_value = {}
    monkeypatch.setattr(
        flow_authoring_operations,
        "get_flow",
        AsyncMock(return_value=SimpleNamespace(steps=[read])),
    )
    save = AsyncMock(return_value=SimpleNamespace(steps=[saved_step], draft_revision=5))
    monkeypatch.setattr(flow_authoring_operations, "apply_editor_update", save)
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
        "add_step",
        "move_step",
        "remove_step",
        "apply_flow_suggestions",
    }
