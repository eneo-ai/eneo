import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.flows.application import flow_authoring_chat, flow_authoring_operations
from eneo.internal_mcp import flows
from eneo.internal_mcp.foundation import ToolContext
from eneo.main.exceptions import BadRequestException, ConflictException


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
        example='{"beslut": "Bifall", "belopp": 4500, "a.b": [], "n": null}',
    )

    assert result.isError is not True
    page = json.loads(result.content[0].text)
    body = json.loads(page["content"])
    assert body["saved"] is True
    assert body["fields"] == [
        {"name": "beslut", "type": "string", "variable": True},
        {"name": "belopp", "type": "number", "variable": True},
        {"name": "a.b", "type": "array", "variable": False},
        {"name": "n", "type": ["string", "null"], "variable": True},
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
    ]
    # The contract carries the fields' types, never the example's values.
    assert "Bifall" not in json.dumps(request.model_dump(mode="json"))


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


# --- Reading the flow by section ---------------------------------------------


_STEP_2_PROMPT = "Sammanfatta {{ step_1.output.text }}."


def _reading_chat(monkeypatch):
    """A view-mode chat over the example flow: step 2 reads step 1 as its
    input and again in its prompt."""
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
