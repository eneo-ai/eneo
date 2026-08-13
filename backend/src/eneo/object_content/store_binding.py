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

from sqlalchemy import delete, exists, func, select, text, update
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
        legacy_columns = False
        if row is None and slot == ACTIVE_DESTINATION_SLOT:
            legacy_columns = await self._legacy_binding_columns_present()
            if legacy_columns:
                adopted = await self._adopt_legacy_binding(deployment_id)
                if adopted is not None:
                    return adopted
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
            if legacy_columns:
                # Mirror the chosen identity into the legacy columns so a
                # previous-version worker, serialized behind the state-row
                # lock the adoption read took, initializes with the same
                # identity instead of forking its own.
                await self._session.execute(
                    text(
                        "UPDATE object_content_reconciliation_state "
                        "SET store_deployment_id = :deployment_id, "
                        "store_binding_id = :binding_id "
                        "WHERE id = 1 AND store_binding_id IS NULL"
                    ),
                    {
                        "deployment_id": row.deployment_id,
                        "binding_id": row.binding_id,
                    },
                )
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
                    # A fresh claim supersedes any expired release lease.
                    "claim_id": None,
                    "claim_until": None,
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

    async def hold_release_lease(self, *, slot: int, lease_seconds: int) -> None:
        """Mark the slot's claimed bucket as being released.

        While the lease is unexpired, a switch must not adopt the
        destination: the releasing actor may delete its marker at any moment.
        The lease expires on its own, so a release that dies mid-flight only
        delays the next attempt instead of wedging it.
        """
        await self._session.execute(
            update(ObjectStoreBindings)
            .where(ObjectStoreBindings.slot == slot)
            .values(
                claim_id=uuid4(),
                claim_until=func.now() + timedelta(seconds=lease_seconds),
            )
        )
        await self._session.flush()

    async def release_lease_active(self, *, slot: int) -> bool:
        """Whether an unexpired release lease guards the slot's bucket."""
        active = await self._session.scalar(
            select(
                exists().where(
                    ObjectStoreBindings.slot == slot,
                    ObjectStoreBindings.claim_id.is_not(None),
                    ObjectStoreBindings.claim_until > func.now(),
                )
            )
        )
        return bool(active)

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

    async def _legacy_binding_columns_present(self) -> bool:
        """True while the pre-contract legacy binding columns still exist."""
        column_present = await self._session.scalar(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'object_content_reconciliation_state' "
                "AND column_name = 'store_binding_id'"
            )
        )
        return bool(column_present)

    async def _adopt_legacy_binding(self, deployment_id: UUID) -> StoreBinding | None:
        """Adopt binding facts a pre-upgrade process wrote after the expand.

        The expand migration copies the legacy reconciliation-state columns
        once. A previous-version worker still running in the deployment
        window can initialize or confirm a binding in those columns
        afterwards, so an absent table row consults them and adopts what it
        finds. The read locks the state row — the same lock a previous-
        version initializer holds — so the two versions serialize instead of
        forking separate identities from the same empty state. The contract
        release drops the columns together with this fallback.
        """
        # The row is locked even when it holds no binding yet: the lock, not
        # the filter, is what serializes this read against a previous-version
        # initializer, and an unbound row is exactly the fork-critical case.
        legacy = (
            await self._session.execute(
                text(
                    "SELECT store_deployment_id, store_binding_id, "
                    "store_binding_confirmed_at, store_binding_create_started_at "
                    "FROM object_content_reconciliation_state "
                    "WHERE id = 1 FOR UPDATE"
                )
            )
        ).one_or_none()
        if legacy is None or legacy[1] is None:
            return None
        stored_deployment_id, binding_id, confirmed_at, create_started_at = legacy
        if stored_deployment_id != deployment_id:
            raise ObjectContentConfigurationError(
                "Object-content deployment identity does not match PostgreSQL"
            )
        await self._session.execute(
            insert(ObjectStoreBindings)
            .values(
                slot=ACTIVE_DESTINATION_SLOT,
                deployment_id=stored_deployment_id,
                binding_id=binding_id,
                confirmed_at=confirmed_at,
                create_started_at=create_started_at,
            )
            .on_conflict_do_nothing(index_elements=[ObjectStoreBindings.slot])
        )
        return StoreBinding(
            deployment_id=stored_deployment_id,
            binding_id=binding_id,
            confirmed=confirmed_at is not None,
            claim_id=None,
            creation_started=create_started_at is not None,
        )

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
            async with database.session() as session, session.begin():
                admin_managed = await session.scalar(
                    select(ObjectStoreConnections.id).where(
                        ObjectStoreConnections.id == slot
                    )
                )
            if admin_managed is None:
                # An environment-managed destination can be repointed by
                # editing configuration, so a missing marker keeps failing
                # closed: it may be a different bucket entirely.
                raise ObjectContentConfigurationError(
                    "The confirmed object-content storage binding is missing"
                )
            # An administrator-managed destination only changes through
            # probed, fenced flows, so the confirmed database binding is the
            # durable authority and an absent marker is a lost projection —
            # the endgame of a cleanup racing a destination switch. Re-assert
            # it instead of failing readiness permanently.
            try:
                creation = await store.prepare_binding_creation(
                    binding.binding_id, require_empty_namespace=False
                )
                if creation is not None:
                    await store.create_binding(creation)
            except ObjectStoreBindingError as error:
                raise ObjectContentConfigurationError(
                    "Object-content storage does not match PostgreSQL"
                ) from error
            except ObjectStoreUnavailableError as error:
                raise ObjectContentUnavailableError(
                    "Durable object content is temporarily unavailable"
                ) from error
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
