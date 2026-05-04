from __future__ import annotations

import litellm
import pytest
from litellm.exceptions import BadRequestError
from litellm.litellm_core_utils.get_llm_provider_logic import get_llm_provider

from intric.model_providers.infrastructure.litellm_runtime_config import (
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
    """LiteLLM-internal retries must not blow the asyncio.wait_for budget.

    The flow runtime wraps `assistant.get_response` in asyncio.wait_for at
    `flow_llm_request_timeout_seconds` (default 600s). LiteLLM's default
    `num_retries` is 0 today but is not part of its public contract; we
    pin it to 0 so a future bump cannot silently turn one slow call into
    several. We also surface `request_timeout` so the underlying HTTP
    layer aborts in line with the asyncio budget rather than relying on
    LiteLLM's internal default.
    """
    monkeypatch.setattr(litellm, "num_retries", 5, raising=False)
    monkeypatch.setattr(litellm, "request_timeout", None, raising=False)

    configure_litellm_runtime(litellm)

    assert litellm.num_retries == 0
    assert isinstance(litellm.request_timeout, (int, float))
    assert litellm.request_timeout > 0


def test_config_default_request_timeout_tracks_flow_llm_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default request_timeout must follow the flow runtime setting.

    Two timeouts that should always agree (the LiteLLM HTTP timeout and
    the asyncio.wait_for budget) drifted in earlier versions because the
    LiteLLM side was a hardcoded 600s while the flow side was
    `settings.flow_llm_request_timeout_seconds`. The default arm of
    `configure_litellm_runtime` must read the setting so an operator
    bumping `FLOW_LLM_REQUEST_TIMEOUT_SECONDS` to e.g. 900 propagates
    to LiteLLM without code changes.
    """
    from intric.main.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "flow_llm_request_timeout_seconds", 777)
    monkeypatch.setattr(litellm, "request_timeout", None, raising=False)

    configure_litellm_runtime(litellm)

    assert litellm.request_timeout == 777
