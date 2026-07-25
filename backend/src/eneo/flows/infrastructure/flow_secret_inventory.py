from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import cast
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

DEFAULT_SAMPLE_LIMIT = 50
_ROW_BATCH_SIZE = 200


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
    config_field: str | None = None
    step_order: int | None = None
    flow_version: int | None = None


@dataclass(frozen=True, slots=True)
class PersistedFlowConfig:
    """One persisted config, or a row whose envelope could not be read at all."""

    location: FlowSecretConfigLocation
    config: Mapping[str, object] | None = None
    envelope_unreadable: bool = False


@dataclass(frozen=True, slots=True)
class UnprotectedFlowSecret:
    location: FlowSecretConfigLocation
    secret_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FlowSecretInventory:
    """What a read-only scan found, without changing anything.

    The counts cover the whole deployment; the sample lists are capped so a
    large estate cannot be pulled into memory or printed in full. A capped
    sample never turns a dirty result clean, because `is_clean` reads counts.
    """

    scanned_configs: int
    authored_http_configs: int
    unprotected_count: int
    unreadable_count: int
    unprotected: tuple[UnprotectedFlowSecret, ...]
    unreadable: tuple[FlowSecretConfigLocation, ...]

    @property
    def is_clean(self) -> bool:
        return not self.unprotected_count and not self.unreadable_count

    @property
    def samples_truncated(self) -> bool:
        return (
            len(self.unprotected) < self.unprotected_count
            or len(self.unreadable) < self.unreadable_count
        )


class _InventoryAccumulator:
    """Folds configs into an inventory, holding counts rather than every row."""

    def __init__(
        self,
        encryption_service: SupportsEncryption | None,
        sample_limit: int,
    ) -> None:
        self._encryption_service = encryption_service
        self._sample_limit = max(sample_limit, 0)
        self._scanned = 0
        self._authored = 0
        self._unprotected_count = 0
        self._unreadable_count = 0
        self._unprotected: list[UnprotectedFlowSecret] = []
        self._unreadable: list[FlowSecretConfigLocation] = []

    def add(self, item: PersistedFlowConfig) -> None:
        if item.envelope_unreadable:
            self._record_unreadable(item.location)
            return

        self._scanned += 1
        if not is_authored_config(item.config):
            return
        self._authored += 1
        try:
            secret_fields = unprotected_persisted_secret_fields(
                item.config,
                self._encryption_service,
            )
        except ValidationError:
            self._record_unreadable(item.location)
            return
        if secret_fields:
            self._unprotected_count += 1
            if len(self._unprotected) < self._sample_limit:
                self._unprotected.append(
                    UnprotectedFlowSecret(
                        location=item.location,
                        secret_fields=secret_fields,
                    )
                )

    def _record_unreadable(self, location: FlowSecretConfigLocation) -> None:
        self._unreadable_count += 1
        if len(self._unreadable) < self._sample_limit:
            self._unreadable.append(location)

    def result(self) -> FlowSecretInventory:
        return FlowSecretInventory(
            scanned_configs=self._scanned,
            authored_http_configs=self._authored,
            unprotected_count=self._unprotected_count,
            unreadable_count=self._unreadable_count,
            unprotected=tuple(self._unprotected),
            unreadable=tuple(self._unreadable),
        )


def inventory_persisted_flow_secrets(
    configs: Iterable[PersistedFlowConfig],
    encryption_service: SupportsEncryption | None,
    *,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
) -> FlowSecretInventory:
    """Report every persisted authored HTTP config holding an unprotected secret.

    A config that declares the authored HTTP shape but no longer parses is
    reported as unreadable rather than counted as clean: nothing can be said
    about the credentials inside it, and silence would read as an all-clear.
    """
    accumulator = _InventoryAccumulator(encryption_service, sample_limit)
    for item in configs:
        accumulator.add(item)
    return accumulator.result()


def _config_item(
    location: FlowSecretConfigLocation,
    value: object,
) -> PersistedFlowConfig:
    """Classify one stored config value: absent, readable, or malformed.

    An absent config and a config that is not a JSON object are different
    facts. Collapsing the second into the first would report a column holding
    a string or an array as clean, when nothing at all can be said about it.
    """
    if value is None:
        return PersistedFlowConfig(location=location)
    if isinstance(value, dict):
        return PersistedFlowConfig(
            location=location,
            config=cast(Mapping[str, object], value),
        )
    return PersistedFlowConfig(location=location, envelope_unreadable=True)


def _published_step_order(step: Mapping[str, object]) -> int | None:
    step_order = step.get("step_order")
    if isinstance(step_order, int) and not isinstance(step_order, bool):
        return step_order
    return None


def draft_step_configs(
    *,
    tenant_id: UUID,
    flow_id: UUID,
    step_order: int,
    input_config: object,
    output_config: object,
) -> Iterable[PersistedFlowConfig]:
    """Yield both config columns of one draft step.

    The columns are typed as JSON objects, but a historical or hand-edited row
    can hold any JSON value, so the payloads are classified rather than trusted.
    """
    for config_field, config in (
        ("input_config", input_config),
        ("output_config", output_config),
    ):
        yield _config_item(
            FlowSecretConfigLocation(
                source=FlowSecretConfigSource.DRAFT_STEP,
                tenant_id=tenant_id,
                flow_id=flow_id,
                config_field=config_field,
                step_order=step_order,
            ),
            config,
        )


def published_version_configs(
    *,
    tenant_id: UUID,
    flow_id: UUID,
    version: int,
    definition_json: object,
) -> Iterable[PersistedFlowConfig]:
    """Yield the step configs inside one published definition.

    A definition whose envelope, step list or step entries are not the shape
    this snapshot format guarantees is reported as an unreadable version rather
    than skipped: an unreadable envelope can still hold credential material,
    and skipping it would report the version clean.
    """
    version_location = FlowSecretConfigLocation(
        source=FlowSecretConfigSource.PUBLISHED_VERSION,
        tenant_id=tenant_id,
        flow_id=flow_id,
        flow_version=version,
    )
    if not isinstance(definition_json, dict):
        yield PersistedFlowConfig(location=version_location, envelope_unreadable=True)
        return

    raw_steps = cast(Mapping[str, object], definition_json).get("steps")
    if not isinstance(raw_steps, list):
        yield PersistedFlowConfig(location=version_location, envelope_unreadable=True)
        return

    for raw_step in cast(list[object], raw_steps):
        if not isinstance(raw_step, dict):
            yield PersistedFlowConfig(
                location=version_location,
                envelope_unreadable=True,
            )
            continue
        step = cast(Mapping[str, object], raw_step)
        for config_field in ("input_config", "output_config"):
            yield _config_item(
                FlowSecretConfigLocation(
                    source=FlowSecretConfigSource.PUBLISHED_VERSION,
                    tenant_id=tenant_id,
                    flow_id=flow_id,
                    config_field=config_field,
                    step_order=_published_step_order(step),
                    flow_version=version,
                ),
                step.get(config_field),
            )


async def stream_persisted_flow_configs(
    session: AsyncSession,
) -> AsyncIterator[PersistedFlowConfig]:
    """Stream every persisted step config, draft and published, without writing.

    Both places are scanned because publishing copies a draft step into an
    immutable version: fixing only the draft would leave the same credential
    readable in every version already published from it. Rows are streamed in
    batches so the scan does not size with the deployment.
    """
    step_stmt = (
        sa.select(
            FlowSteps.tenant_id,
            FlowSteps.flow_id,
            FlowSteps.step_order,
            FlowSteps.input_config,
            FlowSteps.output_config,
        )
        .order_by(FlowSteps.tenant_id, FlowSteps.flow_id, FlowSteps.step_order)
        .execution_options(yield_per=_ROW_BATCH_SIZE)
    )
    step_result = await session.stream(step_stmt)
    async for (
        tenant_id,
        flow_id,
        step_order,
        input_config,
        output_config,
    ) in step_result.tuples():
        for item in draft_step_configs(
            tenant_id=tenant_id,
            flow_id=flow_id,
            step_order=step_order,
            input_config=input_config,
            output_config=output_config,
        ):
            yield item

    version_stmt = (
        sa.select(
            FlowVersions.tenant_id,
            FlowVersions.flow_id,
            FlowVersions.version,
            FlowVersions.definition_json,
        )
        .order_by(FlowVersions.tenant_id, FlowVersions.flow_id, FlowVersions.version)
        .execution_options(yield_per=_ROW_BATCH_SIZE)
    )
    version_result = await session.stream(version_stmt)
    async for tenant_id, flow_id, version, definition_json in version_result.tuples():
        for item in published_version_configs(
            tenant_id=tenant_id,
            flow_id=flow_id,
            version=version,
            definition_json=definition_json,
        ):
            yield item


async def inventory_unprotected_flow_secrets(
    session: AsyncSession,
    encryption_service: SupportsEncryption | None,
    *,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
) -> FlowSecretInventory:
    """Inventory unprotected stored HTTP credentials across all tenants."""
    accumulator = _InventoryAccumulator(encryption_service, sample_limit)
    async for item in stream_persisted_flow_configs(session):
        accumulator.add(item)
    return accumulator.result()
