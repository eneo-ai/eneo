"""Seed Help Assistants per tenant (v1 rollout)

For every existing tenant, idempotently ensures:
  1. An org-space (spaces row with user_id IS NULL AND tenant_space_id IS NULL).
  2. A per-tenant system user (users.is_system_user = true) in that tenant.
  3. A default Prompt Guide assistant in the org-space, owned by the system
     user, populated from the defaults snapshot inlined in this file.
  4. The active prompt_guide role assignment in
     ``org_space_assistant_roles``.

Idempotence:
  - Each insert uses ``WHERE NOT EXISTS`` or ``ON CONFLICT DO NOTHING``.
  - Phase 3 (assistant + prompt + role) short-circuits if a
    ``prompt_guide`` role already exists for the org-space, so re-runs do not
    create duplicate prompts/assistants under a fresh UUID.
  - Re-running ``upgrade()`` after a successful ``upgrade()`` leaves the
    database unchanged.

Downgrade:
  - No-op. Seeded rows are user data after the fact (admins may have edited
    the Prompt Guide prompt, attached knowledge, etc.). Auto-deleting them
    on rollback would destroy that work. Operators who want to truly
    reverse this migration should do so manually.

Defaults snapshot:
  - The Prompt Guide name, description, prompt text, and config values are
    inlined below. They MUST match ``intric.help_assistants.defaults`` at
    the time this migration was authored. Migrations may not import from
    ``intric.*`` (the modules they reference get refactored over time),
    hence the duplication. See ``backend/src/intric/help_assistants/defaults.py``
    docstring and ``.claude/plans/help-assistants/README.md`` "Plan
    adjustments" / step 007 for the runbook when editing the registry.

Completion model resolution:
  - Per-tenant default completion model is picked with a raw SQL query that
    mirrors ``CompletionModelCRUDService.get_default_completion_model``:
    prefer ``is_default = true``, then a tenant-scoped model over a global
    model, then the most recently created. If no eligible completion model
    exists, the Prompt Guide is seeded with ``completion_model_id = NULL``
    and a warning is printed; the admin must pick one before the helper
    can run.

PRD §2, §8.

Revision ID: 202605211400
Revises: 202605211300
Create Date: 2026-05-21
"""

from uuid import uuid4

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic
revision = "202605211400"
down_revision = "202605211300"
branch_labels = None
depends_on = None


PROMPT_GUIDE_NAME = "Prompt Guide"
PROMPT_GUIDE_DESCRIPTION = (
    "Helps an editor iterate on the system prompt of the assistant they "
    "are currently editing. Asks short, focused questions and produces a "
    "final prompt at the end of the conversation."
)
PROMPT_GUIDE_PROMPT_TEXT = (
    "You are the Prompt Guide, a Help Assistant inside Eneo. Your role "
    "is to help the user iterate on the system prompt of an assistant "
    "they are currently editing.\n\n"
    "Always answer in the user's UI language. If the user writes in "
    "Swedish, reply in Swedish. If the user writes in English, reply in "
    "English. Do not switch languages mid-conversation unless the user "
    "does.\n\n"
    "Conduct a short interview: ask one focused question at a time about "
    "the assistant's purpose, audience, tone, constraints, and the kinds "
    "of inputs and outputs it should handle. Wait for the user's answer "
    "before moving on. Keep questions concise.\n\n"
    "When you have enough information, produce the final artifact: a "
    "complete, ready-to-use system prompt for the assistant the user is "
    "editing. Present it clearly so the user can copy or apply it.\n\n"
    "You are a plain-text assistant. Do not call tools, browse the web, "
    "or use external integrations. Stay focused on prompt design."
)
PROMPT_GUIDE_DATA_RETENTION_DAYS = 30
ORG_SPACE_NAME = "Organisation"


def upgrade() -> None:
    conn = op.get_bind()

    # Phase 1 — ensure an org-space per tenant. The partial unique index
    # `idx_unique_org_space_per_tenant` already enforces at most one
    # org-space per tenant; the NOT EXISTS guard keeps the insert
    # idempotent without relying on ON CONFLICT against a partial index.
    conn.execute(
        text(
            """
            INSERT INTO spaces (
                id, tenant_id, user_id, tenant_space_id, name, description,
                created_at, updated_at
            )
            SELECT gen_random_uuid(), t.id, NULL, NULL, :name, NULL, now(), now()
            FROM tenants t
            WHERE NOT EXISTS (
                SELECT 1 FROM spaces s
                WHERE s.tenant_id = t.id
                  AND s.user_id IS NULL
                  AND s.tenant_space_id IS NULL
            )
            """
        ),
        {"name": ORG_SPACE_NAME},
    )

    # Phase 2 — ensure a per-tenant system user. Email and username are
    # synthesized from the tenant id so re-runs are stable and the active-
    # email partial-unique index (`idx_unique_active_user_email`) never
    # fires. `password` and `salt` are NULL — the password verifier cannot
    # produce a match for NULL, and `state = 'inactive'` plus
    # `is_active = false` keep the user out of every login/search path.
    conn.execute(
        text(
            """
            INSERT INTO users (
                id, email, username, email_verified, salt, password,
                is_active, state, used_tokens, tenant_id, quota_limit,
                is_system_user, created_at, updated_at
            )
            SELECT
                gen_random_uuid(),
                'system+' || t.id::text || '@eneo.local',
                'system+' || t.id::text,
                false,
                NULL,
                NULL,
                false,
                'inactive',
                0,
                t.id,
                NULL,
                true,
                now(),
                now()
            FROM tenants t
            WHERE NOT EXISTS (
                SELECT 1 FROM users u
                WHERE u.tenant_id = t.id AND u.is_system_user = true
            )
            """
        )
    )

    # Phase 3 — ensure a Prompt Guide assistant and the active role
    # assignment per tenant. Driven by a Python loop because we need to
    # capture multiple generated UUIDs (prompt + assistant) and link them
    # via `prompts_assistants` and `org_space_assistant_roles`.
    tenants = conn.execute(text("SELECT id FROM tenants")).fetchall()

    for (tenant_id,) in tenants:
        org_space_row = conn.execute(
            text(
                """
                SELECT id FROM spaces
                WHERE tenant_id = :tid
                  AND user_id IS NULL
                  AND tenant_space_id IS NULL
                """
            ),
            {"tid": tenant_id},
        ).first()
        org_space_id = org_space_row.id

        system_user_row = conn.execute(
            text(
                """
                SELECT id FROM users
                WHERE tenant_id = :tid AND is_system_user = true
                """
            ),
            {"tid": tenant_id},
        ).first()
        system_user_id = system_user_row.id

        # Short-circuit if Prompt Guide role assignment is already in
        # place — preserves the existing prompt/assistant rows on re-runs.
        existing_role = conn.execute(
            text(
                """
                SELECT 1 FROM org_space_assistant_roles
                WHERE org_space_id = :osid AND kind = 'prompt_guide'
                """
            ),
            {"osid": org_space_id},
        ).first()
        if existing_role:
            continue

        # Mirrors CompletionModelCRUDService.get_default_completion_model:
        # prefer is_default models, prefer tenant-specific over global,
        # break ties by most recent. `is_enabled` and `not is_deprecated`
        # approximate the runtime `can_access` check minus the tenant-
        # credentials gate (which is environment-specific and out of scope
        # for a one-shot seed).
        cm_row = conn.execute(
            text(
                """
                SELECT id
                FROM completion_models
                WHERE (tenant_id = :tid OR tenant_id IS NULL)
                  AND is_enabled = true
                  AND is_deprecated = false
                ORDER BY
                    is_default DESC,
                    (tenant_id IS NOT NULL) DESC,
                    created_at DESC NULLS LAST
                LIMIT 1
                """
            ),
            {"tid": tenant_id},
        ).first()
        completion_model_id = cm_row.id if cm_row else None
        if completion_model_id is None:
            print(
                f"[seed help-assistants] Tenant {tenant_id}: no eligible "
                "completion model; Prompt Guide created with "
                "completion_model_id = NULL — an admin must pick one "
                "before the helper can run."
            )

        prompt_id = uuid4()
        conn.execute(
            text(
                """
                INSERT INTO prompts (
                    id, text, description, user_id, tenant_id,
                    created_at, updated_at
                )
                VALUES (:pid, :text, :desc, :uid, :tid, now(), now())
                """
            ),
            {
                "pid": prompt_id,
                "text": PROMPT_GUIDE_PROMPT_TEXT,
                "desc": PROMPT_GUIDE_DESCRIPTION,
                "uid": system_user_id,
                "tid": tenant_id,
            },
        )

        assistant_id = uuid4()
        conn.execute(
            text(
                """
                INSERT INTO assistants (
                    id, name, description, user_id, space_id,
                    completion_model_id, logging_enabled, insight_enabled,
                    is_default, published, type, data_retention_days,
                    created_at, updated_at
                )
                VALUES (
                    :aid, :name, :desc, :uid, :sid,
                    :cm, false, false,
                    false, false, 'assistant', :retention,
                    now(), now()
                )
                """
            ),
            {
                "aid": assistant_id,
                "name": PROMPT_GUIDE_NAME,
                "desc": PROMPT_GUIDE_DESCRIPTION,
                "uid": system_user_id,
                "sid": org_space_id,
                "cm": completion_model_id,
                "retention": PROMPT_GUIDE_DATA_RETENTION_DAYS,
            },
        )

        conn.execute(
            text(
                """
                INSERT INTO prompts_assistants (
                    prompt_id, assistant_id, is_selected,
                    created_at, updated_at
                )
                VALUES (:pid, :aid, true, now(), now())
                """
            ),
            {"pid": prompt_id, "aid": assistant_id},
        )

        # Phase 4 — active role assignment. UNIQUE(org_space_id, kind)
        # plus the short-circuit above keep this single-occupancy.
        # created_by_user_id / updated_by_user_id are NULL: this row was
        # seeded by the platform, not actioned by a human admin.
        conn.execute(
            text(
                """
                INSERT INTO org_space_assistant_roles (
                    id, org_space_id, kind, assistant_id,
                    is_enabled, is_visible_to_users,
                    created_by_user_id, updated_by_user_id,
                    created_at, updated_at
                ) VALUES (
                    gen_random_uuid(), :osid, 'prompt_guide', :aid,
                    true, true,
                    NULL, NULL,
                    now(), now()
                )
                """
            ),
            {"osid": org_space_id, "aid": assistant_id},
        )


def downgrade() -> None:
    # Intentional no-op. See module docstring for rationale.
    pass
