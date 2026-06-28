# MIT License

"""Shared display-name uniqueness guard for the model tables.

A model's display name (`nickname`) is what users pick from in the chat model
selector and admin tables; two *active* models sharing one are impossible to
tell apart. This mirrors the partial unique indexes added in the
`20260602_unique_display_names` migration so the service layer raises a clean
409 instead of letting the DB throw a raw 500 on insert.

Used by both the tenant model service (AddWizard path) and the sysadmin
global-model endpoints — same rule everywhere. The predicate must stay in lockstep
with that migration's index: active = `deleted_at IS NULL AND is_deprecated = false`,
case-insensitive via SQL `lower()`, scoped per (tenant, provider). Global models
always carry `provider_id IS NULL`, so they share one provider scope and stay
unique per name; the same name may repeat across a tenant's providers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

import sqlalchemy as sa

from eneo.main.exceptions import NameCollisionException

if TYPE_CHECKING:
    from eneo.database.database import AsyncSession


async def validate_unique_display_name(
    session: "AsyncSession",
    table: Any,
    *,
    tenant_id: UUID | None,
    nickname: str | None,
    provider_id: UUID | None = None,
    exclude_id: UUID | None = None,
) -> None:
    """Raise `NameCollisionException` if another active model in the same
    (tenant, provider) scope already uses `nickname`. No-op when `nickname` is
    None.

    `table` is one of the three model ORM tables (all carry `nickname`,
    `deleted_at`, `is_deprecated`, `tenant_id`, `provider_id` after the
    model-table alignment). `provider_id` is None for global models (which also
    have no provider) and otherwise scopes the check to one provider, so a name
    may repeat across a tenant's providers. Pass `exclude_id` on updates so a row
    never collides with itself.
    """
    if nickname is None:
        return

    conditions = [
        sa.func.lower(table.nickname) == sa.func.lower(nickname),
        table.deleted_at.is_(None),
        table.is_deprecated.is_(False),
    ]
    if tenant_id is None:
        conditions.append(table.tenant_id.is_(None))
    else:
        conditions.append(table.tenant_id == tenant_id)
    if provider_id is None:
        conditions.append(table.provider_id.is_(None))
    else:
        conditions.append(table.provider_id == provider_id)
    if exclude_id is not None:
        conditions.append(table.id != exclude_id)

    existing = (
        await session.execute(sa.select(table.id).where(*conditions).limit(1))
    ).scalar_one_or_none()
    if existing is not None:
        raise NameCollisionException(f"A model named '{nickname}' already exists.")
