"""The crawl bootstrap snapshots its embedding provider, headers included."""

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from eneo.worker.crawl_tasks import _embedding_model_spec

HEADERS = [{"id": "h1", "name": "X-Org-Unit", "value": "{{user.department}}"}]


def _model(provider_id: Any = None) -> Any:
    return SimpleNamespace(
        id=uuid4(),
        name="embed",
        litellm_model_name="stored/embed",
        family="",
        max_input=512,
        max_batch_size=None,
        dimensions=None,
        open_source=False,
        provider_id=provider_id,
    )


def _provider(*, is_active: bool = True) -> Any:
    return SimpleNamespace(
        is_active=is_active,
        provider_type="hosted_vllm",
        credentials={"api_key": "enc:fernet:v1:x"},
        config={"endpoint": "https://gateway.internal/v1"},
        outbound_headers=HEADERS,
    )


def test_an_active_provider_is_captured_with_its_headers():
    provider_id = uuid4()

    spec = _embedding_model_spec(_model(provider_id), _provider())

    assert spec.provider_id == provider_id
    assert spec.provider_type == "hosted_vllm"
    assert spec.litellm_model_name == "hosted_vllm/embed"
    assert spec.provider_config == {"endpoint": "https://gateway.internal/v1"}
    assert spec.provider_outbound_headers == HEADERS
    assert spec.family is None


def test_an_inactive_provider_captures_nothing():
    spec = _embedding_model_spec(_model(uuid4()), _provider(is_active=False))

    assert spec.provider_type is None
    assert spec.provider_credentials is None
    assert spec.provider_outbound_headers is None
    assert spec.litellm_model_name == "stored/embed"


def test_a_missing_provider_captures_nothing():
    spec = _embedding_model_spec(_model(), None)

    assert spec.provider_type is None
    assert spec.provider_outbound_headers is None
