from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.flow_tables import FlowSteps, FlowVersions
from eneo.flows.http_transport import (
    is_authored_config,
    unprotected_persisted_secret_fields,
)
from eneo.flows.http_transport.secret_codec import SupportsEncryption


class FlowSecretConfigSource(StrEnum):
    """Which persisted place an authored HTTP config was read from."""

    DRAFT_STEP = "flow_steps"
    PUBLISHED_VERSION = "flow_versions"


@dataclass(frozen=True, slots=True)
class FlowSecretConfigLocation:
    """Enough of a row to find the config again and decide what to do with it."""

    source: FlowSecretConfigSource
    tenant_id: UUID
    flow_id: UUID
    config_field: str
    step_order: int | None = None
    flow_version: int | None = None


@dataclass(frozen=True, slots=True)
class PersistedFlowConfig:
    location: FlowSecretConfigLocation
    config: Mapping[str, object] | None


@dataclass(frozen=True, slots=True)
class UnprotectedFlowSecret:
    location: FlowSecretConfigLocation
    secret_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FlowSecretInventory:
    """What a read-only scan found, without changing anything."""

    scanned_configs: int
    authored_http_configs: int
    unprotected: tuple[UnprotectedFlowSecret, ...]
    unreadable: tuple[FlowSecretConfigLocation, ...]

    @property
    def is_clean(self) -> bool:
        return not self.unprotected and not self.unreadable


def inventory_persisted_flow_secrets(
    configs: Iterable[PersistedFlowConfig],
    encryption_service: SupportsEncryption | None,
) -> FlowSecretInventory:
    """Report every persisted authored HTTP config holding an unprotected secret.

    A config that declares the authored HTTP shape but no longer parses is
    reported separately rather than counted as clean: nothing can be said about
    the credentials inside it, and silence would read as an all-clear.
    """
    unprotected: list[UnprotectedFlowSecret] = []
    unreadable: list[FlowSecretConfigLocation] = []
    scanned = 0
    authored = 0

    for item in configs:
        scanned += 1
        if not is_authored_config(item.config):
            continue
        authored += 1
        try:
            secret_fields = unprotected_persisted_secret_fields(
                item.config,
                encryption_service,
            )
        except ValidationError:
            unreadable.append(item.location)
            continue
        if secret_fields:
            unprotected.append(
                UnprotectedFlowSecret(
                    location=item.location,
                    secret_fields=secret_fields,
                )
            )

    return FlowSecretInventory(
        scanned_configs=scanned,
        authored_http_configs=authored,
        unprotected=tuple(unprotected),
        unreadable=tuple(unreadable),
    )


def _config_payload(value: object) -> Mapping[str, object] | None:
    return cast(Mapping[str, object], value) if isinstance(value, dict) else None


def _published_step_order(step: Mapping[str, object]) -> int | None:
    step_order = step.get("step_order")
    if isinstance(step_order, int) and not isinstance(step_order, bool):
        return step_order
    return None


def _draft_step_configs(
    rows: Iterable[
        tuple[UUID, UUID, int, dict[str, Any] | None, dict[str, Any] | None]
    ],
) -> list[PersistedFlowConfig]:
    configs: list[PersistedFlowConfig] = []
    for tenant_id, flow_id, step_order, input_config, output_config in rows:
        for config_field, config in (
            ("input_config", input_config),
            ("output_config", output_config),
        ):
            configs.append(
                PersistedFlowConfig(
                    location=FlowSecretConfigLocation(
                        source=FlowSecretConfigSource.DRAFT_STEP,
                        tenant_id=tenant_id,
                        flow_id=flow_id,
                        config_field=config_field,
                        step_order=step_order,
                    ),
                    config=_config_payload(config),
                )
            )
    return configs


def _published_version_configs(
    rows: Iterable[tuple[UUID, UUID, int, dict[str, Any]]],
) -> list[PersistedFlowConfig]:
    configs: list[PersistedFlowConfig] = []
    for tenant_id, flow_id, version, definition_json in rows:
        raw_steps = definition_json.get("steps")
        if not isinstance(raw_steps, list):
            continue
        for raw_step in cast(list[object], raw_steps):
            if not isinstance(raw_step, dict):
                continue
            step = cast(Mapping[str, object], raw_step)
            for config_field in ("input_config", "output_config"):
                configs.append(
                    PersistedFlowConfig(
                        location=FlowSecretConfigLocation(
                            source=FlowSecretConfigSource.PUBLISHED_VERSION,
                            tenant_id=tenant_id,
                            flow_id=flow_id,
                            config_field=config_field,
                            step_order=_published_step_order(step),
                            flow_version=version,
                        ),
                        config=_config_payload(step.get(config_field)),
                    )
                )
    return configs


async def read_persisted_flow_configs(
    session: AsyncSession,
) -> list[PersistedFlowConfig]:
    """Read every persisted step config, draft and published, without writing.

    Both places are scanned because publishing copies a draft step into an
    immutable version: fixing only the draft would leave the same credential
    readable in every version already published from it.
    """
    step_stmt = sa.select(
        FlowSteps.tenant_id,
        FlowSteps.flow_id,
        FlowSteps.step_order,
        FlowSteps.input_config,
        FlowSteps.output_config,
    ).order_by(FlowSteps.tenant_id, FlowSteps.flow_id, FlowSteps.step_order)
    version_stmt = sa.select(
        FlowVersions.tenant_id,
        FlowVersions.flow_id,
        FlowVersions.version,
        FlowVersions.definition_json,
    ).order_by(FlowVersions.tenant_id, FlowVersions.flow_id, FlowVersions.version)

    step_rows = (await session.execute(step_stmt)).tuples().all()
    version_rows = (await session.execute(version_stmt)).tuples().all()
    return _draft_step_configs(step_rows) + _published_version_configs(version_rows)


async def inventory_unprotected_flow_secrets(
    session: AsyncSession,
    encryption_service: SupportsEncryption | None,
) -> FlowSecretInventory:
    """Inventory unprotected stored HTTP credentials across all tenants."""
    return inventory_persisted_flow_secrets(
        await read_persisted_flow_configs(session),
        encryption_service,
    )
