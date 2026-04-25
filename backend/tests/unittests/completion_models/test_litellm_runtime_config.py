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
