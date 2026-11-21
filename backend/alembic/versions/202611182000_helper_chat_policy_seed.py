"""Seed the helper chat's organisation settings from the prompt guide, once

The helper chat on assistants takes over from the organisation space's
prompt guide (``org_space_assistant_roles`` with kind ``prompt_guide``). For
each tenant that has a guide:

- the helper chat starts off (``flow_settings.helper_chat.enabled = false``)
  when the guide is not enabled or not visible to users, since either one
  already keeps everyone from using it;
- when the tenant has no default model for helper chats yet
  (``flow_settings.authoring_chat.completion_model_id``), the guide's model
  becomes that default if it is enabled, the tenant's own and supports tool
  calling. ``flow_settings.helper_chat.seeded_completion_model_id`` records
  it, so the downgrade can tell the seed's default from one an administrator
  set.

Nothing else is carried over (not the guide's prompt, knowledge, tools or
retention), the guide's own rows are not changed, and a tenant without a
guide gets nothing written: the defaults apply.

The downgrade removes ``flow_settings.helper_chat`` from every tenant and the
default model where it is still the one the seed set.

Revision ID: 202611182000
Revises: 202611181200
Create Date: 2026-11-18 20:00:00.000000
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202611182000"
down_revision: str | None = "202611181200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    connection = op.get_bind()
    switched_off = connection.execute(
        sa.text(
            """
            WITH off AS (
                SELECT DISTINCT spaces.tenant_id
                FROM org_space_assistant_roles AS roles
                JOIN spaces ON spaces.id = roles.org_space_id
                WHERE roles.kind = 'prompt_guide'
                  AND (NOT roles.is_enabled OR NOT roles.is_visible_to_users)
            )
            UPDATE tenants
            SET flow_settings = jsonb_set(
                tenants.flow_settings,
                '{helper_chat}',
                CASE
                    WHEN jsonb_typeof(tenants.flow_settings->'helper_chat') = 'object'
                    THEN tenants.flow_settings->'helper_chat'
                    ELSE '{}'::jsonb
                END || '{"enabled": false}'::jsonb
            )
            FROM off
            WHERE tenants.id = off.tenant_id
            RETURNING tenants.id
            """
        )
    ).all()
    seeded = connection.execute(
        sa.text(
            """
            WITH guide_models AS (
                SELECT DISTINCT ON (spaces.tenant_id)
                    spaces.tenant_id,
                    models.id AS model_id
                FROM org_space_assistant_roles AS roles
                JOIN spaces ON spaces.id = roles.org_space_id
                JOIN assistants ON assistants.id = roles.assistant_id
                JOIN completion_models AS models
                  ON models.id = assistants.completion_model_id
                WHERE roles.kind = 'prompt_guide'
                  AND models.supports_tool_calling
                  AND models.is_enabled
                  AND (models.tenant_id IS NULL OR models.tenant_id = spaces.tenant_id)
                ORDER BY spaces.tenant_id, roles.updated_at DESC, roles.id
            )
            UPDATE tenants
            SET flow_settings = jsonb_set(
                jsonb_set(
                    tenants.flow_settings,
                    '{authoring_chat}',
                    CASE
                        WHEN jsonb_typeof(tenants.flow_settings->'authoring_chat')
                            = 'object'
                        THEN tenants.flow_settings->'authoring_chat'
                        ELSE '{}'::jsonb
                    END
                    || jsonb_build_object(
                        'completion_model_id', guide_models.model_id::text
                    )
                ),
                '{helper_chat}',
                CASE
                    WHEN jsonb_typeof(tenants.flow_settings->'helper_chat') = 'object'
                    THEN tenants.flow_settings->'helper_chat'
                    ELSE '{}'::jsonb
                END
                || jsonb_build_object(
                    'seeded_completion_model_id', guide_models.model_id::text
                )
            )
            FROM guide_models
            WHERE tenants.id = guide_models.tenant_id
              AND tenants.flow_settings->'authoring_chat'->>'completion_model_id'
                  IS NULL
            RETURNING tenants.id, guide_models.model_id
            """
        )
    ).all()
    for row in switched_off:
        _logger.info(
            "Helper chat starts off, as the prompt guide was: tenant=%s", row.id
        )
    for row in seeded:
        _logger.info(
            "Helper chat default model from the prompt guide: tenant=%s model=%s",
            row.id,
            row.model_id,
        )
    _logger.info(
        "Helper chat settings seeded: %s tenants off, %s default models",
        len(switched_off),
        len(seeded),
    )


def downgrade() -> None:
    # The default model goes only where it is still the one the seed set; an
    # administrator's own choice stays.
    op.execute(
        """
        UPDATE tenants
        SET flow_settings = CASE
            WHEN (flow_settings->'authoring_chat') - 'completion_model_id'
                = '{}'::jsonb
            THEN flow_settings - 'authoring_chat'
            ELSE flow_settings #- '{authoring_chat,completion_model_id}'
        END
        WHERE flow_settings->'helper_chat'->>'seeded_completion_model_id'
              IS NOT NULL
          AND flow_settings->'authoring_chat'->>'completion_model_id'
              = flow_settings->'helper_chat'->>'seeded_completion_model_id'
        """
    )
    op.execute(
        """
        UPDATE tenants
        SET flow_settings = flow_settings - 'helper_chat'
        WHERE flow_settings ? 'helper_chat'
        """
    )
