from __future__ import annotations

from typing import Any, cast
from unittest.mock import Mock
from uuid import uuid4

import pytest

from eneo.model_providers.infrastructure import tenant_model_credential_resolver
from eneo.model_providers.infrastructure.tenant_model_credential_resolver import (
    TenantModelCredentialResolver,
)


def _resolver(
    *,
    credentials: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> TenantModelCredentialResolver:
    return TenantModelCredentialResolver(
        provider_id=uuid4(),
        provider_type="openai",
        credentials=credentials or {},
        config=config or {},
        encryption_service=cast(Any, None),
    )


def test_missing_optional_field_without_fallback_does_not_log_noise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = _resolver()
    debug = Mock()
    monkeypatch.setattr(tenant_model_credential_resolver.logger, "debug", debug)

    assert resolver.get_credential_field(field="api_version") is None

    debug.assert_not_called()


def test_missing_optional_field_with_fallback_logs_fallback_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = _resolver()
    debug = Mock()
    monkeypatch.setattr(tenant_model_credential_resolver.logger, "debug", debug)

    assert (
        resolver.get_credential_field(field="endpoint", fallback="https://example")
        == "https://example"
    )

    debug.assert_called_once()
    assert "Field 'endpoint' not found" in debug.call_args.args[0]
