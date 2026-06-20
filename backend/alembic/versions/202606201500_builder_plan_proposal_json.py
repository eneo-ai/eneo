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
                || jsonb_build_object(
                    'description_override_manual',
                    CASE
                        WHEN edit_result_json IS NOT NULL
                             AND jsonb_typeof(edit_result_json -> 'description_override_manual') = 'boolean'
                            THEN edit_result_json -> 'description_override_manual'
                        ELSE 'false'::jsonb
                    END
                )
                || CASE
                    WHEN edit_result_json IS NULL
                         OR NOT (edit_result_json ? 'compiled_edit')
                         OR edit_result_json -> 'compiled_edit' = 'null'::jsonb
                        THEN '{}'::jsonb
                    ELSE jsonb_build_object(
                        'edit',
                        jsonb_build_object(
                            'base_flow_revision',
                            edit_result_json -> 'compiled_edit' -> 'base_flow_revision',
                            'removed_existing_step_refs',
                            COALESCE(
                                (
                                    SELECT jsonb_agg(
                                        change -> 'step_ref'
                                        ORDER BY (change ->> 'step_ref') COLLATE "C"
                                    )
                                    FROM jsonb_array_elements(
                                        edit_result_json -> 'compiled_edit' -> 'diff' -> 'step_changes'
                                    ) AS change
                                    WHERE change ->> 'kind' = 'removed'
                                      AND change ? 'step_ref'
                                      AND change -> 'step_ref' <> 'null'::jsonb
                                ),
                                '[]'::jsonb
                            ),
                            'diff',
                            edit_result_json -> 'compiled_edit' -> 'diff',
                            'warnings',
                            COALESCE(
                                edit_result_json -> 'compiled_edit' -> 'warnings',
                                '[]'::jsonb
                            ),
                            'advisories',
                            COALESCE(
                                edit_result_json -> 'compiled_edit' -> 'advisories',
                                '[]'::jsonb
                            ),
                            'risk_flags',
                            COALESCE(
                                edit_result_json -> 'compiled_edit' -> 'risk_flags',
                                '[]'::jsonb
                            ),
                            'confidence',
                            COALESCE(
                                edit_result_json -> 'compiled_edit' -> 'confidence',
                                '"ready"'::jsonb
                            )
                        )
                    )
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
                (proposal_json -> 'content') - 'spec' - 'edit'
                    - 'description_override_manual'
                || CASE
                    WHEN proposal_json ? 'reasoning'
                        THEN jsonb_build_object('reasoning', proposal_json -> 'reasoning')
                    ELSE '{}'::jsonb
                END,
            resource_bindings_json = COALESCE(
                proposal_json -> 'resource_bindings',
                '[]'::jsonb
            ),
            edit_result_json =
                CASE
                    WHEN proposal_json -> 'content' ? 'edit'
                        THEN jsonb_build_object(
                            'description_override_manual',
                            COALESCE(
                                proposal_json -> 'content' -> 'description_override_manual',
                                'false'::jsonb
                            ),
                            'compiled_edit',
                            jsonb_build_object(
                                'compiled_spec',
                                proposal_json -> 'content' -> 'spec',
                                'diff',
                                proposal_json -> 'content' -> 'edit' -> 'diff',
                                'original_draft',
                                jsonb_build_object(
                                    'operations',
                                    COALESCE(
                                        (
                                            SELECT jsonb_agg(
                                                jsonb_build_object(
                                                    'op',
                                                    'remove',
                                                    'target_ref',
                                                    removed_ref.value
                                                )
                                            )
                                            FROM jsonb_array_elements_text(
                                                proposal_json -> 'content' -> 'edit'
                                                    -> 'removed_existing_step_refs'
                                            ) AS removed_ref(value)
                                        ),
                                        '[]'::jsonb
                                    )
                                ),
                                'base_flow_revision',
                                proposal_json -> 'content' -> 'edit' -> 'base_flow_revision',
                                'warnings',
                                COALESCE(
                                    proposal_json -> 'content' -> 'edit' -> 'warnings',
                                    '[]'::jsonb
                                ),
                                'advisories',
                                COALESCE(
                                    proposal_json -> 'content' -> 'edit' -> 'advisories',
                                    '[]'::jsonb
                                ),
                                'risk_flags',
                                COALESCE(
                                    proposal_json -> 'content' -> 'edit' -> 'risk_flags',
                                    '[]'::jsonb
                                ),
                                'confidence',
                                COALESCE(
                                    proposal_json -> 'content' -> 'edit' -> 'confidence',
                                    '"ready"'::jsonb
                                )
                            )
                        )
                    WHEN COALESCE(
                        (proposal_json -> 'content' ->> 'description_override_manual')::boolean,
                        false
                    )
                        THEN jsonb_build_object('description_override_manual', true)
                    ELSE NULL
                END
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
                        (proposal_json -> 'content') ? 'edit'
                        AND jsonb_typeof(
                            proposal_json -> 'content' -> 'edit'
                        ) <> 'object'
                   )
                   OR (
                        (proposal_json -> 'content') ? 'description_override_manual'
                        AND jsonb_typeof(
                            proposal_json -> 'content' -> 'description_override_manual'
                        ) <> 'boolean'
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
                    'description_override_manual',
                    'edit'
                )
            ) THEN
                RAISE EXCEPTION
                    'Cannot migrate builder_plans proposal storage: proposal_json.content has unknown keys';
            END IF;
        END $$;
        """
    )
