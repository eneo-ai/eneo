"""Durable destination pairing and the store-generation write fence.

This module owns, per destination slot, the database-to-bucket binding facts
(identity, claim, creation intent, confirmation) and the transactional check
that a remote operation still acts for the destination revision its client
was built from. Slot 1 is always the active destination; slot 2 exists only
while a destination migration holds a candidate or retiring destination.
"""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.object_content_table import ObjectContents
from eneo.database.tables.object_store_binding_table import ObjectStoreBindings
from eneo.database.tables.object_store_connection_table import (
    ACTIVE_DESTINATION_SLOT,
    ObjectStoreConnections,
)
from eneo.object_content.configuration import ObjectContentSettings
from eneo.object_content.content import (
    ObjectContentBusyError,
    ObjectContentConfigurationError,
    ObjectContentUnavailableError,
    StorageKind,
)
from eneo.object_content.s3_object_store import (
    ObjectStoreBindingError,
    ObjectStoreUnavailableError,
    S3ObjectStore,
)

#: Revision reported by a destination without a stored connection row —
#: the legacy environment-managed configuration. The fence treats a missing
#: row and this revision as the same generation.
UNSTORED_CONNECTION_REVISION = 0


@dataclass(frozen=True, slots=True)
class StoreBinding:
    deployment_id: UUID
    binding_id: UUID
    confirmed: bool
    claim_id: UUID | None
    creation_started: bool


@dataclass(frozen=True, slots=True)
class StoreBindingSnapshot:
    deployment_id: UUID | None
    binding_id: UUID | None
    confirmed: bool

    @property
    def unbound(self) -> bool:
        return (
            self.deployment_id is None
            and self.binding_id is None
            and not self.confirmed
        )


async def require_store_generation(
    session: AsyncSession,
    *,
    slot: int,
    revision: int,
) -> None:
    """Fail typed unless the slot's connection revision still matches.

    Runs inside the caller's durable-intent transaction and shared-locks the
    connection row, so a concurrent credential rotation or destination
    cutover (which advances the revision under an exclusive lock) strictly
    orders against every remote intent recorded under the old generation.
    A missing row is the legacy environment-managed configuration and pairs
    with ``UNSTORED_CONNECTION_REVISION``.
    """
    current = await session.scalar(
        select(ObjectStoreConnections.revision)
        .where(ObjectStoreConnections.id == slot)
        .with_for_update(read=True)
    )
    if (current if current is not None else UNSTORED_CONNECTION_REVISION) != revision:
        raise ObjectContentUnavailableError(
            "Object-store configuration changed during the operation; try again"
        )


class StoreBindingRepository:
    """Slot-scoped persistence for durable destination binding facts."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def snapshot(
        self, *, slot: int = ACTIVE_DESTINATION_SLOT
    ) -> StoreBindingSnapshot:
        row = (
            await self._session.execute(
                select(
                    ObjectStoreBindings.deployment_id,
                    ObjectStoreBindings.binding_id,
                    ObjectStoreBindings.confirmed_at,
                ).where(ObjectStoreBindings.slot == slot)
            )
        ).one_or_none()
        if row is None:
            return StoreBindingSnapshot(
                deployment_id=None, binding_id=None, confirmed=False
            )
        deployment_id, binding_id, confirmed_at = row
        return StoreBindingSnapshot(
            deployment_id=deployment_id,
            binding_id=binding_id,
            confirmed=confirmed_at is not None,
        )

    async def get_or_initialize(
        self,
        deployment_id: UUID,
        *,
        slot: int = ACTIVE_DESTINATION_SLOT,
        claim_id: UUID,
        claim_seconds: int,
    ) -> StoreBinding:
        if claim_seconds < 1:
            raise ValueError("Store-binding claim duration must be positive")

        confirmed_row = (
            await self._session.execute(
                select(
                    ObjectStoreBindings.deployment_id,
                    ObjectStoreBindings.binding_id,
                    ObjectStoreBindings.confirmed_at,
                    ObjectStoreBindings.create_started_at,
                ).where(ObjectStoreBindings.slot == slot)
            )
        ).one_or_none()
        if confirmed_row is not None and confirmed_row[2] is not None:
            stored_deployment_id, binding_id, _, create_started_at = confirmed_row
            if stored_deployment_id != deployment_id:
                raise ObjectContentConfigurationError(
                    "Object-content deployment identity does not match PostgreSQL"
                )
            return StoreBinding(
                deployment_id=stored_deployment_id,
                binding_id=binding_id,
                confirmed=True,
                claim_id=None,
                creation_started=create_started_at is not None,
            )

        row = await self._row_for_update(slot)
        if row is None:
            if (
                slot == ACTIVE_DESTINATION_SLOT
                and await self._has_object_store_content()
            ):
                raise ObjectContentConfigurationError(
                    "Object-content storage binding is missing for existing records"
                )
            await self._session.execute(
                insert(ObjectStoreBindings)
                .values(
                    slot=slot,
                    deployment_id=deployment_id,
                    binding_id=uuid4(),
                )
                .on_conflict_do_nothing(index_elements=[ObjectStoreBindings.slot])
            )
            row = await self._row_for_update(slot)
            if row is None:
                raise RuntimeError("Object-store binding initialization failed")
        if row.deployment_id != deployment_id:
            raise ObjectContentConfigurationError(
                "Object-content deployment identity does not match PostgreSQL"
            )

        confirmed = row.confirmed_at is not None
        owns_claim = False
        if not confirmed:
            now = await self._database_now()
            claim_expired = row.claim_until is None or row.claim_until <= now
            if row.claim_id is None or claim_expired:
                row.claim_id = claim_id
                row.claim_until = now + timedelta(seconds=claim_seconds)
                owns_claim = True
                await self._session.flush()
            elif row.claim_id == claim_id:
                owns_claim = True
        return StoreBinding(
            deployment_id=row.deployment_id,
            binding_id=row.binding_id,
            confirmed=confirmed,
            claim_id=claim_id if owns_claim else None,
            creation_started=row.create_started_at is not None,
        )

    async def record_switch_claim(
        self,
        *,
        slot: int,
        deployment_id: UUID,
        binding_id: UUID,
    ) -> None:
        """Record that a destination switch is about to claim a bucket.

        Writing the pairing marker is a durable remote effect. Recording the
        intent first means a switch that fails afterwards leaves a tracked
        claim: a retry recognises its own marker, and the temporary slot shows
        an operator which bucket was touched.
        """
        await self._session.execute(
            insert(ObjectStoreBindings)
            .values(
                slot=slot,
                deployment_id=deployment_id,
                binding_id=binding_id,
                create_started_at=func.now(),
            )
            .on_conflict_do_update(
                index_elements=[ObjectStoreBindings.slot],
                set_={
                    "deployment_id": deployment_id,
                    "binding_id": binding_id,
                    "create_started_at": func.now(),
                },
            )
        )
        await self._session.flush()

    async def clear_slot(self, *, slot: int) -> None:
        """Drop a temporary binding record once its switch has settled."""
        await self._session.execute(
            delete(ObjectStoreBindings).where(ObjectStoreBindings.slot == slot)
        )
        await self._session.flush()

    async def mark_creation_started(
        self,
        *,
        slot: int = ACTIVE_DESTINATION_SLOT,
        deployment_id: UUID,
        binding_id: UUID,
        claim_id: UUID,
    ) -> None:
        row = await self._row_for_update(slot)
        if (
            row is None
            or row.deployment_id != deployment_id
            or row.binding_id != binding_id
            or row.confirmed_at is not None
        ):
            raise ObjectContentConfigurationError(
                "Object-content storage binding changed before marker creation"
            )
        now = await self._database_now()
        if (
            row.claim_id != claim_id
            or row.claim_until is None
            or row.claim_until <= now
        ):
            raise ObjectContentBusyError(
                "Object-content storage binding claim is no longer owned"
            )
        if row.create_started_at is not None:
            raise ObjectContentConfigurationError(
                "Object-content marker creation has an ambiguous prior outcome"
            )
        row.create_started_at = now
        await self._session.flush()

    async def confirm(
        self,
        *,
        slot: int = ACTIVE_DESTINATION_SLOT,
        deployment_id: UUID,
        binding_id: UUID,
        claim_id: UUID,
    ) -> None:
        row = await self._row_for_update(slot)
        if (
            row is None
            or row.deployment_id != deployment_id
            or row.binding_id != binding_id
        ):
            raise ObjectContentConfigurationError(
                "Object-content storage binding changed during verification"
            )
        if row.confirmed_at is None:
            if row.claim_id != claim_id:
                raise ObjectContentBusyError(
                    "Object-content storage binding claim changed during verification"
                )
            row.confirmed_at = await self._database_now()
            row.claim_id = None
            row.claim_until = None
            await self._session.flush()

    async def _row_for_update(self, slot: int) -> ObjectStoreBindings | None:
        return (
            await self._session.scalars(
                select(ObjectStoreBindings)
                .where(ObjectStoreBindings.slot == slot)
                .with_for_update()
            )
        ).one_or_none()

    async def _has_object_store_content(self) -> bool:
        return bool(
            await self._session.scalar(
                select(
                    exists().where(
                        ObjectContents.storage_kind == StorageKind.OBJECT_STORE.value
                    )
                )
            )
        )

    async def _database_now(self):
        now = await self._session.scalar(select(func.now()))
        if now is None:
            raise RuntimeError("PostgreSQL did not return its current time")
        return now


async def ensure_store_binding_ready(
    database: DatabaseSessionManager,
    settings: ObjectContentSettings,
    store: S3ObjectStore,
    *,
    slot: int = ACTIVE_DESTINATION_SLOT,
) -> None:
    """Establish or verify the durable PostgreSQL-to-object-store binding."""
    try:
        await store.check_ready()
    except ObjectStoreUnavailableError as error:
        raise ObjectContentUnavailableError(
            "Durable object content is temporarily unavailable"
        ) from error

    claim_id = uuid4()
    try:
        async with database.session() as session, session.begin():
            binding = await StoreBindingRepository(session).get_or_initialize(
                settings.deployment_id,
                slot=slot,
                claim_id=claim_id,
                claim_seconds=settings.binding_claim_seconds,
            )
    except ObjectContentConfigurationError:
        raise
    except (OSError, SQLAlchemyError) as error:
        raise ObjectContentUnavailableError(
            "Unable to verify the object-content database binding"
        ) from error

    if not binding.confirmed and binding.claim_id is None:
        raise ObjectContentUnavailableError(
            "Object-content storage binding is being established"
        )

    try:
        marker_exists = await store.verify_binding(binding.binding_id)
    except ObjectStoreBindingError as error:
        raise ObjectContentConfigurationError(
            "Object-content storage does not match PostgreSQL"
        ) from error
    except ObjectStoreUnavailableError as error:
        raise ObjectContentUnavailableError(
            "Durable object content is temporarily unavailable"
        ) from error

    if binding.confirmed:
        if not marker_exists:
            raise ObjectContentConfigurationError(
                "The confirmed object-content storage binding is missing"
            )
        return

    if not marker_exists:
        if binding.creation_started:
            raise ObjectContentConfigurationError(
                "Object-content marker creation has an ambiguous prior outcome"
            )
        try:
            creation = await store.prepare_binding_creation(binding.binding_id)
        except ObjectStoreBindingError as error:
            raise ObjectContentConfigurationError(
                "Object-content storage does not match PostgreSQL"
            ) from error
        except ObjectStoreUnavailableError as error:
            raise ObjectContentUnavailableError(
                "Durable object content is temporarily unavailable"
            ) from error
        if creation is not None:
            try:
                async with database.session() as session, session.begin():
                    await StoreBindingRepository(session).mark_creation_started(
                        slot=slot,
                        deployment_id=binding.deployment_id,
                        binding_id=binding.binding_id,
                        claim_id=claim_id,
                    )
            except ObjectContentConfigurationError:
                raise
            except ObjectContentBusyError as error:
                raise ObjectContentUnavailableError(
                    "Object-content storage binding claim changed"
                ) from error
            except (OSError, SQLAlchemyError) as error:
                raise ObjectContentUnavailableError(
                    "Unable to claim object-content marker creation"
                ) from error
            try:
                await store.create_binding(creation)
            except ObjectStoreBindingError as error:
                raise ObjectContentConfigurationError(
                    "Object-content storage does not match PostgreSQL"
                ) from error
            except ObjectStoreUnavailableError as error:
                raise ObjectContentUnavailableError(
                    "Durable object content is temporarily unavailable"
                ) from error

    try:
        async with database.session() as session, session.begin():
            await StoreBindingRepository(session).confirm(
                slot=slot,
                deployment_id=binding.deployment_id,
                binding_id=binding.binding_id,
                claim_id=claim_id,
            )
    except ObjectContentConfigurationError:
        raise
    except ObjectContentBusyError as error:
        raise ObjectContentUnavailableError(
            "Object-content storage binding claim changed"
        ) from error
    except (OSError, SQLAlchemyError) as error:
        raise ObjectContentUnavailableError(
            "Unable to confirm the object-content database binding"
        ) from error
