"""Persistence of one organisation's transcription-service connections."""

from __future__ import annotations

from collections.abc import Sequence
from typing import NoReturn
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer, selectinload

from eneo.database.database import AsyncSession
from eneo.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassificationTable,
)
from eneo.database.tables.transcription_services_table import (
    SpacesTranscriptionServiceConnections,
    TranscriptionServiceConnections,
)
from eneo.main.exceptions import NameCollisionException, NotFoundException
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from eneo.transcription_services.models import TranscriptionServiceConnection

_UNIQUE_NAME = "uq_transcription_service_connections_name"


class TranscriptionServiceConnectionRepository:
    """Reads and writes are confined to one tenant; another tenant's
    connection is reported as not found."""

    def __init__(self, session: AsyncSession, tenant_id: UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id

    async def count(self) -> int:
        return (
            await self.session.scalar(
                sa.select(sa.func.count())
                .select_from(TranscriptionServiceConnections)
                .where(TranscriptionServiceConnections.tenant_id == self.tenant_id)
            )
        ) or 0

    async def list(
        self, *, limit: int | None = None, offset: int = 0
    ) -> list[TranscriptionServiceConnection]:
        stmt = (
            self._select()
            .order_by(
                TranscriptionServiceConnections.name,
                TranscriptionServiceConnections.id,
            )
            .offset(offset)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = (await self.session.scalars(stmt)).all()
        return [_to_domain(row) for row in rows]

    async def list_granted(
        self, space_id: UUID
    ) -> list[TranscriptionServiceConnection]:
        """The connections granted to one space, in name order."""
        grants = SpacesTranscriptionServiceConnections
        stmt = (
            self._select()
            .join(
                grants,
                grants.connection_id == TranscriptionServiceConnections.id,
            )
            .where(grants.space_id == space_id)
            .order_by(
                TranscriptionServiceConnections.name,
                TranscriptionServiceConnections.id,
            )
        )
        rows = (await self.session.scalars(stmt)).all()
        return [_to_domain(row) for row in rows]

    async def get(self, connection_id: UUID) -> TranscriptionServiceConnection:
        return _to_domain(await self._row(connection_id))

    async def get_with_key(
        self, connection_id: UUID
    ) -> tuple[TranscriptionServiceConnection, str]:
        """The connection and its key ciphertext from one row read, so an edit
        committed in between can never pair an endpoint with another key."""
        table = TranscriptionServiceConnections
        row = (
            await self.session.execute(
                self._select()
                .add_columns(table.api_key_encrypted)
                .where(table.id == connection_id)
            )
        ).one_or_none()
        if row is None:
            raise NotFoundException("Transcription service not found")
        connection_row, ciphertext = row
        return _to_domain(connection_row), ciphertext

    async def get_many(
        self, connection_ids: Sequence[UUID]
    ) -> list[TranscriptionServiceConnection]:
        """The named connections in request order; any unknown id is not found."""
        if not connection_ids:
            return []
        rows = (
            await self.session.scalars(
                self._select().where(
                    TranscriptionServiceConnections.id.in_(set(connection_ids))
                )
            )
        ).all()
        by_id = {row.id: _to_domain(row) for row in rows}
        missing = [str(id) for id in connection_ids if id not in by_id]
        if missing:
            raise NotFoundException(
                f"Transcription service not found: {', '.join(missing)}"
            )
        return [by_id[id] for id in connection_ids]

    async def create(
        self,
        *,
        name: str,
        endpoint_url: str,
        api_key_encrypted: str,
        is_enabled: bool,
        security_classification_id: UUID | None,
    ) -> TranscriptionServiceConnection:
        table = TranscriptionServiceConnections
        try:
            async with self.session.begin_nested():
                connection_id = await self.session.scalar(
                    sa.insert(table)
                    .values(
                        tenant_id=self.tenant_id,
                        name=name,
                        endpoint_url=endpoint_url,
                        api_key_encrypted=api_key_encrypted,
                        is_enabled=is_enabled,
                        security_classification_id=security_classification_id,
                    )
                    .returning(table.id)
                )
        except IntegrityError as exc:
            _raise_name_collision(exc)
        assert connection_id is not None
        return await self.get(connection_id)

    async def lock(self, connection_id: UUID) -> TranscriptionServiceConnections:
        """The row, locked for this transaction's edit.

        Concurrent edits of one connection serialise here, so a key and the
        endpoint it was entered for are always written together.
        """
        return await self._row(connection_id, for_update=True)

    async def save(
        self, row: TranscriptionServiceConnections
    ) -> TranscriptionServiceConnection:
        connection_id = row.id
        await self._flush()
        # Reload whole: the row's server-side updated_at and its reloaded
        # classification must come back, never stale attributes.
        self.session.expire(row)
        return await self.get(connection_id)

    async def delete(self, connection_id: UUID) -> None:
        """Delete the connection; the database removes its space grants."""
        await self.session.delete(await self._row(connection_id, for_update=True))
        await self.session.flush()

    def _select(self) -> sa.Select[tuple[TranscriptionServiceConnections]]:
        return (
            sa.select(TranscriptionServiceConnections)
            .where(TranscriptionServiceConnections.tenant_id == self.tenant_id)
            .options(
                # The key is read only where it is sent (get_with_key).
                defer(TranscriptionServiceConnections.api_key_encrypted),
                selectinload(
                    TranscriptionServiceConnections.security_classification
                ).selectinload(SecurityClassificationTable.tenant),
            )
        )

    async def _row(
        self, connection_id: UUID, *, for_update: bool = False
    ) -> TranscriptionServiceConnections:
        stmt = self._select().where(TranscriptionServiceConnections.id == connection_id)
        if for_update:
            stmt = stmt.with_for_update(of=TranscriptionServiceConnections)
        row = (await self.session.scalars(stmt)).one_or_none()
        if row is None:
            raise NotFoundException("Transcription service not found")
        return row

    async def _flush(self) -> None:
        try:
            await self.session.flush()
        except IntegrityError as exc:
            _raise_name_collision(exc)


def _raise_name_collision(exc: IntegrityError) -> NoReturn:
    if _UNIQUE_NAME in str(exc.orig):
        raise NameCollisionException(
            "A transcription service with this name already exists"
        ) from None
    raise exc


def _to_domain(row: TranscriptionServiceConnections) -> TranscriptionServiceConnection:
    return TranscriptionServiceConnection(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        endpoint_url=row.endpoint_url,
        is_enabled=row.is_enabled,
        security_classification=SecurityClassification.to_domain(
            row.security_classification
        ),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
