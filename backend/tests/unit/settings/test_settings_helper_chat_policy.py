"""A change of the helper chat's organisation settings: what the request
refuses before anything is read or saved."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from eneo.settings.settings import HelperChatPolicyUpdate


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"enabled": None}, id="enabled-null"),
        pytest.param({"enabled": "kanske"}, id="enabled-not-a-boolean"),
        pytest.param({"guidance": None}, id="guidance-null"),
        pytest.param({"guidance": ["du"]}, id="guidance-not-a-string"),
        pytest.param({"guidance": "Ange\u0000källan."}, id="guidance-with-nul"),
        pytest.param({"completion_model_id": "modell"}, id="model-not-a-uuid"),
        pytest.param({"prompt": "Du är en guide."}, id="unknown-field"),
    ],
)
def test_a_setting_that_is_not_valid_is_refused(body: dict) -> None:
    with pytest.raises(ValidationError):
        HelperChatPolicyUpdate.model_validate(body)
