"""collapse builder plan proposal storage

Revision ID: 20260620_plan_proposal_json
Revises: 202606191530
Create Date: 2026-06-20 15:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# Keep under 32 chars for alembic_version.version_num.
revision = "20260620_plan_proposal_json"
down_revision = "202606191530"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _assert_old_columns_are_valid()

    op.add_column(
        "builder_plans",
        sa.Column(
            "proposal_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Serialized FlowBuilderProposal.",
        ),
    )

    op.execute(
        """
        UPDATE builder_plans
        SET proposal_json =
            jsonb_build_object(
                'content',
                (envelope_json - 'spec' - 'reasoning')
                || jsonb_build_object('spec', spec_json)
                || CASE
                    WHEN edit_result_json IS NULL THEN '{}'::jsonb
                    ELSE jsonb_build_object('edit_result', edit_result_json)
                END,
                'resource_bindings',
                COALESCE(resource_bindings_json, '[]'::jsonb)
            )
            || CASE
                WHEN envelope_json ? 'reasoning'
                     AND envelope_json -> 'reasoning' <> 'null'::jsonb
                    THEN jsonb_build_object('reasoning', envelope_json -> 'reasoning')
                ELSE '{}'::jsonb
            END
        """
    )

    _assert_new_column_is_valid()

    op.alter_column("builder_plans", "proposal_json", nullable=False)
    op.drop_column("builder_plans", "edit_result_json")
    op.drop_column("builder_plans", "resource_bindings_json")
    op.drop_column("builder_plans", "envelope_json")
    op.drop_column("builder_plans", "spec_json")


def downgrade() -> None:
    op.add_column(
        "builder_plans",
        sa.Column("spec_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "builder_plans",
        sa.Column(
            "envelope_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.add_column(
        "builder_plans",
        sa.Column(
            "resource_bindings_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment=(
                "Plan-scoped binding snapshot taken at proposal; transferred to "
                "FlowResourceBindings on apply."
            ),
        ),
    )
    op.add_column(
        "builder_plans",
        sa.Column(
            "edit_result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )

    op.execute(
        """
        UPDATE builder_plans
        SET
            spec_json = proposal_json -> 'content' -> 'spec',
            envelope_json =
                (proposal_json -> 'content') - 'spec' - 'edit_result'
                || CASE
                    WHEN proposal_json ? 'reasoning'
                        THEN jsonb_build_object('reasoning', proposal_json -> 'reasoning')
                    ELSE '{}'::jsonb
                END,
            resource_bindings_json = COALESCE(
                proposal_json -> 'resource_bindings',
                '[]'::jsonb
            ),
            edit_result_json = proposal_json -> 'content' -> 'edit_result'
        """
    )

    op.alter_column("builder_plans", "spec_json", nullable=False)
    op.alter_column("builder_plans", "envelope_json", nullable=False)
    op.drop_column("builder_plans", "proposal_json")


def _assert_old_columns_are_valid() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM builder_plans
                WHERE jsonb_typeof(spec_json) <> 'object'
                   OR jsonb_typeof(envelope_json) <> 'object'
                   OR jsonb_typeof(resource_bindings_json) <> 'array'
                   OR (
                        edit_result_json IS NOT NULL
                        AND jsonb_typeof(edit_result_json) <> 'object'
                   )
            ) THEN
                RAISE EXCEPTION
                    'Cannot migrate builder_plans proposal storage: invalid old JSON shape';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM builder_plans bp
                CROSS JOIN LATERAL jsonb_object_keys(bp.envelope_json - 'spec') AS key(name)
                WHERE key.name NOT IN (
                    'assumptions',
                    'lint_warnings',
                    'risk_acknowledgments',
                    'reasoning',
                    'plan_rationale'
                )
            ) THEN
                RAISE EXCEPTION
                    'Cannot migrate builder_plans proposal storage: envelope_json has unknown keys';
            END IF;
        END $$;
        """
    )


def _assert_new_column_is_valid() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM builder_plans
                WHERE proposal_json IS NULL
                   OR jsonb_typeof(proposal_json) <> 'object'
                   OR NOT (proposal_json ? 'content')
                   OR jsonb_typeof(proposal_json -> 'content') <> 'object'
                   OR NOT ((proposal_json -> 'content') ? 'spec')
                   OR jsonb_typeof(proposal_json -> 'content' -> 'spec') <> 'object'
                   OR NOT (proposal_json ? 'resource_bindings')
                   OR jsonb_typeof(proposal_json -> 'resource_bindings') <> 'array'
                   OR (
                        (proposal_json -> 'content') ? 'edit_result'
                        AND jsonb_typeof(
                            proposal_json -> 'content' -> 'edit_result'
                        ) <> 'object'
                   )
                   OR (
                        proposal_json ? 'reasoning'
                        AND jsonb_typeof(proposal_json -> 'reasoning') <> 'string'
                   )
            ) THEN
                RAISE EXCEPTION
                    'Cannot migrate builder_plans proposal storage: invalid proposal_json';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM builder_plans bp
                CROSS JOIN LATERAL jsonb_object_keys(bp.proposal_json) AS key(name)
                WHERE key.name NOT IN (
                    'content',
                    'resource_bindings',
                    'reasoning'
                )
            ) THEN
                RAISE EXCEPTION
                    'Cannot migrate builder_plans proposal storage: proposal_json has unknown keys';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM builder_plans bp
                CROSS JOIN LATERAL jsonb_object_keys(
                    bp.proposal_json -> 'content'
                ) AS key(name)
                WHERE key.name NOT IN (
                    'spec',
                    'assumptions',
                    'lint_warnings',
                    'risk_acknowledgments',
                    'plan_rationale',
                    'edit_result'
                )
            ) THEN
                RAISE EXCEPTION
                    'Cannot migrate builder_plans proposal storage: proposal_json.content has unknown keys';
            END IF;
        END $$;
        """
    )
