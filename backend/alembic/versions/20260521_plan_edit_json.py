"""nest builder plan edit result json

Revision ID: 20260521_plan_edit_json
Revises: 20260519_flow_package_imports
Create Date: 2026-05-21 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260521_plan_edit_json"
down_revision = "20260519_flow_package_imports"
branch_labels = None
depends_on = None

_COMPILED_EDIT_KEYS = (
    "compiled_spec",
    "diff",
    "original_draft",
    "base_flow_revision",
    "warnings",
    "advisories",
    "risk_flags",
    "confidence",
)
_COMPILED_EDIT_KEYS_SQL = ", ".join(f"'{key}'" for key in _COMPILED_EDIT_KEYS)


def upgrade() -> None:
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM builder_plans
                    WHERE edit_result_json IS NOT NULL
                      AND jsonb_typeof(edit_result_json) = 'object'
                      AND NOT (edit_result_json ? 'compiled_edit')
                      AND EXISTS (
                          SELECT 1
                          FROM jsonb_object_keys(
                              edit_result_json - 'description_override_manual'
                          ) AS legacy_key(key)
                      )
                      AND EXISTS (
                          SELECT 1
                          FROM jsonb_object_keys(
                              edit_result_json - 'description_override_manual'
                          ) AS legacy_key(key)
                          WHERE legacy_key.key <> ALL (
                              ARRAY[{_COMPILED_EDIT_KEYS_SQL}]
                          )
                      )
                ) THEN
                    RAISE EXCEPTION
                        'Cannot migrate builder_plans.edit_result_json: unknown legacy flat edit-result keys exist';
                END IF;
            END $$;
            """
        )
    )

    op.execute(
        sa.text(
            f"""
            UPDATE builder_plans
            SET edit_result_json = jsonb_build_object(
                'compiled_edit', edit_result_json - 'description_override_manual',
                'description_override_manual',
                    CASE
                        WHEN jsonb_typeof(
                            edit_result_json -> 'description_override_manual'
                        ) = 'boolean'
                        THEN (
                            edit_result_json ->> 'description_override_manual'
                        )::boolean
                        ELSE false
                    END
            )
            WHERE edit_result_json IS NOT NULL
              AND jsonb_typeof(edit_result_json) = 'object'
              AND NOT (edit_result_json ? 'compiled_edit')
              AND EXISTS (
                  SELECT 1
                  FROM jsonb_object_keys(
                      edit_result_json - 'description_override_manual'
                  ) AS legacy_key(key)
                  WHERE legacy_key.key = ANY (ARRAY[{_COMPILED_EDIT_KEYS_SQL}])
              );
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE builder_plans
            SET edit_result_json = COALESCE(
                    edit_result_json -> 'compiled_edit',
                    '{}'::jsonb
                )
                || CASE
                    WHEN jsonb_typeof(
                        edit_result_json -> 'description_override_manual'
                    ) = 'boolean'
                    AND (
                        edit_result_json ->> 'description_override_manual'
                    )::boolean
                    THEN '{"description_override_manual": true}'::jsonb
                    ELSE '{}'::jsonb
                END
            WHERE edit_result_json IS NOT NULL
              AND jsonb_typeof(edit_result_json) = 'object'
              AND edit_result_json ? 'compiled_edit';
            """
        )
    )
