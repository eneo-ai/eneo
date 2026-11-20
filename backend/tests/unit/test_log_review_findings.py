"""Faults a review of a deployment's logs turned up, each pinned once fixed.

One file because the faults are unrelated and small: what they share is how
they were found. A fault with a home of its own (the tool loop's limits) is
tested there instead.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import anyio
import pytest
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from eneo.ai_models.completion_models.completion_model import TokenUsage
from eneo.audit.application import audit_worker_task
from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ALWAYS_AUDITED_ACTIONS, ActionType
from eneo.audit.domain.json_metadata import json_metadata
from eneo.completion_models.infrastructure.adapters.tenant_model_adapter import (
    TenantModelAdapter,
)
from eneo.conversations import conversations_router
from eneo.conversations.conversation_models import ConversationRequest
from eneo.database import database
from eneo.database.database import DatabaseSessionManager
from eneo.main.config import get_settings
from eneo.main.logging import OTELJSONFormatter
from eneo.server.middleware import request_context
from eneo.server.middleware.request_context import RequestContextMiddleware
from eneo.worker.worker import _log_arq_records_once


@contextmanager
def _logs_of(
    module: ModuleType, caplog: pytest.LogCaptureFixture, level: int
) -> Iterator[None]:
    # Eneo's module loggers carry their own handler and do not propagate.
    logger: logging.Logger = module.logger
    previous = logger.level
    logger.addHandler(caplog.handler)
    logger.setLevel(level)
    try:
        yield
    finally:
        logger.removeHandler(caplog.handler)
        logger.setLevel(previous)


# --- chat version 3 --------------------------------------------------------


@pytest.mark.parametrize(("api_version", "answering"), [(1, 1), (2, 2), (3, 2)])
def test_chat_version_3_answers_as_version_2(api_version: int, answering: int):
    assert conversations_router._answering_version(api_version) == answering


@pytest.mark.asyncio
async def test_a_version_3_chat_reaches_the_services_as_version_2():
    # Version 3 differs from 2 in how the stream is framed. The services below
    # the router branch on 1 and 2 only; handed a 3, retrieval raised and an
    # assistant with knowledge answered every such chat with a 500.
    conversation_service = SimpleNamespace(
        ask_conversation=AsyncMock(return_value="the-response")
    )

    @asynccontextmanager
    async def begin():
        yield

    container = SimpleNamespace(
        session=lambda: SimpleNamespace(begin=begin),
        conversation_service=lambda: conversation_service,
    )
    http_request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/conversations/",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "query_string": b"",
        }
    )

    with (
        patch.object(conversations_router, "_validate_conversation_scope", AsyncMock()),
        patch.object(
            conversations_router,
            "to_ui_message_stream_response",
            return_value="framed-as-version-3",
        ) as framed,
    ):
        response = await conversations_router.chat(
            request=ConversationRequest(
                question="hello", assistant_id=uuid4(), stream=True
            ),
            http_request=http_request,
            version=3,
            container=container,  # type: ignore[arg-type]
        )

    assert conversation_service.ask_conversation.await_args.kwargs["version"] == 2
    assert response == "framed-as-version-3"
    assert framed.call_args.kwargs["response"] == "the-response"


# --- audit metadata --------------------------------------------------------


class _Colour(Enum):
    RED = "red"


class _Permissions(BaseModel):
    assistants: str = "read"
    granted_at: datetime | None = None


def test_audit_metadata_becomes_json_whatever_the_caller_put_in_it():
    # An API key's expiry change put two datetimes in `changes`, and a
    # permission change a model. The event is pickled to the worker, so they
    # arrived unchanged at the JSONB insert, which raised and lost the event.
    moment = datetime(2026, 11, 17, 12, 12, 8, tzinfo=timezone.utc)
    identifier = UUID("07509b64-a4be-4436-8943-9613c8ab4b57")

    stored = json_metadata(
        {
            "changes": {
                "expires_at": {"old": None, "new": moment},
                "resource_permissions": {
                    "old": None,
                    "new": _Permissions(granted_at=moment),
                },
            },
            "extra": {
                "id": identifier,
                "colour": _Colour.RED,
                "amount": Decimal("1.50"),
                "tags": {"a"},
                "raw": b"\xff\x00",
                "opaque": object,
            },
        }
    )

    import json

    json.dumps(stored)  # every value is one the column's encoder accepts
    assert stored["changes"]["expires_at"]["new"] == "2026-11-17T12:12:08Z"
    assert stored["changes"]["resource_permissions"]["new"] == {
        "assistants": "read",
        "granted_at": "2026-11-17T12:12:08Z",
    }
    assert stored["extra"]["id"] == str(identifier)
    assert stored["extra"]["colour"] == "red"
    assert stored["extra"]["tags"] == ["a"]


def test_audit_metadata_that_is_already_json_is_unchanged():
    metadata = {"actor": {"id": "1"}, "changes": {"name": {"old": "a", "new": "b"}}}

    assert json_metadata(metadata) == metadata


class _Session:
    def __init__(self, *, in_transaction: bool) -> None:
        self._in_transaction = in_transaction
        self.transactions_opened = 0

    def in_transaction(self) -> bool:
        return self._in_transaction

    @asynccontextmanager
    async def begin(self):
        self.transactions_opened += 1
        self._in_transaction = True
        try:
            yield
        finally:
            self._in_transaction = False


def _configurable_action() -> ActionType:
    return next(a for a in ActionType if a not in ALWAYS_AUDITED_ACTIONS)


@pytest.mark.asyncio
async def test_the_audit_settings_are_read_in_a_transaction_when_none_is_open():
    # A streamed answer logs events after the request's transaction closed.
    # With autobegin off the settings read then failed ("Autobegin is disabled
    # on this Session") and the event was logged whatever the tenant had set.
    session = _Session(in_transaction=False)
    read_inside_transaction: list[bool] = []

    async def is_action_enabled(tenant_id: UUID, action: str) -> bool:
        del tenant_id, action
        read_inside_transaction.append(session.in_transaction())
        return False

    service = AuditService(
        repository=AsyncMock(),
        audit_config_service=SimpleNamespace(is_action_enabled=is_action_enabled),  # type: ignore[arg-type]
        session=session,  # type: ignore[arg-type]
    )

    assert await service._should_log_action(uuid4(), _configurable_action()) is False
    assert read_inside_transaction == [True]
    assert session.transactions_opened == 1


@pytest.mark.asyncio
async def test_the_audit_settings_read_joins_a_transaction_that_is_open():
    session = _Session(in_transaction=True)
    service = AuditService(
        repository=AsyncMock(),
        audit_config_service=SimpleNamespace(
            is_action_enabled=AsyncMock(return_value=True)
        ),  # type: ignore[arg-type]
        session=session,  # type: ignore[arg-type]
    )

    assert await service._should_log_action(uuid4(), _configurable_action()) is True
    assert session.transactions_opened == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("actor_was_deleted", [False, True])
async def test_a_lost_audit_event_is_logged_with_its_action(
    caplog: pytest.LogCaptureFixture,
    actor_was_deleted: bool,
):
    # The job is not retried and the worker's own lines carry only a job id,
    # so nothing said which event a failed insert lost.
    failures: list[Exception] = [RuntimeError("insert failed")]
    if actor_was_deleted:
        failures.insert(
            0, IntegrityError(None, None, RuntimeError("audit_logs_actor_id_fkey"))
        )
    failing_insert = AsyncMock(side_effect=failures)

    params = {
        "tenant_id": str(uuid4()),
        "actor_id": str(uuid4()),
        "actor_api_key_id": None,
        "actor_type": "user",
        "action": "api_key_updated",
        "entity_type": "api_key",
        "entity_id": str(uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "description": "Updated an API key",
        "metadata": {},
        "outcome": "success",
        "ip_address": None,
        "user_agent": None,
        "request_id": None,
        "error_message": None,
    }

    with (
        patch.object(audit_worker_task, "_create_in_savepoint", failing_insert),
        _logs_of(audit_worker_task, caplog, logging.ERROR),
        pytest.raises(RuntimeError),
    ):
        await audit_worker_task.log_audit_event_task(
            job_id=uuid4(),
            params=params,
            session=AsyncMock(),
        )

    [record] = [r for r in caplog.records if "Audit event not stored" in r.message]
    assert failing_insert.await_count == len(failures)
    assert "action=api_key_updated" in record.message
    assert "insert failed" not in record.getMessage()


# --- logs that held what they should not -----------------------------------


@pytest.mark.parametrize("separator", ["-", "@", "%40"])
def test_database_pool_diagnostics_keep_connection_secrets_out_of_logs(
    separator: str,
    caplog: pytest.LogCaptureFixture,
):
    manager = DatabaseSessionManager()
    password = f"pool-test-left{separator}pool-test-right"
    url = f"postgresql+asyncpg://eneo:{password}@db:5432/eneo?sslkey=pool-test-option"

    with _logs_of(database, caplog, logging.DEBUG):
        manager.init(url)

    formatter = OTELJSONFormatter()
    logged = "\n".join(formatter.format(record) for record in caplog.records)
    assert manager.initialized
    assert "Database connection budget" in logged
    assert all(
        part not in logged
        for part in ("pool-test-left", "pool-test-right", "pool-test-option")
    )


def test_a_completion_request_is_logged_by_shape_not_with_its_tool_definitions():
    # A chat with MCP servers sends every tool definition on each request;
    # logged whole, one request was a line of 60 to 80 kB.
    adapter = TenantModelAdapter.__new__(TenantModelAdapter)
    tools = [
        {
            "type": "function",
            "function": {"name": f"tool_{n}", "description": "x" * 900},
        }
        for n in range(40)
    ]

    logged = adapter._get_effective_params(
        {
            "api_key": "sk-test-1234567890",
            "temperature": 0.2,
            "tools": tools,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"a": "b" * 5000},
            },
            "extra_headers": {"x-tenant": "secret-header-value"},
            "metadata": {"k": "v"},
            "dropped_param": 1,
        },
        {"dropped_param"},
    )

    assert logged == {
        "api_key": "...7890",
        "temperature": 0.2,
        "tools": "<40 tools>",
        "response_format": "<json_schema>",
        "extra_headers": {"x-tenant": "***"},
        "metadata": "<dict with 1 keys>",
    }
    assert len(str(logged)) < 300


# --- a cancelled request and its connection --------------------------------


class _SlowClosingSession:
    def __init__(self) -> None:
        self.closed = False

    async def rollback(self) -> None:
        return None

    async def close(self) -> None:
        # Handing a connection back awaits the driver; a cancelled scope
        # cancels that await unless the close is shielded.
        await anyio.sleep(0.01)
        self.closed = True


@pytest.mark.asyncio
async def test_a_cancelled_request_still_closes_its_session():
    # A client that hangs up on a stream cancels the request's scope, and
    # with it every await in the cleanup. The close stopped at its first one
    # and the connection never went back to the pool.
    manager = DatabaseSessionManager()
    session = _SlowClosingSession()
    manager._sessionmaker = lambda: session  # type: ignore[assignment]

    with anyio.CancelScope() as scope:
        async with manager.session():
            scope.cancel()
            await anyio.sleep(0)

    assert scope.cancelled_caught
    assert session.closed


async def test_session_close_deadline_is_reported(caplog, monkeypatch):
    manager = DatabaseSessionManager()
    monkeypatch.setattr(database, "_SESSION_CLOSE_BUDGET_SECONDS", 0.01)
    with (
        patch.object(
            manager,
            "_sessionmaker",
            return_value=SimpleNamespace(close=asyncio.Event().wait),
        ),
        _logs_of(database, caplog, logging.WARNING),
    ):
        async with asyncio.timeout(2), manager.session():
            pass
    assert "Closing a database session exceeded" in caplog.text


# --- a turn's estimate against its first request ---------------------------


def test_usage_keeps_the_first_request_apart_from_the_turn_total():
    # The estimate made before a turn is of its first request. Compared with
    # the total over every tool round it read as a 48 to 99 percent drift.
    first = TokenUsage(
        prompt_tokens=5_000,
        completion_tokens=100,
        context_prompt_tokens=5_000,
        context_completion_tokens=100,
        first_request_prompt_tokens=5_000,
    )
    second = TokenUsage(
        prompt_tokens=40_000,
        completion_tokens=300,
        context_prompt_tokens=40_000,
        context_completion_tokens=300,
        first_request_prompt_tokens=40_000,
    )

    turn = TenantModelAdapter._combine_usage(first, second)

    assert turn is not None
    assert turn.prompt_tokens == 45_000
    assert turn.context_prompt_tokens == 40_000
    assert turn.first_request_prompt_tokens == 5_000

    # A later request without usage leaves the first request known.
    partial = TenantModelAdapter._combine_usage(first, None)
    assert partial is not None
    assert partial.prompt_tokens is None
    assert partial.first_request_prompt_tokens == 5_000


# --- behind a reverse proxy ------------------------------------------------


def _probe_app() -> Starlette:
    async def probe(request: Request) -> PlainTextResponse:
        del request
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/probe", probe)])
    app.add_middleware(RequestContextMiddleware)
    return app


def _forwarding_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if "TRUSTED_PROXY_COUNT" in record.getMessage()
    ]


def test_an_unused_forwarding_header_is_reported_once(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
):
    # Behind a proxy with TRUSTED_PROXY_COUNT left at 0, every log line and
    # audit entry carried the proxy's address and nothing pointed at the cause.
    monkeypatch.setattr(request_context, "_untrusted_forwarding_reported", False)
    settings = get_settings().model_copy(update={"trusted_proxy_count": 0})
    monkeypatch.setattr(request_context, "get_settings", lambda: settings)

    with (
        _logs_of(request_context, caplog, logging.WARNING),
        TestClient(_probe_app()) as client,
    ):
        client.get("/probe")
        assert _forwarding_warnings(caplog) == []
        client.get("/probe", headers={"X-Forwarded-For": "203.0.113.7"})
        client.get("/probe", headers={"X-Forwarded-For": "203.0.113.8"})

    [warning] = _forwarding_warnings(caplog)
    assert "x-forwarded-for" in warning
    assert "203.0.113" not in warning


def test_a_trusted_proxy_is_not_reported(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(request_context, "_untrusted_forwarding_reported", False)
    settings = get_settings().model_copy(update={"trusted_proxy_count": 1})
    monkeypatch.setattr(request_context, "get_settings", lambda: settings)

    with (
        _logs_of(request_context, caplog, logging.WARNING),
        TestClient(_probe_app()) as client,
    ):
        client.get("/probe", headers={"X-Forwarded-For": "203.0.113.7"})

    assert _forwarding_warnings(caplog) == []


# --- worker log lines written twice ----------------------------------------


@pytest.fixture
def arq_logging():
    arq_logger = logging.getLogger("arq")
    root = logging.getLogger()
    saved = (list(arq_logger.handlers), arq_logger.propagate, list(root.handlers))
    yield arq_logger, root
    arq_logger.handlers[:], arq_logger.propagate, root.handlers[:] = saved


def _ways_out(arq_logger: logging.Logger, root: logging.Logger) -> int:
    return len(arq_logger.handlers) + (
        len(root.handlers) if arq_logger.propagate else 0
    )


def test_an_arq_record_is_written_once_when_the_root_logger_has_a_handler(arq_logging):
    arq_logger, root = arq_logging
    arq_logger.handlers[:] = [logging.NullHandler()]
    arq_logger.propagate = True
    root.handlers[:] = [logging.NullHandler()]

    _log_arq_records_once()

    assert _ways_out(arq_logger, root) == 1
    assert arq_logger.propagate


def test_an_arq_record_is_written_once_when_only_arq_has_a_handler(arq_logging):
    arq_logger, root = arq_logging
    arq_logger.handlers[:] = [logging.NullHandler()]
    arq_logger.propagate = True
    root.handlers[:] = []

    _log_arq_records_once()

    assert len(arq_logger.handlers) == 1
    assert not arq_logger.propagate


def test_arq_keeps_its_own_destination_when_propagation_is_disabled(
    arq_logging, caplog
):
    arq_logger, root = arq_logging
    arq_logger.handlers[:] = [caplog.handler]
    arq_logger.propagate = False
    root.handlers[:] = [logging.NullHandler()]
    with caplog.at_level(logging.INFO, logger="arq"):
        _log_arq_records_once()
        arq_logger.info("custom ARQ destination")
    assert [record.message for record in caplog.records] == ["custom ARQ destination"]
