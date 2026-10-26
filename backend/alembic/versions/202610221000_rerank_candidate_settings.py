"""rerank candidate settings per model

Adds candidate_factor and max_candidates to rerank_models; existing rows get
5 and 100.

Revision ID: 202610221000
Revises: 202610161000
Create Date: 2026-10-22 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610221000"
down_revision: str | None = "202610161000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "rerank_models",
        sa.Column("candidate_factor", sa.Integer(), server_default="5", nullable=False),
    )
    op.add_column(
        "rerank_models",
        sa.Column("max_candidates", sa.Integer(), server_default="100", nullable=False),
    )
    op.create_check_constraint(
        "ck_rerank_models_candidate_factor_range",
        "rerank_models",
        "candidate_factor BETWEEN 1 AND 20",
    )
    op.create_check_constraint(
        "ck_rerank_models_max_candidates_range",
        "rerank_models",
        "max_candidates BETWEEN 1 AND 1000",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_rerank_models_max_candidates_range", "rerank_models", type_="check"
    )
    op.drop_constraint(
        "ck_rerank_models_candidate_factor_range", "rerank_models", type_="check"
    )
    op.drop_column("rerank_models", "max_candidates")
    op.drop_column("rerank_models", "candidate_factor")
