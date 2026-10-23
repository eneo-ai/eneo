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


async def test_read_flow_suggestions_reports_the_drafts_suggestions_in_view_mode(
    monkeypatch,
):
    from eneo.flows.api import flow_suggestions_router
    from eneo.flows.api.flow_suggestions_models import (
        FLOW_SUGGESTIONS_EXAMPLE,
        FlowSuggestionsPublic,
    )

    chat = SimpleNamespace(flow_id=uuid4(), space_id=uuid4(), editing=False)
    monkeypatch.setattr(
        flows, "internal_tool_context", _tool_context(_transaction_container([]))
    )
    monkeypatch.setattr(
        flow_authoring_chat, "load_authoring_chat", AsyncMock(return_value=chat)
    )
    edit = AsyncMock()
    monkeypatch.setattr(flow_authoring_chat, "require_authoring_edit", edit)
    answer = FlowSuggestionsPublic.model_validate(
        {**FLOW_SUGGESTIONS_EXAMPLE, "flow_id": str(chat.flow_id)}
    )
    read = AsyncMock(return_value=answer)
    monkeypatch.setattr(flow_suggestions_router, "get_flow_suggestions", read)

    result = await flows.read_flow_suggestions(MagicMock(), offset=0)

    assert result.isError is not True
    page = json.loads(result.content[0].text)
    assert page["flow_id"] == str(chat.flow_id)
    assert page["draft_revision"] == answer.draft_revision
    assert '"code":"duplicate_read"' in page["content"]
    # A read: the tool asks the router for this chat's flow and needs no edit mode.
    assert read.await_args.kwargs["id"] == chat.flow_id
    edit.assert_not_awaited()


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
