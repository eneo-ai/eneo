# MIT License

"""Helpers for validating tenant-scoped security classification references.

The tenant model routers (completion / embedding / transcription) all need
the same lookup: "given an optional classification id from a request body,
return the UUID if it belongs to this tenant, raise NotFoundException
otherwise". This module is the single home for that lookup so the three
routers stay in sync as the rule evolves (e.g. soft-delete, archived
classifications).
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.security_classifications_table import SecurityClassification
from eneo.main.exceptions import NotFoundException
from eneo.main.models import ModelId


async def resolve_tenant_security_classification(
    session: AsyncSession,
    reference: ModelId | None,
    tenant_id: UUID,
) -> UUID | None:
    """Validate a security classification reference against a tenant.

    Returns the classification UUID when the reference is set and belongs to
    `tenant_id`, `None` when no reference was supplied, and raises
    `NotFoundException` when the reference points at a classification that
    does not exist in this tenant (including cross-tenant attempts).

    Note on archival/soft-delete: the `security_classifications` table has no
    `deleted_at` column today, so an "exists in tenant" check is sufficient.
    If soft-delete is ever added, this query must also filter out deleted
    rows — otherwise admins could attach archived classifications to new
    models, silently re-introducing semantically retired levels.
    """
    if reference is None:
        return None

    stmt = sa.select(SecurityClassification.id).where(
        SecurityClassification.id == reference.id,
        SecurityClassification.tenant_id == tenant_id,
    )
    result = await session.execute(stmt)
    classification_id = result.scalar_one_or_none()
    if classification_id is None:
        raise NotFoundException("Security classification not found")
    return classification_id
