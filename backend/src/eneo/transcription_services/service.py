"""Administration of an organisation's native transcription-service connections."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.main.models import NOT_PROVIDED, ModelId, NotProvided, is_provided
from eneo.model_providers.domain.endpoints import require_key_for_destination
from eneo.security_classifications.tenant_validation import (
    resolve_tenant_security_classification,
)
from eneo.transcription_services.client import (
    CredentialsRejected,
    TranscriptionServiceClient,
)
from eneo.transcription_services.models import TranscriptionServiceConnection

if TYPE_CHECKING:
    from eneo.audit.application.audit_service import AuditService
    from eneo.settings.encryption_service import EncryptionService
    from eneo.transcription_services.repository import (
        TranscriptionServiceConnectionRepository,
    )
    from eneo.users.user import UserInDB

# An administrator waits for the check; a service that has not answered by
# then is reported unavailable rather than holding the request for the
# minutes a transcription request may take.
_CHECK_TIMEOUT_SECONDS = 10.0


class ConnectionCheckOutcome(StrEnum):
    READY = "ready"
    NOT_ACCEPTING_JOBS = "not_accepting_jobs"
    UNAVAILABLE = "unavailable"
    CREDENTIALS_REJECTED = "credentials_rejected"


@dataclass(frozen=True, slots=True)
class ConnectionCheck:
    """What the service answered to an authenticated readiness request.

    No audio is sent. ``identifies_speakers`` is None when the service does
    not report which tasks it supports.
    """

    outcome: ConnectionCheckOutcome
    detail: str
    identifies_speakers: bool | None
    service_version: str | None


class TranscriptionServiceConnectionService:
    def __init__(
        self,
        *,
        user: UserInDB,
        repository: TranscriptionServiceConnectionRepository,
        encryption: EncryptionService,
        audit_service: AuditService,
    ) -> None:
        self.user = user
        self.repository = repository
        self.encryption = encryption
        self.audit_service = audit_service

    async def list(
        self, *, limit: int, offset: int
    ) -> tuple[list[TranscriptionServiceConnection], bool]:
        """One page in name order, and whether another page follows."""
        page = await self.repository.list(limit=limit + 1, offset=offset)
        return page[:limit], len(page) > limit

    async def get(self, connection_id: UUID) -> TranscriptionServiceConnection:
        return await self.repository.get(connection_id)

    async def create(
        self,
        *,
        name: str,
        endpoint_url: str,
        api_key: str,
        is_enabled: bool,
        security_classification: ModelId | None,
    ) -> TranscriptionServiceConnection:
        require_key_for_destination(
            stored_destination=None,
            proposed_destination=endpoint_url,
            key_stored=False,
            replacement_key=api_key,
        )
        connection = await self.repository.create(
            name=name,
            endpoint_url=endpoint_url,
            api_key_encrypted=self.encryption.encrypt(api_key),
            is_enabled=is_enabled,
            security_classification_id=await self._classification_id(
                security_classification
            ),
        )
        await self._audit(
            ActionType.TRANSCRIPTION_SERVICE_CREATED,
            connection,
            f"Created transcription service '{connection.name}'",
            extra=_facts(connection),
        )
        return connection

    async def update(
        self,
        connection_id: UUID,
        *,
        name: str | NotProvided = NOT_PROVIDED,
        endpoint_url: str | NotProvided = NOT_PROVIDED,
        api_key: str | NotProvided = NOT_PROVIDED,
        is_enabled: bool | NotProvided = NOT_PROVIDED,
        security_classification: ModelId | None | NotProvided = NOT_PROVIDED,
    ) -> TranscriptionServiceConnection:
        row = await self.repository.lock(connection_id)
        before = await self.repository.get(connection_id)
        require_key_for_destination(
            stored_destination=row.endpoint_url,
            proposed_destination=endpoint_url
            if is_provided(endpoint_url)
            else row.endpoint_url,
            key_stored=True,
            replacement_key=api_key if is_provided(api_key) else None,
        )
        # Everything that can query or fail runs before the row is dirtied:
        # a query would autoflush a half-applied edit outside the save.
        classification_id = (
            await self._classification_id(security_classification)
            if is_provided(security_classification)
            else NOT_PROVIDED
        )
        api_key_encrypted = (
            self.encryption.encrypt(api_key) if is_provided(api_key) else NOT_PROVIDED
        )
        if is_provided(name):
            row.name = name
        if is_provided(endpoint_url):
            row.endpoint_url = endpoint_url
        if is_provided(api_key_encrypted):
            row.api_key_encrypted = api_key_encrypted
        if is_provided(is_enabled):
            row.is_enabled = is_enabled
        if is_provided(classification_id):
            row.security_classification_id = classification_id
        after = await self.repository.save(row)
        changes = _changes(before, after)
        if is_provided(api_key):
            changes["api_key"] = {"old": "set", "new": "replaced"}
        if changes:
            await self._audit(
                ActionType.TRANSCRIPTION_SERVICE_UPDATED,
                after,
                f"Updated transcription service '{after.name}'",
                changes=changes,
            )
        return after

    async def delete(self, connection_id: UUID) -> None:
        # Locked first, so the audit records the state that is deleted.
        await self.repository.lock(connection_id)
        connection = await self.repository.get(connection_id)
        await self.repository.delete(connection_id)
        await self._audit(
            ActionType.TRANSCRIPTION_SERVICE_DELETED,
            connection,
            f"Deleted transcription service '{connection.name}'",
            extra=_facts(connection),
        )

    async def check(self, connection_id: UUID) -> ConnectionCheck:
        """Ask the service whether it would admit a job from this connection."""
        connection, ciphertext = await self.repository.get_with_key(connection_id)
        client = TranscriptionServiceClient(
            base_url=connection.endpoint_url,
            api_key=self.encryption.decrypt(ciphertext),
            submit_timeout_seconds=_CHECK_TIMEOUT_SECONDS,
            result_timeout_seconds=_CHECK_TIMEOUT_SECONDS,
        )
        try:
            readiness = await client.check_readiness()
        except CredentialsRejected:
            result = ConnectionCheck(
                outcome=ConnectionCheckOutcome.CREDENTIALS_REJECTED,
                detail="the service rejected the API key",
                identifies_speakers=None,
                service_version=None,
            )
        else:
            result = ConnectionCheck(
                outcome=ConnectionCheckOutcome.UNAVAILABLE
                if not readiness.ready
                else ConnectionCheckOutcome.READY
                if readiness.accepting_jobs
                else ConnectionCheckOutcome.NOT_ACCEPTING_JOBS,
                detail=readiness.detail,
                identifies_speakers=readiness.identifies_speakers,
                service_version=readiness.service_version,
            )
        await self._audit(
            ActionType.TRANSCRIPTION_SERVICE_CHECKED,
            connection,
            f"Checked transcription service '{connection.name}'",
            extra={
                "outcome": result.outcome.value,
                "detail": result.detail,
                "identifies_speakers": result.identifies_speakers,
            },
        )
        return result

    async def _classification_id(self, reference: ModelId | None) -> UUID | None:
        return await resolve_tenant_security_classification(
            self.repository.session, reference, self.user.tenant_id
        )

    async def _audit(
        self,
        action: ActionType,
        connection: TranscriptionServiceConnection,
        description: str,
        *,
        changes: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            user=self.user,
            action=action,
            entity_type=EntityType.TRANSCRIPTION_SERVICE,
            entity_id=connection.id,
            description=description,
            metadata=AuditMetadata.standard(
                actor=self.user, target=connection, changes=changes, extra=extra
            ),
        )


def _facts(connection: TranscriptionServiceConnection) -> dict[str, Any]:
    """What the connection is, as recorded in the audit log; never the key."""
    classification = connection.security_classification
    return {
        "endpoint_url": connection.endpoint_url,
        "is_enabled": connection.is_enabled,
        "security_classification_id": str(classification.id)
        if classification is not None
        else None,
    }


def _changes(
    before: TranscriptionServiceConnection, after: TranscriptionServiceConnection
) -> dict[str, Any]:
    old = {"name": before.name, **_facts(before)}
    new = {"name": after.name, **_facts(after)}
    return {
        field: {"old": old[field], "new": new[field]}
        for field in old
        if old[field] != new[field]
    }
