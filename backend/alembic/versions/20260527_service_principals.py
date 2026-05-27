"""introduce stable service principals for service API keys

Revision ID: 20260527_service_principals
Revises: 20260527_review_ckpt_snapshot
Create Date: 2026-05-27 11:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260527_service_principals"
down_revision = "20260527_review_ckpt_snapshot"
branch_labels = None
depends_on = None


_SERVICE_PRINCIPALS = "service_principals"
_API_KEYS = "api_keys_v2"
_SERVICE_PRINCIPAL_FK = "fk_api_keys_v2_service_principal"
_SERVICE_PRINCIPAL_REQUIRED_CHECK = "ck_api_keys_v2_service_principal_required"
_USER_WITHOUT_SERVICE_PRINCIPAL_CHECK = "ck_api_keys_v2_user_without_service_principal"
_API_KEYS_SERVICE_PRINCIPAL_INDEX = "idx_api_keys_v2_service_principal_id"


def _create_service_principals_table() -> None:
    op.create_table(
        _SERVICE_PRINCIPALS,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("scope_type", sa.String(), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "state",
            sa.String(),
            server_default="active",
            nullable=False,
        ),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('active', 'disabled')",
            name="ck_service_principals_state",
        ),
        sa.CheckConstraint(
            "("
            "(state = 'active' AND disabled_at IS NULL) "
            "OR "
            "(state = 'disabled' AND disabled_at IS NOT NULL)"
            ")",
            name="ck_service_principals_disabled_at_matches_state",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
            name="fk_service_principals_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
            name="fk_service_principals_created_by_user",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_service_principals_tenant_id",
        _SERVICE_PRINCIPALS,
        ["tenant_id"],
    )


def _backfill_service_principals() -> None:
    op.execute(
        sa.text(
            """
            CREATE TEMP TABLE service_api_key_chains ON COMMIT DROP AS
            WITH RECURSIVE chains(key_id, root_key_id, path) AS (
                SELECT
                    api_key.id AS key_id,
                    api_key.id AS root_key_id,
                    ARRAY[api_key.id] AS path
                FROM api_keys_v2 AS api_key
                LEFT JOIN api_keys_v2 AS service_parent
                  ON service_parent.id = api_key.rotated_from_key_id
                 AND service_parent.ownership = 'service'
                WHERE api_key.ownership = 'service'
                  AND service_parent.id IS NULL

                UNION ALL

                SELECT
                    child.id AS key_id,
                    chains.root_key_id,
                    chains.path || child.id
                FROM api_keys_v2 AS child
                JOIN chains
                  ON child.rotated_from_key_id = chains.key_id
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
            SELECT
                root_key_id,
                gen_random_uuid() AS service_principal_id
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
                        'Cannot introduce service principals: % service-owned api_keys_v2 rows have no service principal backfill.',
                        missing_service_principals;
                END IF;

                SELECT count(*)
                INTO user_keys_with_service_principals
                FROM api_keys_v2
                WHERE ownership = 'user'
                  AND service_principal_id IS NOT NULL;

                IF user_keys_with_service_principals > 0 THEN
                    RAISE EXCEPTION
                        'Cannot introduce service principals: % user-owned api_keys_v2 rows have service_principal_id.',
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
                        'Cannot introduce service principals: % api_keys_v2 rows link to a principal in another tenant.',
                        tenant_mismatches;
                END IF;
            END $$;
            """
        )
    )


def _add_api_key_service_principal_constraints() -> None:
    op.execute(
        sa.text(
            f"""
            ALTER TABLE {_API_KEYS}
            ADD CONSTRAINT {_SERVICE_PRINCIPAL_REQUIRED_CHECK}
            CHECK (ownership <> 'service' OR service_principal_id IS NOT NULL)
            NOT VALID
            """
        )
    )
    op.execute(
        f"ALTER TABLE {_API_KEYS} VALIDATE CONSTRAINT "
        f"{_SERVICE_PRINCIPAL_REQUIRED_CHECK}"
    )
    op.execute(
        sa.text(
            f"""
            ALTER TABLE {_API_KEYS}
            ADD CONSTRAINT {_USER_WITHOUT_SERVICE_PRINCIPAL_CHECK}
            CHECK (ownership <> 'user' OR service_principal_id IS NULL)
            NOT VALID
            """
        )
    )
    op.execute(
        f"ALTER TABLE {_API_KEYS} VALIDATE CONSTRAINT "
        f"{_USER_WITHOUT_SERVICE_PRINCIPAL_CHECK}"
    )
    op.create_foreign_key(
        _SERVICE_PRINCIPAL_FK,
        _API_KEYS,
        _SERVICE_PRINCIPALS,
        ["service_principal_id"],
        ["id"],
        ondelete="RESTRICT",
        postgresql_not_valid=True,
    )
    op.execute(f"ALTER TABLE {_API_KEYS} VALIDATE CONSTRAINT {_SERVICE_PRINCIPAL_FK}")


def upgrade() -> None:
    _create_service_principals_table()
    op.add_column(
        _API_KEYS,
        sa.Column("service_principal_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    _backfill_service_principals()
    _assert_service_principal_backfill()
    _add_api_key_service_principal_constraints()

    with op.get_context().autocommit_block():
        op.create_index(
            _API_KEYS_SERVICE_PRINCIPAL_INDEX,
            _API_KEYS,
            ["service_principal_id"],
            postgresql_where=sa.text("service_principal_id IS NOT NULL"),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            _API_KEYS_SERVICE_PRINCIPAL_INDEX,
            table_name=_API_KEYS,
            postgresql_concurrently=True,
        )

    op.drop_constraint(_SERVICE_PRINCIPAL_FK, _API_KEYS, type_="foreignkey")
    op.drop_constraint(_USER_WITHOUT_SERVICE_PRINCIPAL_CHECK, _API_KEYS, type_="check")
    op.drop_constraint(_SERVICE_PRINCIPAL_REQUIRED_CHECK, _API_KEYS, type_="check")
    op.drop_column(_API_KEYS, "service_principal_id")
    op.drop_index("ix_service_principals_tenant_id", table_name=_SERVICE_PRINCIPALS)
    op.drop_table(_SERVICE_PRINCIPALS)
