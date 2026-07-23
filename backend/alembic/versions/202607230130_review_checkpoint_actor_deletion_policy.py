"""Align review-checkpoint user actor deletion policy.

Revision ID: 202607230130_review_actor_delete
Revises: 202607221930_drop_step_deps
Create Date: 2026-07-23 01:30:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "202607230130_review_actor_delete"
down_revision = "202607221930_drop_step_deps"
branch_labels = None
depends_on = None

_TABLE = "flow_run_review_checkpoints"
_USER_FOREIGN_KEYS = (
    (
        "fk_review_checkpoints_requester_user",
        "requester_user_id",
    ),
    (
        "fk_review_checkpoints_decided_by_user",
        "decided_by_user_id",
    ),
)


def _assert_actor_contract(*, user_confdeltype: str) -> None:
    op.execute(f"LOCK TABLE {_TABLE} IN SHARE ROW EXCLUSIVE MODE")
    op.execute(
        f"""
        DO $$
        DECLARE
            matching_actor_foreign_keys integer;
            validated_actor_checks integer;
        BEGIN
            SELECT count(*)
            INTO matching_actor_foreign_keys
            FROM (
                VALUES
                    ('fk_review_checkpoints_requester_user',
                     'requester_user_id', 'users', '{user_confdeltype}'),
                    ('fk_review_checkpoints_decided_by_user',
                     'decided_by_user_id', 'users', '{user_confdeltype}'),
                    ('fk_review_checkpoints_requester_service',
                     'requester_service_id', 'service_principals', 'r'),
                    ('fk_review_checkpoints_decided_by_service',
                     'decided_by_service_id', 'service_principals', 'r')
            ) AS expected(constraint_name, column_name, target_table, delete_action)
            JOIN pg_constraint AS constraint_row
              ON constraint_row.conrelid = '{_TABLE}'::regclass
             AND constraint_row.conname = expected.constraint_name
             AND constraint_row.contype = 'f'
             AND constraint_row.confrelid = to_regclass(expected.target_table)
             AND constraint_row.confdeltype::text = expected.delete_action
             AND constraint_row.convalidated
             AND cardinality(constraint_row.conkey) = 1
            JOIN pg_attribute AS source_attribute
              ON source_attribute.attrelid = constraint_row.conrelid
             AND source_attribute.attnum = constraint_row.conkey[1]
             AND source_attribute.attname = expected.column_name;

            SELECT count(*)
            INTO validated_actor_checks
            FROM pg_constraint AS constraint_row
            WHERE constraint_row.conrelid = '{_TABLE}'::regclass
              AND constraint_row.contype = 'c'
              AND constraint_row.convalidated
              AND constraint_row.conname IN (
                  'ck_flow_run_review_checkpoints_requester_principal',
                  'ck_flow_run_review_checkpoints_decider_principal'
              );

            IF matching_actor_foreign_keys <> 4
               OR validated_actor_checks <> 2 THEN
                RAISE EXCEPTION
                    'Unexpected review-checkpoint actor constraint contract: % matching foreign keys and % validated actor checks.',
                    matching_actor_foreign_keys,
                    validated_actor_checks;
            END IF;
        END
        $$
        """
    )


def _replace_user_foreign_keys(*, ondelete: str) -> None:
    for constraint_name, column_name in _USER_FOREIGN_KEYS:
        op.drop_constraint(constraint_name, _TABLE, type_="foreignkey")
        op.create_foreign_key(
            constraint_name,
            _TABLE,
            "users",
            [column_name],
            ["id"],
            ondelete=ondelete,
            postgresql_not_valid=True,
        )
        op.execute(f"ALTER TABLE {_TABLE} VALIDATE CONSTRAINT {constraint_name}")


def upgrade() -> None:
    _assert_actor_contract(user_confdeltype="n")
    _replace_user_foreign_keys(ondelete="RESTRICT")


def downgrade() -> None:
    _assert_actor_contract(user_confdeltype="r")
    _replace_user_foreign_keys(ondelete="SET NULL")
