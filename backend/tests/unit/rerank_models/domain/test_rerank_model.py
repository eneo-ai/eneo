"""The rerank model entity and its public shape."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from eneo.rerank_models.domain.rerank_model import RerankModel
from eneo.rerank_models.presentation.rerank_model_models import RerankModelPublic


def _db_row(**overrides):
    now = datetime.now(timezone.utc)
    row = SimpleNamespace(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="rerank-multilingual-v3.0",
        nickname="Cohere multilingual",
        family="cohere",
        hosting="eu",
        org=None,
        stability="stable",
        open_source=None,
        description=None,
        hf_link=None,
        is_deprecated=False,
        is_enabled=True,
        is_default=False,
        security_classification=None,
        tenant_id=uuid4(),
        provider_id=uuid4(),
        candidate_factor=5,
        max_candidates=100,
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _user():
    user = MagicMock()
    user.tenant = MagicMock(security_enabled=False)
    return user


class TestCreateFromDb:
    def test_maps_columns_without_name_inversion(self):
        row = _db_row()

        model = RerankModel.create_from_db(
            row, _user(), provider_name="Cohere", provider_type="cohere"
        )

        assert model.name == "rerank-multilingual-v3.0"
        assert model.nickname == "Cohere multilingual"
        assert model.is_org_enabled is True
        assert model.is_org_default is False
        assert model.open_source is False
        assert model.provider_name == "Cohere"
        assert model.provider_type == "cohere"
        assert model.tenant_id == row.tenant_id
        assert model.provider_id == row.provider_id

    def test_public_dto_carries_the_catalog_fields(self):
        model = RerankModel.create_from_db(
            _db_row(is_default=True), _user(), provider_type="cohere"
        )

        public = RerankModelPublic.from_domain(model)

        assert public.name == "rerank-multilingual-v3.0"
        assert public.nickname == "Cohere multilingual"
        assert public.is_org_enabled is True
        assert public.is_org_default is True
        assert public.can_access is True
        assert public.provider_type == "cohere"
        assert public.security_classification is None

    def test_carries_candidate_factor_and_cap_to_the_public_dto(self):
        model = RerankModel.create_from_db(
            _db_row(candidate_factor=3, max_candidates=250), _user()
        )

        assert (model.candidate_factor, model.max_candidates) == (3, 250)
        public = RerankModelPublic.from_domain(model)
        assert (public.candidate_factor, public.max_candidates) == (3, 250)

    def test_disabled_model_cannot_be_accessed(self):
        model = RerankModel.create_from_db(_db_row(is_enabled=False), _user())

        assert RerankModelPublic.from_domain(model).can_access is False
