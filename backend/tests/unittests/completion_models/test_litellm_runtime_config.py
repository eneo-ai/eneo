from __future__ import annotations

import litellm
import pytest
from litellm.exceptions import BadRequestError
from litellm.litellm_core_utils.get_llm_provider_logic import get_llm_provider

from eneo.model_providers.infrastructure.litellm_runtime_config import (
    configure_litellm_runtime,
)


def test_config_suppresses_litellm_provider_list_stdout(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(litellm, "suppress_debug_info", False)

    configure_litellm_runtime(litellm)
    with pytest.raises(BadRequestError):
        get_llm_provider(model="not-a-real-providerless-model")

    captured = capsys.readouterr()
    assert "Provider List" not in captured.out


def test_config_sets_request_timeout_and_disables_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Process defaults must not add retries or leave requests unbounded."""
    monkeypatch.setattr(litellm, "num_retries", 5, raising=False)
    monkeypatch.setattr(litellm, "request_timeout", None, raising=False)

    configure_litellm_runtime(litellm)

    assert litellm.num_retries == 0
    assert isinstance(litellm.request_timeout, (int, float))
    assert litellm.request_timeout > 0


def test_config_default_request_timeout_tracks_step_budget_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requests outside an attempt inherit the deployment step budget."""
    from eneo.main.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "flow_step_budget_seconds", 777)
    monkeypatch.setattr(litellm, "request_timeout", None, raising=False)

    configure_litellm_runtime(litellm)

    assert litellm.request_timeout == 777


@pytest.mark.asyncio
@pytest.mark.parametrize("remaining", [12.0, 7200.0])
async def test_completion_request_uses_remaining_attempt_budget(monkeypatch, remaining):
    from unittest.mock import AsyncMock

    from eneo.flows.runtime import step_deadline
    from eneo.model_providers.infrastructure import litellm_transport

    monkeypatch.setattr(step_deadline, "_now", lambda: 100.0)
    monkeypatch.setattr(litellm, "request_timeout", 3600.0)
    request = AsyncMock(return_value=object())
    monkeypatch.setattr(litellm, "acompletion", request)
    deadline = step_deadline.StepDeadline.start(remaining)
    with step_deadline.step_deadline_scope(deadline, step_order=1):
        await litellm_transport.acompletion(model="test", messages=[])
    assert request.await_args.kwargs["timeout"] == remaining
    assert litellm.request_timeout == 3600.0

    request.reset_mock()
    await litellm_transport.acompletion(model="test", messages=[])
    assert "timeout" not in request.await_args.kwargs
    assert litellm.request_timeout == 3600.0
