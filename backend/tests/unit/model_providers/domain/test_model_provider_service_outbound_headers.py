"""The outbound header preview reports why the headers would block a user."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from eneo.model_providers.domain.model_provider_service import ModelProviderService
from eneo.model_providers.domain.outbound_headers import MAX_RESOLVED_VALUE_BYTES


def _stored(name: str, value: str, **kwargs: Any) -> dict[str, Any]:
    return {"id": name, "name": name, "value": value, "secret": False, **kwargs}


def _service(stored: list[dict[str, Any]]) -> ModelProviderService:
    repository = AsyncMock()
    repository.get_by_id.return_value = SimpleNamespace(outbound_headers=stored)
    service = ModelProviderService(repository=repository, encryption=MagicMock())
    service._header_destination_problem = MagicMock(return_value=None)  # type: ignore[method-assign]
    return service


def _user() -> Any:
    return SimpleNamespace(id="user-1", external_id=None, scim_extensions=None)


class TestPreviewBlockedReason:
    async def test_sendable_headers_have_no_reason(self):
        service = _service([_stored("Region", "eu-north")])

        _, problem, blocked, reason = await service.preview_outbound_headers(
            MagicMock(), _user()
        )

        assert (problem, blocked, reason) == (None, False, None)

    async def test_total_size_is_reported_although_no_single_header_is_at_fault(
        self,
    ):
        # Each value is within the per-header bound; only their sum is not.
        value = "a" * (MAX_RESOLVED_VALUE_BYTES - 24)
        service = _service([_stored(f"X-Part-{i}", value) for i in range(5)])

        outcomes, _, blocked, reason = await service.preview_outbound_headers(
            MagicMock(), _user()
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
        service = _service([stored])

        _, _, blocked, reason = await service.preview_outbound_headers(
            MagicMock(), _user()
        )

        assert (blocked, reason) == (True, expected)
