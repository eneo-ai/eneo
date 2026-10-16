"""Bounded inspection and deliberate repair of invalid persisted model options.

Runtime factories validate ModelKwargs and may hide an invalid application.
Inspection reads raw rows, including defaults, and never changes them. Repair
requires operator-selected, validated values and an unchanged source fingerprint.
Group chats have no model options; repairing a member restores its visible seat.
"""

import hashlib
import json
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.database.tables.app_table import Apps
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.service_table import Services
from eneo.database.tables.spaces_table import Spaces
from eneo.main.exceptions import BadRequestException, NotFoundException
from eneo.main.logging import get_logger

logger = get_logger(__name__)
ResourceKind = Literal["assistant", "app", "service"]


class ConfigurationError(BaseModel):
    field: str
    code: str


def configuration_errors(value: object) -> list[ConfigurationError]:
    # NULL is a supported legacy representation of default options.
    if value is None:
        return []
    try:
        ModelKwargs.model_validate(value)
    except ValidationError as error:
        # Exclude messages and context as well as input: custom validators can
        # interpolate sensitive input into either of them.
        return [
            ConfigurationError(
                field=".".join(str(part) for part in item["loc"]), code=item["type"]
            )
            for item in error.errors(
                include_input=False, include_url=False, include_context=False
            )
        ]
    return []


def configuration_fingerprint(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class InvalidConfiguration(BaseModel):
    resource_id: UUID
    space_id: UUID
    fingerprint: str
    errors: list[ConfigurationError]


class ConfigurationInspection(BaseModel):
    tenant_id: UUID
    kind: ResourceKind
    scanned: int
    invalid: list[InvalidConfiguration]
    next_after: UUID | None


class ConfigurationRepair(BaseModel):
    expected_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    replacement: ModelKwargs
    dry_run: bool = True


class ConfigurationRepairResult(BaseModel):
    resource_id: UUID
    status: Literal["would_repair", "repaired", "unchanged"]
    fingerprint: str


class StoredModelConfigurationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def inspect(
        self, tenant_id: UUID, kind: ResourceKind, *, after: UUID | None, limit: int
    ) -> ConfigurationInspection:
        if not 1 <= limit <= 200:
            raise BadRequestException("Inspection limit must be between 1 and 200")
        model = {"assistant": Assistants, "app": Apps, "service": Services}[kind]
        query = (
            sa.select(model.id, model.space_id, model.completion_model_kwargs)
            .join(Spaces, Spaces.id == model.space_id)
            .where(Spaces.tenant_id == tenant_id)
            .order_by(model.id)
            .limit(limit + 1)
        )
        if after is not None:
            query = query.where(model.id > after)
        rows = (await self.session.execute(query)).all()
        invalid: list[InvalidConfiguration] = []
        for row in rows[:limit]:
            errors = configuration_errors(row.completion_model_kwargs)
            if errors:
                invalid.append(
                    InvalidConfiguration(
                        resource_id=row.id,
                        space_id=row.space_id,
                        fingerprint=configuration_fingerprint(
                            row.completion_model_kwargs
                        ),
                        errors=errors,
                    )
                )
        return ConfigurationInspection(
            tenant_id=tenant_id,
            kind=kind,
            scanned=min(len(rows), limit),
            invalid=invalid,
            next_after=rows[limit - 1].id if len(rows) > limit else None,
        )

    async def repair(
        self,
        tenant_id: UUID,
        kind: ResourceKind,
        resource_id: UUID,
        request: ConfigurationRepair,
    ) -> ConfigurationRepairResult:
        model = {"assistant": Assistants, "app": Apps, "service": Services}[kind]
        row = (
            await self.session.execute(
                sa.select(model.completion_model_kwargs)
                .join(
                    Spaces,
                    Spaces.id == model.space_id,
                )
                .where(model.id == resource_id, Spaces.tenant_id == tenant_id)
                .with_for_update(of=model)
            )
        ).one_or_none()
        if row is None:
            raise NotFoundException("Resource not found in tenant")
        current = row.completion_model_kwargs
        replacement = request.replacement.model_dump(mode="json")
        fingerprint = configuration_fingerprint(current)
        if current == replacement:
            return ConfigurationRepairResult(
                resource_id=resource_id, status="unchanged", fingerprint=fingerprint
            )
        if fingerprint != request.expected_fingerprint:
            raise BadRequestException(
                "Configuration changed; inspect it again before repair"
            )
        if not configuration_errors(current):
            raise BadRequestException(
                "Configuration is valid; use its normal settings endpoint"
            )
        if not request.dry_run:
            await self.session.execute(
                sa.update(model)
                .where(model.id == resource_id)
                .values(
                    completion_model_kwargs=replacement,
                )
            )
            logger.warning(
                "Repaired invalid stored model configuration",
                extra={
                    "tenant_id": str(tenant_id),
                    "resource_kind": kind,
                    "resource_id": str(resource_id),
                    "previous_fingerprint": fingerprint,
                    "replacement_fingerprint": configuration_fingerprint(replacement),
                },
            )
        return ConfigurationRepairResult(
            resource_id=resource_id,
            status="would_repair" if request.dry_run else "repaired",
            fingerprint=configuration_fingerprint(replacement),
        )
