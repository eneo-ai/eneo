from typing import TYPE_CHECKING, Any, Optional

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from eneo.database.tables.ai_models_table import TranscriptionModels
from eneo.database.tables.model_providers_table import ModelProviders
from eneo.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassificationDBModel,
)
from eneo.main.exceptions import NotFoundException
from eneo.transcription_models.domain.realtime import realtime_eligibility
from eneo.transcription_models.domain.transcription_model import (
    TranscriptionModel,
)

if TYPE_CHECKING:
    from uuid import UUID

    from eneo.database.database import AsyncSession
    from eneo.tenants.tenant import TenantInDB


# Only the provider facts the read models need: the live text rule reads the
# endpoint and whether outbound headers are configured. Neither the API key nor
# any header value is loaded, so listing models decrypts nothing. The endpoint
# keeps its JSON type, so the rule sees the value the provider itself holds.
_PROVIDER_FACTS = (
    ModelProviders.name,
    ModelProviders.provider_type,
    ModelProviders.credentials["endpoint"].label("credential_endpoint"),
    ModelProviders.config["endpoint"].label("config_endpoint"),
    (
        sa.case(
            (
                sa.func.jsonb_typeof(ModelProviders.outbound_headers) == "array",
                sa.func.jsonb_array_length(ModelProviders.outbound_headers),
            ),
            else_=0,
        )
        > 0
    ).label("has_outbound_headers"),
)


def _to_domain(row: "sa.Row[Any]", tenant: "TenantInDB") -> TranscriptionModel:
    transcription_model, provider_name, provider_type, *_ = row
    return TranscriptionModel.create_from_db(
        transcription_model_db=transcription_model,
        tenant=tenant,
        provider_name=provider_name,
        provider_type=provider_type,
        # A missing key and a JSON null both read as None, which the rule
        # treats as absent, as a request does; an empty credential still
        # shadows config.
        realtime_eligibility=realtime_eligibility(
            provider_type=provider_type,
            credentials={"endpoint": row.credential_endpoint},
            config={"endpoint": row.config_endpoint},
            has_outbound_headers=bool(row.has_outbound_headers),
        ),
    )


class TranscriptionModelRepository:
    def __init__(self, *, session: "AsyncSession", tenant: "TenantInDB") -> None:
        super().__init__()
        self.session = session
        self.tenant = tenant

    async def all(self, with_deprecated: bool = False):
        stmt = (
            sa.select(TranscriptionModels, *_PROVIDER_FACTS)
            .outerjoin(
                ModelProviders, TranscriptionModels.provider_id == ModelProviders.id
            )
            .options(
                selectinload(TranscriptionModels.security_classification),
                selectinload(TranscriptionModels.security_classification).options(
                    selectinload(SecurityClassificationDBModel.tenant)
                ),
            )
            .where(
                # Return both global and tenant models
                # This allows existing apps with global models to continue working
                # UI filtering happens at the presentation layer
                sa.or_(
                    TranscriptionModels.tenant_id.is_(None),
                    TranscriptionModels.tenant_id == self.tenant.id,
                ),
                # Soft-deleted models are tombstones kept only so migration
                # history and lingering app references resolve; never surface
                # them to readers.
                TranscriptionModels.deleted_at.is_(None),
            )
            .order_by(
                TranscriptionModels.org,
                TranscriptionModels.created_at,
                TranscriptionModels.name,
            )
        )

        if not with_deprecated:
            stmt = stmt.where(TranscriptionModels.is_deprecated == False)  # noqa

        result = await self.session.execute(stmt)
        rows = result.all()

        return [_to_domain(row, self.tenant) for row in rows]

    async def one_or_none(self, model_id: "UUID") -> Optional["TranscriptionModel"]:
        # When fetching by ID, return ANY model (global or tenant) that the user can access
        stmt = (
            sa.select(TranscriptionModels, *_PROVIDER_FACTS)
            .outerjoin(
                ModelProviders, TranscriptionModels.provider_id == ModelProviders.id
            )
            .options(
                selectinload(TranscriptionModels.security_classification),
                selectinload(TranscriptionModels.security_classification).options(
                    selectinload(SecurityClassificationDBModel.tenant)
                ),
            )
            .where(
                TranscriptionModels.id == model_id,
                # Allow both global models and models owned by the requesting tenant.
                sa.or_(
                    TranscriptionModels.tenant_id.is_(None),
                    TranscriptionModels.tenant_id == self.tenant.id,
                ),
                # Soft-deleted models are invisible to all callers (including the
                # migration engine, which must not migrate from/to a tombstone).
                TranscriptionModels.deleted_at.is_(None),
            )
        )

        result = await self.session.execute(stmt)
        row = result.one_or_none()

        if row is None:
            return None

        return _to_domain(row, self.tenant)

    async def one(self, model_id: "UUID") -> "TranscriptionModel":
        transcription_model = await self.one_or_none(model_id=model_id)

        if transcription_model is None:
            raise NotFoundException()

        return transcription_model

    async def update(self, transcription_model: "TranscriptionModel"):
        # Update settings directly on the model table
        stmt = (
            sa.update(TranscriptionModels)
            .values(
                is_enabled=transcription_model.is_org_enabled,
                is_default=transcription_model.is_org_default,
                security_classification_id=(
                    transcription_model.security_classification.id
                    if transcription_model.security_classification
                    else None
                ),
            )
            .where(
                TranscriptionModels.id == transcription_model.id,
                TranscriptionModels.tenant_id == self.tenant.id,
            )
        )
        await self.session.execute(stmt)

        if transcription_model.is_org_default:
            # Set all other models to not default (for this tenant)
            stmt = (
                sa.update(TranscriptionModels)
                .values(is_default=False)
                .where(
                    TranscriptionModels.id != transcription_model.id,
                    TranscriptionModels.tenant_id == self.tenant.id,
                )
            )
            await self.session.execute(stmt)
