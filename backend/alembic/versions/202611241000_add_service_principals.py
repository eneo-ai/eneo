"""Give every service API key a service principal.

A service key had no identity of its own: what it owned was tied to the key's
id, which changes on rotation. A service principal is the stable identity
behind the key. Every key in a rotation chain points at the same principal.

Existing service keys get one principal per rotation chain, named after the
first key in the chain. User keys are not touched.

Revision ID: 202611241000
Revises: 202611201305
Create Date: 2026-11-24 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202611241000"
down_revision: str = "202611201305"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_service_principals() -> None:
    op.create_table(
        "service_principals",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("scope_type", sa.String(), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(), server_default="active", nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "((state = 'active' AND disabled_at IS NULL) "
            "OR (state = 'disabled' AND disabled_at IS NOT NULL))",
            name="ck_service_principals_disabled_at_matches_state",
        ),
        sa.CheckConstraint(
            "state IN ('active', 'disabled')", name="ck_service_principals_state"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_service_principals_created_by_user",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_service_principals_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_service_principals_tenant_id",
        "service_principals",
        ["tenant_id"],
        unique=False,
    )


def _backfill_service_principals() -> None:
    # A chain starts at a service key that was not rotated from another
    # service key, and follows rotated_from_key_id from there.
    op.execute(
        sa.text(
            """
            CREATE TEMP TABLE service_api_key_chains ON COMMIT DROP AS
            WITH RECURSIVE chains(key_id, root_key_id, path) AS (
                SELECT
                    api_key.id,
                    api_key.id,
                    ARRAY[api_key.id]
                FROM api_keys_v2 AS api_key
                LEFT JOIN api_keys_v2 AS service_parent
                  ON service_parent.id = api_key.rotated_from_key_id
                 AND service_parent.ownership = 'service'
                WHERE api_key.ownership = 'service'
                  AND service_parent.id IS NULL

                UNION ALL

                SELECT
                    child.id,
                    chains.root_key_id,
                    chains.path || child.id
                FROM api_keys_v2 AS child
                JOIN chains ON child.rotated_from_key_id = chains.key_id
                WHERE child.ownership = 'service'
                  AND NOT child.id = ANY(chains.path)
            )
            SELECT key_id, root_key_id
            FROM chains
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TEMP TABLE service_principal_backfill ON COMMIT DROP AS
            SELECT root_key_id, gen_random_uuid() AS service_principal_id
            FROM (
                SELECT DISTINCT root_key_id
                FROM service_api_key_chains
            ) AS roots
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO service_principals (
                id,
                tenant_id,
                display_name,
                description,
                scope_type,
                scope_id,
                state,
                created_by_user_id,
                created_at,
                updated_at
            )
            SELECT
                backfill.service_principal_id,
                root_key.tenant_id,
                root_key.name,
                root_key.description,
                root_key.scope_type,
                root_key.scope_id,
                'active',
                root_key.created_by_user_id,
                now(),
                now()
            FROM service_principal_backfill AS backfill
            JOIN api_keys_v2 AS root_key
              ON root_key.id = backfill.root_key_id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE api_keys_v2 AS api_key
            SET service_principal_id = backfill.service_principal_id
            FROM service_api_key_chains AS chains
            JOIN service_principal_backfill AS backfill
              ON backfill.root_key_id = chains.root_key_id
            WHERE api_key.id = chains.key_id
            """
        )
    )


def _assert_service_principal_backfill() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            DECLARE
                missing_service_principals integer;
                user_keys_with_service_principals integer;
                tenant_mismatches integer;
            BEGIN
                SELECT count(*)
                INTO missing_service_principals
                FROM api_keys_v2
                WHERE ownership = 'service'
                  AND service_principal_id IS NULL;

                IF missing_service_principals > 0 THEN
                    RAISE EXCEPTION
                        'Cannot introduce service principals: % service keys have no principal backfill.',
                        missing_service_principals;
                END IF;

                SELECT count(*)
                INTO user_keys_with_service_principals
                FROM api_keys_v2
                WHERE ownership = 'user'
                  AND service_principal_id IS NOT NULL;

                IF user_keys_with_service_principals > 0 THEN
                    RAISE EXCEPTION
                        'Cannot introduce service principals: % user keys have a service principal.',
                        user_keys_with_service_principals;
                END IF;

                SELECT count(*)
                INTO tenant_mismatches
                FROM api_keys_v2 AS api_key
                JOIN service_principals AS principal
                  ON principal.id = api_key.service_principal_id
                WHERE api_key.tenant_id <> principal.tenant_id;

                IF tenant_mismatches > 0 THEN
                    RAISE EXCEPTION
                        'Cannot introduce service principals: % API keys cross tenant boundaries.',
                        tenant_mismatches;
                END IF;
            END $$;
            """
        )
    )


def _add_validated_check(table: str, name: str, condition: str) -> None:
    op.create_check_constraint(
        name,
        table,
        condition,
        postgresql_not_valid=True,
    )
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def upgrade() -> None:
    _create_service_principals()
    op.add_column(
        "api_keys_v2",
        sa.Column(
            "service_principal_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    _backfill_service_principals()
    _assert_service_principal_backfill()
    _add_validated_check(
        "api_keys_v2",
        "ck_api_keys_v2_service_principal_required",
        "ownership <> 'service' OR service_principal_id IS NOT NULL",
    )
    _add_validated_check(
        "api_keys_v2",
        "ck_api_keys_v2_user_without_service_principal",
        "ownership <> 'user' OR service_principal_id IS NULL",
    )
    op.create_foreign_key(
        "fk_api_keys_v2_service_principal",
        "api_keys_v2",
        "service_principals",
        ["service_principal_id"],
        ["id"],
        ondelete="RESTRICT",
        postgresql_not_valid=True,
    )
    op.execute(
        "ALTER TABLE api_keys_v2 VALIDATE CONSTRAINT fk_api_keys_v2_service_principal"
    )
    op.create_index(
        "idx_api_keys_v2_service_principal_id",
        "api_keys_v2",
        ["service_principal_id"],
        postgresql_where=sa.text("service_principal_id IS NOT NULL"),
    )


def downgrade() -> None:
    # Nothing is lost: the principal carries only what its first key carries,
    # and the upgrade derives it again.
    op.drop_index("idx_api_keys_v2_service_principal_id", table_name="api_keys_v2")
    op.drop_constraint(
        "fk_api_keys_v2_service_principal", "api_keys_v2", type_="foreignkey"
    )
    op.drop_constraint(
        "ck_api_keys_v2_user_without_service_principal",
        "api_keys_v2",
        type_="check",
    )
    op.drop_constraint(
        "ck_api_keys_v2_service_principal_required",
        "api_keys_v2",
        type_="check",
    )
    op.drop_column("api_keys_v2", "service_principal_id")
    op.drop_index("ix_service_principals_tenant_id", table_name="service_principals")
    op.drop_table("service_principals")
