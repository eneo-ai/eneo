"""A service run stores its question and answer, and retention can remove
them; a log line would keep a copy that it cannot."""

import logging
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.completion_models.domain.model_kwargs_capabilities import (
    SupportedModelKwargs,
)
from eneo.services import service_protocol, service_runner
from eneo.services.service import DatastoreResult
from eneo.services.service_runner import ServiceRunner


@pytest.mark.asyncio
async def test_a_service_run_never_logs_its_answer(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        service_runner, "logger", logging.getLogger("eneo.test.service_runner")
    )
    caplog.set_level(logging.DEBUG, logger="eneo.test.service_runner")
    model = SimpleNamespace(
        id=uuid4(),
        name="model",
        vision=False,
        supported_model_kwargs=SupportedModelKwargs(),
    )
    service = SimpleNamespace(
        id=uuid4(),
        groups=[],
        completion_model=model,
        completion_model_kwargs=ModelKwargs(),
    )
    output = MagicMock()
    output.to_string.return_value = "private answer"
    output.to_value.return_value = "private answer"
    question_repo = SimpleNamespace(add=AsyncMock())
    runner = ServiceRunner(
        user=cast(Any, SimpleNamespace(tenant_id=uuid4())),
        service=cast(Any, service),
        completion_service=cast(
            Any,
            SimpleNamespace(
                get_response=AsyncMock(
                    return_value=SimpleNamespace(
                        completion=SimpleNamespace(text="private answer"),
                        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2),
                    )
                )
            ),
        ),
        file_service=cast(
            Any, SimpleNamespace(get_files_by_ids=AsyncMock(return_value=[]))
        ),
        output_parser=cast(Any, SimpleNamespace(parse=lambda _: output)),
        references_service=cast(
            Any,
            SimpleNamespace(
                get_references=AsyncMock(
                    return_value=DatastoreResult(
                        chunks=[], no_duplicate_chunks=[], info_blobs=[]
                    )
                )
            ),
        ),
        question_repo=cast(Any, question_repo),
        prompt="",
    )

    result = await runner.run("private question")

    assert result.result == "private answer"
    question_repo.add.assert_awaited_once()
    assert caplog.records
    assert "private answer" not in caplog.text
    assert "private question" not in caplog.text


def test_reading_a_run_whose_answer_is_not_json_never_logs_the_answer(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """GET /services/{id}/runs/ reads every run through `to_question`, so a
    plain-text answer would be logged on every read."""
    monkeypatch.setattr(
        service_protocol, "logger", logging.getLogger("eneo.test.service_protocol")
    )
    monkeypatch.setattr(
        service_protocol,
        "CompletionModelPublic",
        SimpleNamespace(from_domain=lambda model, show_pricing: model),
    )
    monkeypatch.setattr(
        service_protocol, "ServiceRun", lambda **fields: SimpleNamespace(**fields)
    )
    caplog.set_level(logging.DEBUG, logger="eneo.test.service_protocol")
    question = SimpleNamespace(
        id=uuid4(), question="private question", answer="private answer", info_blobs=[]
    )
    service = SimpleNamespace(completion_model=SimpleNamespace(id=uuid4()))

    run = service_protocol.to_question(cast(Any, question), cast(Any, service))

    assert run.output == "private answer"
    assert str(question.id) in caplog.text
    assert "private answer" not in caplog.text
    assert "private question" not in caplog.text
