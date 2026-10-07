"""The outbound header preview reports why the headers would block a user."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from eneo.main.exceptions import EncryptionNotConfiguredException
from eneo.model_providers.domain.model_provider_service import ModelProviderService
from eneo.model_providers.domain.outbound_headers import MAX_RESOLVED_VALUE_BYTES


def _stored(name: str, value: str, **kwargs: Any) -> dict[str, Any]:
    return {"id": name, "name": name, "value": value, "secret": False, **kwargs}


async def _preview(
    stored: list[dict[str, Any]], encryption: Any = None
) -> tuple[Any, ...]:
    service = ModelProviderService(
        repository=AsyncMock(), encryption=encryption or MagicMock()
    )
    service._header_destination_problem = MagicMock(return_value=None)  # type: ignore[method-assign]
    provider = SimpleNamespace(outbound_headers=stored)
    return await service.preview_outbound_headers(provider, _user())  # type: ignore[arg-type]


def _user() -> Any:
    return SimpleNamespace(id="user-1", external_id=None, scim_extensions=None)


class TestPreviewBlockedReason:
    async def test_sendable_headers_have_no_reason(self):
        _, problem, blocked, reason = await _preview([_stored("Region", "eu-north")])

        assert (problem, blocked, reason) == (None, False, None)

    @pytest.mark.parametrize(
        "error",
        [
            ValueError("Decryption failed"),
            EncryptionNotConfiguredException("not configured"),
        ],
    )
    async def test_an_unreadable_secret_blocks_instead_of_failing(
        self, error: Exception
    ):
        encryption = MagicMock()
        encryption.decrypt.side_effect = error

        outcomes, _, blocked, reason = await _preview(
            [_stored("X-Key", "enc:fernet:v1:x", secret=True)], encryption
        )

        assert (outcomes, blocked, reason) == ([], True, "decryption_failed")

    async def test_total_size_is_reported_although_no_single_header_is_at_fault(
        self,
    ):
        # Each value is within the per-header bound; only their sum is not.
        value = "a" * (MAX_RESOLVED_VALUE_BYTES - 24)

        outcomes, _, blocked, reason = await _preview(
            [_stored(f"X-Part-{i}", value) for i in range(5)]
        )

        assert {outcome.state for outcome in outcomes} == {"resolved"}
        assert (blocked, reason) == (True, "total_size_exceeded")

    @pytest.mark.parametrize(
        ("stored", "expected"),
        [
            (
                _stored("X-Org-Unit", "{{user.department}}", on_missing="fail"),
                "missing_required_value",
            ),
            (_stored("X-Note", "line\nbreak"), "control_character"),
        ],
    )
    async def test_header_reasons_are_passed_through(
        self, stored: dict[str, Any], expected: str
    ):
        _, _, blocked, reason = await _preview([stored])

        assert (blocked, reason) == (True, expected)
