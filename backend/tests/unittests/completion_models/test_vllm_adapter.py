"""Unit tests for the legacy VLLM adapter handling tenant credentials."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from intric.completion_models.infrastructure.adapters import vllm_model_adapter
from intric.completion_models.infrastructure.adapters.vllm_model_adapter import (
    VLMMModelAdapter,
)
from intric.settings.credential_resolver import CredentialResolver
from intric.tenants.tenant import TenantInDB, TenantState


class DummyAsyncOpenAI:
    """Capture init parameters without performing any network calls."""

    def __init__(self, *args, **kwargs):  # noqa: D401, ARG002
        self.base_url = kwargs.get("base_url")
        self.api_key = kwargs.get("api_key")


def make_settings(**overrides):
    defaults = {
        "tenant_credentials_enabled": True,
        "vllm_api_key": "global-key",
        "vllm_model_url": "http://global-vllm:8000",
        "openai_api_key": None,
        "anthropic_api_key": None,
        "azure_api_key": None,
        "berget_api_key": None,
        "mistral_api_key": None,
        "ovhcloud_api_key": None,
        "federation_per_tenant_enabled": False,
        "public_origin": "https://global.example.com",
        "oidc_discovery_endpoint": None,
        "oidc_client_secret": None,
        "oidc_client_id": None,
        "oidc_tenant_id": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def make_tenant(api_credentials):
    return TenantInDB(
        id=uuid4(),
        name="Tenant",
        display_name="Tenant",
        quota_limit=1024**3,
        slug="tenant",
        state=TenantState.ACTIVE,
        modules=[],
        api_credentials=api_credentials,
        federation_config={},
    )


def make_model(base_url=None):
    return SimpleNamespace(token_limit=8000, base_url=base_url)


@pytest.mark.asyncio
async def test_vllm_adapter_uses_tenant_credentials(monkeypatch):
    settings = make_settings(tenant_credentials_enabled=True)
    tenant = make_tenant({"vllm": {"api_key": "tenant-key", "endpoint": "http://tenant-vllm:8000"}})
    resolver = CredentialResolver(tenant=tenant, settings=settings, encryption_service=None)

    monkeypatch.setattr(vllm_model_adapter, "get_settings", lambda: settings)
    created_clients = []

    def factory(*args, **kwargs):
        client = DummyAsyncOpenAI(*args, **kwargs)
        created_clients.append(client)
        return client

    monkeypatch.setattr(vllm_model_adapter, "AsyncOpenAI", factory)

    adapter = VLMMModelAdapter(model=make_model(), credential_resolver=resolver)

    assert adapter.extra_headers == {"X-API-Key": "tenant-key"}
    assert created_clients[0].base_url == "http://tenant-vllm:8000"


@pytest.mark.asyncio
async def test_vllm_adapter_requires_endpoint_in_strict_mode(monkeypatch):
    settings = make_settings(tenant_credentials_enabled=True)
    tenant = make_tenant({"vllm": {"api_key": "tenant-key"}})
    resolver = CredentialResolver(tenant=tenant, settings=settings, encryption_service=None)

    monkeypatch.setattr(vllm_model_adapter, "get_settings", lambda: settings)

    with pytest.raises(ValueError) as exc:
        VLMMModelAdapter(model=make_model(), credential_resolver=resolver)

    assert "endpoint" in str(exc.value)


@pytest.mark.asyncio
async def test_vllm_adapter_falls_back_to_global_single_tenant(monkeypatch):
    settings = make_settings(tenant_credentials_enabled=False)
    monkeypatch.setattr(vllm_model_adapter, "get_settings", lambda: settings)
    created_clients = []

    def factory(*args, **kwargs):
        client = DummyAsyncOpenAI(*args, **kwargs)
        created_clients.append(client)
        return client

    monkeypatch.setattr(vllm_model_adapter, "AsyncOpenAI", factory)

    adapter = VLMMModelAdapter(model=make_model(), credential_resolver=None)

    assert adapter.extra_headers == {"X-API-Key": "global-key"}
    assert created_clients[0].base_url == "http://global-vllm:8000"
