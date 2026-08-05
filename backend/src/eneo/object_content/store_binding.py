from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from eneo.database.database import DatabaseSessionManager
from eneo.object_content.configuration import ObjectContentSettings
from eneo.object_content.content import (
    ObjectContentBusyError,
    ObjectContentConfigurationError,
    ObjectContentUnavailableError,
)
from eneo.object_content.reconciliation_repository import (
    ObjectContentReconciliationRepository,
)
from eneo.object_content.s3_object_store import (
    ObjectStoreBindingError,
    ObjectStoreUnavailableError,
    S3ObjectStore,
)


async def ensure_store_binding_ready(
    database: DatabaseSessionManager,
    settings: ObjectContentSettings,
    store: S3ObjectStore,
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
            binding = await ObjectContentReconciliationRepository(
                session
            ).get_or_initialize_store_binding(
                settings.deployment_id,
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
                    await ObjectContentReconciliationRepository(
                        session
                    ).mark_store_binding_creation_started(
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
            await ObjectContentReconciliationRepository(session).confirm_store_binding(
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
