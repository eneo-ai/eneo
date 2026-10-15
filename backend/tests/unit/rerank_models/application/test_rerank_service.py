"""Resolving the installation's default reranker into a spec.

The spec is built only when the tenant has an enabled default rerank model
and the space's security classification allows it; everything else is
``None``, which makes semantic search run today's path.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from eneo.rerank_models.application import rerank_service as service_module
from eneo.rerank_models.application.rerank_service import RerankService


def _model(**overrides) -> MagicMock:
    model = MagicMock()
    model.id = uuid4()
    model.name = "rerank-v3.5"
    model.provider_id = uuid4()
    model.is_org_default = True
    model.can_access = True
    model.security_classification = None
    for key, value in overrides.items():
        setattr(model, key, value)
    return model


def _service(models: list[MagicMock], security_enabled: bool = False) -> RerankService:
    repo = MagicMock()
    repo.all = AsyncMock(return_value=models)
    user = MagicMock()
    user.tenant_id = uuid4()
    user.tenant = MagicMock(security_enabled=security_enabled)
    return RerankService(
        session=MagicMock(),
        user=user,
        rerank_model_repo=repo,
        encryption_service=MagicMock(),
    )


def _provider(provider_type: str = "cohere") -> MagicMock:
    provider = MagicMock()
    provider.provider_type = provider_type
    provider.create_credential_resolver.return_value = MagicMock(
        provider_type=provider_type
    )
    provider.create_outbound_headers.return_value = None
    return provider


class TestSpecForDefault:
    async def test_no_rerank_model_means_no_spec(self):
        service = _service([])

        assert await service.spec_for_default("q", None) is None

    async def test_only_an_enabled_default_counts(self):
        service = _service(
            [
                _model(is_org_default=False),
                _model(is_org_default=True, can_access=False),
            ]
        )

        assert await service.spec_for_default("q", None) is None

    async def test_builds_a_spec_from_the_default_model(self):
        model = _model()
        service = _service([_model(is_org_default=False), model])
        provider = _provider("vllm")

        with (
            patch.object(
                service_module,
                "load_active_litellm_provider",
                AsyncMock(return_value=provider),
            ) as load,
            patch.object(
                service_module,
                "build_litellm_provider_kwargs",
                return_value={"api_base": "http://reranker:8000"},
            ),
        ):
            spec = await service.spec_for_default("the question", None)

        assert spec is not None
        assert spec.query == "the question"
        assert spec.model_name == "rerank-v3.5"
        assert spec.reranker.route == "hosted_vllm/rerank-v3.5"
        assert spec.reranker.provider_kwargs == {"api_base": "http://reranker:8000"}
        assert load.await_args.kwargs["provider_id"] == model.provider_id
        assert load.await_args.kwargs["tenant_id"] == service.user.tenant_id

    async def test_classification_above_the_models_refuses(self):
        model = _model(security_classification=MagicMock(security_level=1))
        service = _service([model], security_enabled=True)
        space_classification = MagicMock()
        space_classification.is_greater_than.return_value = True

        with patch.object(service_module, "logger") as logger:
            first = await service.spec_for_default("q", space_classification)
            second = await service.spec_for_default("q", space_classification)

        assert first is None and second is None
        space_classification.is_greater_than.assert_called_with(
            model.security_classification
        )
        # Logged once per model and process, not once per search.
        assert logger.warning.call_count == 1
        assert "rerank-v3.5" in logger.warning.call_args.args

    async def test_classification_at_or_below_the_models_allows(self):
        model = _model(security_classification=MagicMock(security_level=2))
        service = _service([model], security_enabled=True)
        space_classification = MagicMock()
        space_classification.is_greater_than.return_value = False

        with (
            patch.object(
                service_module,
                "load_active_litellm_provider",
                AsyncMock(return_value=_provider()),
            ),
            patch.object(
                service_module, "build_litellm_provider_kwargs", return_value={}
            ),
        ):
            spec = await service.spec_for_default("q", space_classification)

        assert spec is not None
