"""Leave the flows_core flag and the roles as the organisation chose them

This revision used to turn the ``flows_core`` flag on for every tenant and to
give predefined Owner and AI Configurator roles the flow permissions. An
upgrade must not make that choice for an organisation: Flows stay off, as
202610211900 seeded the flag, until an administrator switches them on with the
organisation's own row in ``tenant_feature_flags`` and grants the roles that
should use them.

The revision stays in the chain with an empty body both ways, so databases
already past it keep their revision history and the graph does not change.

Revision ID: 202610220930
Revises: 202610212300
Create Date: 2026-10-22 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "202610220930"
down_revision: str | None = "202610212300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
