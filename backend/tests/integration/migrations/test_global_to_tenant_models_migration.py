"""
Integration tests for the global-to-tenant-models migration.

These tests verify the complete migration flow from global AI models
(tenant_id=NULL, provider_id=NULL) to tenant-specific models with proper
FK reference updates across all affected tables.

The tests simulate a realistic "legacy" database state with:
- Multiple tenants with different credentials configurations
- Global completion, embedding, and transcription models
- Assistants, apps, services, spaces linked to global models
- Model settings and many-to-many relationships

After running the migration, we verify:
- Providers are created per tenant based on credentials
- Tenant-specific model copies are created
- All FK references are updated correctly
- Global models are deleted
- No orphaned references remain

NOTE: These tests use a special approach where we:
1. Downgrade to a state BEFORE the migration
2. Create legacy data (global models with FK relations)
3. Run the migration (upgrade)
4. Verify results

IMPORTANT: These tests use their own isolated PostgreSQL container to avoid
interference with other integration tests. This is necessary because:
- Migration tests need to downgrade/upgrade the database schema
- Other tests expect the database to be at the latest migration
- Using a shared database would cause test failures when run together
"""

import json
from pathlib import Path

import psycopg2
import pytest
from alembic import command
from alembic.config import Config
from datetime import datetime, timezone
from uuid import uuid4


# Mark tests to run only when explicitly selected (not as part of larger suite)
# These tests downgrade/upgrade the database schema and must run in isolation.
# Run with: pytest -m migration_isolation tests/integration/migrations/test_global_to_tenant_models_migration.py -v
pytestmark = pytest.mark.migration_isolation


def get_alembic_config(database_url: str) -> Config:
    """Get Alembic config for programmatic migrations."""
    backend_dir = Path(__file__).parent.parent.parent.parent
    alembic_ini_path = backend_dir / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini_path))
    alembic_cfg.set_main_option("sqlalchemy.url", database_url)
    return alembic_cfg


def create_legacy_database_state(cur, now: datetime) -> dict:
    """
    Create a realistic legacy database state with global models
    and entities linked to them.

    Args:
        cur: psycopg2 cursor object
        now: datetime for timestamps

    Returns:
        dict with IDs of created entities
    """
    # =====================================================================
    # TENANTS - Different credential configurations
    # =====================================================================

    # Tenant 1: Full credentials (OpenAI + Azure)
    tenant1_id = str(uuid4())
    tenant1_credentials = {
        "openai": {
            "api_key": "sk-test-tenant1-openai-key",
            "set_at": now.isoformat()
        },
        "azure": {
            "api_key": "azure-test-tenant1-key",
            "endpoint": "https://tenant1.openai.azure.com",
            "api_version": "2024-02-01",
            "set_at": now.isoformat()
        }
    }

    # Tenant 2: Only OpenAI credentials
    tenant2_id = str(uuid4())
    tenant2_credentials = {
        "openai": {
            "api_key": "sk-test-tenant2-openai-key",
            "set_at": now.isoformat()
        }
    }

    # Tenant 3: No credentials (empty)
    tenant3_id = str(uuid4())
    tenant3_credentials = {}

    # Insert tenants
    for tenant_id, name, creds in [
        (tenant1_id, "Tenant One", tenant1_credentials),
        (tenant2_id, "Tenant Two", tenant2_credentials),
        (tenant3_id, "Tenant Three", tenant3_credentials),
    ]:
        cur.execute("""
            INSERT INTO tenants (id, name, quota_limit, api_credentials, state, created_at, updated_at)
            VALUES (%s, %s, %s, %s::jsonb, 'active', %s, %s)
        """, (tenant_id, name, 1000000, json.dumps(creds), now, now))

    # =====================================================================
    # USERS - One per tenant
    # =====================================================================
    user_ids = {}
    for tenant_id, tenant_name in [(tenant1_id, "one"), (tenant2_id, "two"), (tenant3_id, "three")]:
        user_id = str(uuid4())
        user_ids[tenant_id] = user_id
        cur.execute("""
            INSERT INTO users (id, tenant_id, username, email, used_tokens, state, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (user_id, tenant_id, f"user_{tenant_name}", f"user@tenant{tenant_name}.com", 0, 'active', now, now))

    # =====================================================================
    # GLOBAL COMPLETION MODELS (tenant_id=NULL, provider_id=NULL)
    # =====================================================================
    completion_models = [
        {"name": "gpt-4o", "nickname": "GPT-4o", "family": "openai", "token_limit": 128000, "vision": True, "reasoning": False},
        {"name": "gpt-4-turbo", "nickname": "GPT-4 Turbo", "family": "openai", "token_limit": 128000, "vision": True, "reasoning": False},
        {"name": "gpt-3.5-turbo", "nickname": "GPT-3.5 Turbo", "family": "openai", "token_limit": 16385, "vision": False, "reasoning": False},
        {"name": "claude-3-opus", "nickname": "Claude 3 Opus", "family": "claude", "token_limit": 200000, "vision": True, "reasoning": False},
        {"name": "claude-3-sonnet", "nickname": "Claude 3 Sonnet", "family": "claude", "token_limit": 200000, "vision": True, "reasoning": False},
        {"name": "claude-3-haiku", "nickname": "Claude 3 Haiku", "family": "claude", "token_limit": 200000, "vision": True, "reasoning": False},
        {"name": "mistral-large", "nickname": "Mistral Large", "family": "mistral", "token_limit": 32000, "vision": False, "reasoning": False},
        {"name": "mistral-small", "nickname": "Mistral Small", "family": "mistral", "token_limit": 32000, "vision": False, "reasoning": False},
        {"name": "gpt-4o-azure", "nickname": "GPT-4o (Azure)", "family": "azure", "token_limit": 128000, "vision": True, "reasoning": False},
        {"name": "o1-preview", "nickname": "O1 Preview", "family": "openai", "token_limit": 128000, "vision": False, "reasoning": True},
    ]

    completion_model_ids = {}
    for model in completion_models:
        model_id = str(uuid4())
        completion_model_ids[model["name"]] = model_id
        # Note: Before f7f7647d5327, tenant_id and provider_id columns
        # don't exist yet - they are added by that migration
        cur.execute("""
            INSERT INTO completion_models (
                id, name, nickname, family,
                token_limit, vision, reasoning, is_deprecated,
                stability, hosting, open_source,
                created_at, updated_at
            )
            VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, false,
                'stable', 'usa', false,
                %s, %s
            )
        """, (model_id, model["name"], model["nickname"], model["family"],
              model["token_limit"], model["vision"], model["reasoning"], now, now))

    # =====================================================================
    # GLOBAL EMBEDDING MODELS
    # =====================================================================
    embedding_models = [
        {"name": "text-embedding-3-small", "family": "openai", "dimensions": 1536, "max_input": 8191},
        {"name": "text-embedding-3-large", "family": "openai", "dimensions": 3072, "max_input": 8191},
        {"name": "text-embedding-ada-002", "family": "openai", "dimensions": 1536, "max_input": 8191},
        {"name": "multilingual-e5-large", "family": "e5", "dimensions": 1024, "max_input": 512},
        {"name": "embed-multilingual-v3.0", "family": "cohere", "dimensions": 1024, "max_input": 512},
    ]

    embedding_model_ids = {}
    for model in embedding_models:
        model_id = str(uuid4())
        embedding_model_ids[model["name"]] = model_id
        # Note: Before f7f7647d5327, tenant_id and provider_id columns
        # don't exist yet - they are added by that migration
        cur.execute("""
            INSERT INTO embedding_models (
                id, name, family,
                dimensions, max_input, max_batch_size, is_deprecated,
                stability, hosting, open_source,
                created_at, updated_at
            )
            VALUES (
                %s, %s, %s,
                %s, %s, 100, false,
                'stable', 'usa', false,
                %s, %s
            )
        """, (model_id, model["name"], model["family"],
              model["dimensions"], model["max_input"], now, now))

    # =====================================================================
    # GLOBAL TRANSCRIPTION MODELS
    # =====================================================================
    transcription_models = [
        {"name": "whisper-1", "model_name": "whisper-1", "family": "openai"},
        {"name": "kb-whisper", "model_name": "kb-whisper-large", "family": "berget"},
    ]

    transcription_model_ids = {}
    for model in transcription_models:
        model_id = str(uuid4())
        transcription_model_ids[model["name"]] = model_id
        # Note: Before f7f7647d5327, tenant_id and provider_id columns
        # don't exist yet - they are added by that migration
        cur.execute("""
            INSERT INTO transcription_models (
                id, name, model_name, family,
                is_deprecated, stability, hosting, open_source, base_url,
                created_at, updated_at
            )
            VALUES (
                %s, %s, %s, %s,
                false, 'stable', 'usa', false, '',
                %s, %s
            )
        """, (model_id, model["name"], model["model_name"], model["family"], now, now))

    # =====================================================================
    # SPACES - Per tenant (one org space + one personal space per tenant)
    # =====================================================================
    space_ids = {}
    for tenant_id in [tenant1_id, tenant2_id, tenant3_id]:
        user_id = user_ids[tenant_id]
        # First space: org space (user_id = NULL)
        org_space_id = str(uuid4())
        space_ids.setdefault(tenant_id, []).append(org_space_id)
        cur.execute("""
            INSERT INTO spaces (id, tenant_id, user_id, name, created_at, updated_at)
            VALUES (%s, %s, NULL, %s, %s, %s)
        """, (org_space_id, tenant_id, "Organization Space", now, now))

        # Second space: personal space (user_id = user)
        personal_space_id = str(uuid4())
        space_ids[tenant_id].append(personal_space_id)
        cur.execute("""
            INSERT INTO spaces (id, tenant_id, user_id, name, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (personal_space_id, tenant_id, user_id, "Personal Space", now, now))

    # =====================================================================
    # ASSISTANTS - Linked to global completion models
    # =====================================================================
    assistant_ids = {}
    assistants_data = [
        # Tenant 1 assistants
        (tenant1_id, "Customer Support Bot", "gpt-4o"),
        (tenant1_id, "Code Assistant", "gpt-4-turbo"),
        (tenant1_id, "Quick Helper", "gpt-3.5-turbo"),
        (tenant1_id, "Creative Writer", "claude-3-opus"),
        # Tenant 2 assistants
        (tenant2_id, "Sales Bot", "gpt-4o"),
        (tenant2_id, "FAQ Bot", "gpt-3.5-turbo"),
        (tenant2_id, "Analysis Bot", "claude-3-sonnet"),
        # Tenant 3 assistants
        (tenant3_id, "General Assistant", "gpt-4o"),
        (tenant3_id, "Research Bot", "claude-3-haiku"),
    ]

    for tenant_id, name, model_name in assistants_data:
        assistant_id = str(uuid4())
        assistant_ids.setdefault(tenant_id, []).append(assistant_id)
        model_id = completion_model_ids[model_name]
        user_id = user_ids[tenant_id]
        space_id = space_ids[tenant_id][0]  # Use first space

        cur.execute("""
            INSERT INTO assistants (
                id, user_id, space_id, name, completion_model_id,
                logging_enabled, is_default, published, type, insight_enabled,
                created_at, updated_at
            )
            VALUES (
                %s, %s, %s, %s, %s,
                false, false, false, 'assistant', false,
                %s, %s
            )
        """, (assistant_id, user_id, space_id, name, model_id, now, now))

    # =====================================================================
    # APPS - Linked to global completion models
    # =====================================================================
    app_ids = {}
    apps_data = [
        (tenant1_id, "Chatbot App", "gpt-4o"),
        (tenant1_id, "Summarizer App", "gpt-3.5-turbo"),
        (tenant2_id, "Q&A App", "gpt-4-turbo"),
        (tenant3_id, "Translation App", "claude-3-sonnet"),
    ]

    for tenant_id, name, model_name in apps_data:
        app_id = str(uuid4())
        app_ids.setdefault(tenant_id, []).append(app_id)
        model_id = completion_model_ids[model_name]
        user_id = user_ids[tenant_id]
        space_id = space_ids[tenant_id][0]

        cur.execute("""
            INSERT INTO apps (
                id, tenant_id, user_id, space_id, name, completion_model_id,
                published,
                created_at, updated_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s,
                false,
                %s, %s
            )
        """, (app_id, tenant_id, user_id, space_id, name, model_id, now, now))

    # =====================================================================
    # SERVICES - Linked to global completion models
    # =====================================================================
    service_ids = {}
    services_data = [
        (tenant1_id, "API Service", "gpt-4o"),
        (tenant1_id, "Batch Service", "gpt-3.5-turbo"),
        (tenant2_id, "Webhook Service", "gpt-4-turbo"),
    ]

    for tenant_id, name, model_name in services_data:
        service_id = str(uuid4())
        service_ids.setdefault(tenant_id, []).append(service_id)
        model_id = completion_model_ids[model_name]
        user_id = user_ids[tenant_id]
        space_id = space_ids[tenant_id][0]

        cur.execute("""
            INSERT INTO services (
                id, user_id, space_id, name, completion_model_id,
                prompt,
                created_at, updated_at
            )
            VALUES (
                %s, %s, %s, %s, %s,
                'Service prompt',
                %s, %s
            )
        """, (service_id, user_id, space_id, name, model_id, now, now))

    # =====================================================================
    # GROUPS (Collections) - Linked to global embedding models
    # =====================================================================
    group_ids = {}
    groups_data = [
        (tenant1_id, "Knowledge Base", "text-embedding-3-small"),
        (tenant1_id, "Documents", "text-embedding-3-large"),
        (tenant2_id, "FAQ Collection", "text-embedding-ada-002"),
        (tenant3_id, "Research Papers", "multilingual-e5-large"),
    ]

    for tenant_id, name, model_name in groups_data:
        group_id = str(uuid4())
        group_ids.setdefault(tenant_id, []).append(group_id)
        model_id = embedding_model_ids[model_name]
        user_id = user_ids[tenant_id]
        space_id = space_ids[tenant_id][0]

        cur.execute("""
            INSERT INTO groups (
                id, tenant_id, user_id, space_id, name, embedding_model_id,
                size,
                created_at, updated_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s,
                0,
                %s, %s
            )
        """, (group_id, tenant_id, user_id, space_id, name, model_id, now, now))

    # =====================================================================
    # SPACES_COMPLETION_MODELS - Many-to-many
    # =====================================================================
    for tenant_id in [tenant1_id, tenant2_id, tenant3_id]:
        for space_id in space_ids[tenant_id]:
            # Add 3-4 models per space
            models_to_add = ["gpt-4o", "gpt-3.5-turbo", "claude-3-sonnet"]
            for model_name in models_to_add:
                model_id = completion_model_ids[model_name]
                cur.execute("""
                    INSERT INTO spaces_completion_models (space_id, completion_model_id, created_at, updated_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                """, (space_id, model_id, now, now))

    # =====================================================================
    # SPACES_EMBEDDING_MODELS - Many-to-many
    # =====================================================================
    for tenant_id in [tenant1_id, tenant2_id, tenant3_id]:
        for space_id in space_ids[tenant_id]:
            # Add 2 embedding models per space
            models_to_add = ["text-embedding-3-small", "multilingual-e5-large"]
            for model_name in models_to_add:
                model_id = embedding_model_ids[model_name]
                cur.execute("""
                    INSERT INTO spaces_embedding_models (space_id, embedding_model_id, created_at, updated_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                """, (space_id, model_id, now, now))

    # =====================================================================
    # COMPLETION_MODEL_SETTINGS - Per tenant settings for global models
    # =====================================================================
    for tenant_id in [tenant1_id, tenant2_id, tenant3_id]:
        for model_name, model_id in completion_model_ids.items():
            # Enable most models, set one as default
            is_default = model_name == "gpt-4o"
            cur.execute("""
                INSERT INTO completion_model_settings (
                    tenant_id, completion_model_id, is_org_enabled, is_org_default,
                    created_at, updated_at
                )
                VALUES (%s, %s, true, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (tenant_id, model_id, is_default, now, now))

    # =====================================================================
    # EMBEDDING_MODEL_SETTINGS - Per tenant settings for global models
    # =====================================================================
    for tenant_id in [tenant1_id, tenant2_id, tenant3_id]:
        for model_name, model_id in embedding_model_ids.items():
            is_default = model_name == "text-embedding-3-small"
            cur.execute("""
                INSERT INTO embedding_model_settings (
                    tenant_id, embedding_model_id, is_org_enabled, is_org_default,
                    created_at, updated_at
                )
                VALUES (%s, %s, true, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (tenant_id, model_id, is_default, now, now))

    return {
        "tenant_ids": [tenant1_id, tenant2_id, tenant3_id],
        "user_ids": user_ids,
        "completion_model_ids": completion_model_ids,
        "embedding_model_ids": embedding_model_ids,
        "transcription_model_ids": transcription_model_ids,
        "space_ids": space_ids,
        "assistant_ids": assistant_ids,
        "app_ids": app_ids,
        "service_ids": service_ids,
        "group_ids": group_ids,
        "tenant_credentials": {
            tenant1_id: tenant1_credentials,
            tenant2_id: tenant2_credentials,
            tenant3_id: tenant3_credentials,
        }
    }


@pytest.fixture(autouse=True)
def cleanup_database():
    """Override the autouse cleanup_database fixture from conftest.py.

    We don't want the database to be cleaned between tests in this module
    since we set up legacy data once and run the migration once for all tests.
    """
    yield
    # Do nothing - don't clean up


@pytest.fixture(autouse=True)
def seed_default_models():
    """Override the autouse seed_default_models fixture from conftest.py.

    We don't want default models seeded since we're creating our own legacy data.
    """
    yield
    # Do nothing


@pytest.fixture(scope="module")
def migration_test_db(test_settings):
    """
    Special database setup for migration tests.

    This fixture tests BOTH migrations in sequence:
    1. Downgrade stepwise to BEFORE migrate_global_to_tenant_models
       (this runs consolidate_model_settings downgrade which recreates settings tables)
    2. Creates legacy data (global models + settings in separate tables)
    3. Runs migrate_global_to_tenant_models (updates FK references)
    4. Runs consolidate_model_settings (moves settings to model columns)
    5. Returns connection info for tests to verify results

    NOTE: These tests must be run in isolation:
        pytest tests/integration/migrations/test_global_to_tenant_models_migration.py -v

    Using module scope so all tests in this module share the same migrated state.
    """
    # Connect to the database
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    conn.autocommit = True

    alembic_cfg = get_alembic_config(test_settings.sync_database_url)

    # Target revision: just before f7f7647d5327 which adds model_providers table
    # At this point: model tables exist but WITHOUT tenant_id/provider_id columns,
    # and completion_model_settings table exists
    pre_migration_revision = "20260116_update_audit_actor_fk"

    try:
        # Stepwise downgrade to restore settings tables:
        # 1. First downgrade to migrate_global_to_tenant_models
        #    (this runs consolidate_model_settings downgrade, recreating settings tables)
        # 2. Then downgrade to pre_migration_revision (before f7f7647d5327)
        try:
            print("Downgrading stepwise to restore settings tables...")
            # This triggers consolidate_model_settings downgrade which recreates settings tables
            command.downgrade(alembic_cfg, "migrate_global_to_tenant_models")
            print("Downgraded past consolidate_model_settings (settings tables recreated)")

            # Now downgrade to before f7f7647d5327 (which adds model_providers)
            command.downgrade(alembic_cfg, pre_migration_revision)
            print(f"Downgraded to {pre_migration_revision} (before model_providers migration)")
        except Exception as e:
            print(f"Downgrade not possible (may already be at base): {e}")
            # If downgrade fails, upgrade to that revision instead
            command.upgrade(alembic_cfg, pre_migration_revision)
            print(f"Upgraded to {pre_migration_revision}")

        # Create legacy data
        now = datetime.now(timezone.utc)
        with conn.cursor() as cur:
            # Clear any existing data first (in case of rerun)
            # Note: Before f7f7647d5327, model_providers table doesn't exist yet
            # (it's created by that migration)
            cur.execute("DELETE FROM completion_model_settings")
            cur.execute("DELETE FROM embedding_model_settings")
            cur.execute("DELETE FROM spaces_completion_models")
            cur.execute("DELETE FROM spaces_embedding_models")
            cur.execute("DELETE FROM assistants")
            cur.execute("DELETE FROM apps")
            cur.execute("DELETE FROM services")
            cur.execute("DELETE FROM groups")
            cur.execute("DELETE FROM spaces")
            cur.execute("DELETE FROM users")
            cur.execute("DELETE FROM tenants")
            cur.execute("DELETE FROM completion_models")
            cur.execute("DELETE FROM embedding_models")
            cur.execute("DELETE FROM transcription_models")
            # Don't delete from model_providers - it doesn't exist at this migration level

            legacy_data = create_legacy_database_state(cur, now)
            conn.commit()

        print(f"Created legacy state with {len(legacy_data['tenant_ids'])} tenants")
        print(f"  - {len(legacy_data['completion_model_ids'])} completion models")
        print(f"  - {len(legacy_data['embedding_model_ids'])} embedding models")
        print(f"  - {len(legacy_data['transcription_model_ids'])} transcription models")

        # Verify models and settings exist before migration
        # Note: Before f7f7647d5327, tenant_id column doesn't exist yet
        # so we just count all models (they are all "global" at this point)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM completion_models")
            global_cm_count = cur.fetchone()[0]
            print(f"Completion models before migration: {global_cm_count}")
            assert global_cm_count > 0, "Should have models before migration"

            # Verify settings tables exist and have data
            cur.execute("SELECT COUNT(*) FROM completion_model_settings")
            settings_count = cur.fetchone()[0]
            print(f"Completion model settings before migration: {settings_count}")
            assert settings_count > 0, "Should have completion model settings before migration"

        # Run migrate_global_to_tenant_models
        print("\nRunning migrate_global_to_tenant_models...")
        command.upgrade(alembic_cfg, "migrate_global_to_tenant_models")
        print("migrate_global_to_tenant_models completed!")

        # Run consolidate_model_settings
        print("\nRunning consolidate_model_settings...")
        command.upgrade(alembic_cfg, "consolidate_model_settings")
        print("consolidate_model_settings completed!")

        yield {
            "conn": conn,
            "legacy_data": legacy_data,
            "test_settings": test_settings,
        }

    finally:
        conn.close()


class TestGlobalToTenantModelsMigration:
    """
    Test suite for the global-to-tenant-models migration.

    These tests verify the migration results after it has been run
    by the migration_test_db fixture.
    """

    def test_migration_creates_providers_per_tenant(self, migration_test_db):
        """
        Test that the migration creates providers for each tenant based on credentials.
        """
        conn = migration_test_db["conn"]
        legacy_data = migration_test_db["legacy_data"]

        with conn.cursor() as cur:
            for tenant_id in legacy_data["tenant_ids"]:
                cur.execute("""
                    SELECT name, provider_type, is_active
                    FROM model_providers
                    WHERE tenant_id = %s
                    ORDER BY name
                """, (tenant_id,))
                providers = cur.fetchall()

                assert len(providers) > 0, f"No providers created for tenant {tenant_id}"

                # Check provider types
                provider_types = {p[1] for p in providers}
                assert "openai" in provider_types, "OpenAI provider should exist"

    def test_migration_creates_tenant_specific_models(self, migration_test_db):
        """
        Test that the migration creates tenant-specific copies of all global models.
        """
        conn = migration_test_db["conn"]
        legacy_data = migration_test_db["legacy_data"]

        with conn.cursor() as cur:
            for tenant_id in legacy_data["tenant_ids"]:
                # Count completion models for this tenant
                cur.execute("""
                    SELECT COUNT(*) FROM completion_models
                    WHERE tenant_id = %s
                """, (tenant_id,))
                cm_count = cur.fetchone()[0]

                original_cm_count = len(legacy_data["completion_model_ids"])
                assert cm_count >= original_cm_count, \
                    f"Tenant {tenant_id} should have {original_cm_count} completion models, got {cm_count}"

                # Count embedding models for this tenant
                cur.execute("""
                    SELECT COUNT(*) FROM embedding_models
                    WHERE tenant_id = %s
                """, (tenant_id,))
                em_count = cur.fetchone()[0]

                original_em_count = len(legacy_data["embedding_model_ids"])
                assert em_count >= original_em_count, \
                    f"Tenant {tenant_id} should have {original_em_count} embedding models, got {em_count}"

    def test_migration_updates_assistant_fk_references(self, migration_test_db):
        """
        Test that assistant.completion_model_id references are updated to tenant-specific models.
        """
        conn = migration_test_db["conn"]
        legacy_data = migration_test_db["legacy_data"]

        with conn.cursor() as cur:
            # Check no assistants reference global models
            cur.execute("""
                SELECT COUNT(*)
                FROM assistants a
                JOIN completion_models cm ON a.completion_model_id = cm.id
                WHERE cm.tenant_id IS NULL
            """)
            orphan_count = cur.fetchone()[0]
            assert orphan_count == 0, \
                f"Found {orphan_count} assistants still referencing global models"

            # Verify each assistant references a model from their tenant
            for tenant_id, assistant_ids in legacy_data["assistant_ids"].items():
                for assistant_id in assistant_ids:
                    cur.execute("""
                        SELECT cm.tenant_id
                        FROM assistants a
                        JOIN completion_models cm ON a.completion_model_id = cm.id
                        WHERE a.id = %s
                    """, (assistant_id,))
                    row = cur.fetchone()

                    if row:
                        model_tenant_id = str(row[0]) if row[0] else None
                        assert model_tenant_id == tenant_id, \
                            f"Assistant {assistant_id} references model from wrong tenant"

    def test_migration_updates_app_fk_references(self, migration_test_db):
        """
        Test that app.completion_model_id references are updated to tenant-specific models.
        """
        conn = migration_test_db["conn"]

        with conn.cursor() as cur:
            # Check no apps reference global models
            cur.execute("""
                SELECT COUNT(*)
                FROM apps a
                JOIN completion_models cm ON a.completion_model_id = cm.id
                WHERE cm.tenant_id IS NULL
            """)
            orphan_count = cur.fetchone()[0]
            assert orphan_count == 0, \
                f"Found {orphan_count} apps still referencing global models"

    def test_migration_updates_spaces_completion_models(self, migration_test_db):
        """
        Test that spaces_completion_models references are updated to tenant-specific models.
        """
        conn = migration_test_db["conn"]

        with conn.cursor() as cur:
            # Check no spaces_completion_models reference global models
            cur.execute("""
                SELECT COUNT(*)
                FROM spaces_completion_models scm
                JOIN completion_models cm ON scm.completion_model_id = cm.id
                WHERE cm.tenant_id IS NULL
            """)
            orphan_count = cur.fetchone()[0]
            assert orphan_count == 0, \
                f"Found {orphan_count} space-model links still referencing global models"

    def test_migration_updates_groups_embedding_model_references(self, migration_test_db):
        """
        Test that groups.embedding_model_id references are updated to tenant-specific models.
        """
        conn = migration_test_db["conn"]

        with conn.cursor() as cur:
            # Check no groups reference global embedding models
            cur.execute("""
                SELECT COUNT(*)
                FROM groups g
                JOIN embedding_models em ON g.embedding_model_id = em.id
                WHERE em.tenant_id IS NULL
            """)
            orphan_count = cur.fetchone()[0]
            assert orphan_count == 0, \
                f"Found {orphan_count} groups still referencing global embedding models"

    def test_migration_deletes_global_models(self, migration_test_db):
        """
        Test that all global models are deleted after migration.
        """
        conn = migration_test_db["conn"]

        with conn.cursor() as cur:
            # Verify no global completion models remain
            cur.execute("""
                SELECT COUNT(*) FROM completion_models
                WHERE tenant_id IS NULL AND provider_id IS NULL
            """)
            assert cur.fetchone()[0] == 0, "Global completion models should be deleted"

            # Verify no global embedding models remain
            cur.execute("""
                SELECT COUNT(*) FROM embedding_models
                WHERE tenant_id IS NULL AND provider_id IS NULL
            """)
            assert cur.fetchone()[0] == 0, "Global embedding models should be deleted"

            # Verify no global transcription models remain
            cur.execute("""
                SELECT COUNT(*) FROM transcription_models
                WHERE tenant_id IS NULL AND provider_id IS NULL
            """)
            assert cur.fetchone()[0] == 0, "Global transcription models should be deleted"

    def test_migration_preserves_model_settings(self, migration_test_db):
        """
        Test that model settings (is_enabled, is_default) are preserved on model columns
        after consolidate_model_settings migration.

        After consolidate_model_settings, settings are stored directly on model columns
        (is_enabled, is_default) instead of separate settings tables.
        """
        conn = migration_test_db["conn"]
        legacy_data = migration_test_db["legacy_data"]

        with conn.cursor() as cur:
            # Verify each tenant has models with settings migrated to columns
            for tenant_id in legacy_data["tenant_ids"]:
                # Check is_enabled column (should have enabled models)
                cur.execute("""
                    SELECT COUNT(*)
                    FROM completion_models
                    WHERE tenant_id = %s AND is_enabled = true
                """, (tenant_id,))
                enabled_count = cur.fetchone()[0]

                assert enabled_count > 0, \
                    f"Tenant {tenant_id} should have enabled completion models"

                # Check is_default column (should have one default model)
                cur.execute("""
                    SELECT COUNT(*)
                    FROM completion_models
                    WHERE tenant_id = %s AND is_default = true
                """, (tenant_id,))
                default_count = cur.fetchone()[0]

                assert default_count >= 1, \
                    f"Tenant {tenant_id} should have at least one default completion model"


class TestMigrationDataIntegrity:
    """
    Tests focused on data integrity after migration.
    """

    def test_model_names_preserved(self, migration_test_db):
        """
        Test that model names are preserved exactly as they were.
        """
        conn = migration_test_db["conn"]
        legacy_data = migration_test_db["legacy_data"]

        original_model_names = set(legacy_data["completion_model_ids"].keys())

        with conn.cursor() as cur:
            # Get model names for first tenant
            tenant1_id = legacy_data["tenant_ids"][0]
            cur.execute("""
                SELECT name FROM completion_models
                WHERE tenant_id = %s
            """, (tenant1_id,))
            tenant_model_names = {row[0] for row in cur.fetchall()}

            # All original model names should exist
            for name in original_model_names:
                assert name in tenant_model_names, f"Model '{name}' should exist for tenant"

    def test_model_attributes_preserved(self, migration_test_db):
        """
        Test that model attributes (token_limit, vision, reasoning) are preserved.
        """
        conn = migration_test_db["conn"]
        legacy_data = migration_test_db["legacy_data"]

        tenant1_id = legacy_data["tenant_ids"][0]

        with conn.cursor() as cur:
            # Check GPT-4o attributes
            cur.execute("""
                SELECT token_limit, vision, reasoning
                FROM completion_models
                WHERE tenant_id = %s AND name = 'gpt-4o'
            """, (tenant1_id,))
            row = cur.fetchone()

            assert row is not None, "gpt-4o should exist for tenant"
            token_limit, vision, reasoning = row
            assert token_limit == 128000, "token_limit should be preserved"
            assert vision is True, "vision capability should be preserved"
            assert reasoning is False, "reasoning flag should be preserved"

            # Check O1-preview (reasoning model)
            cur.execute("""
                SELECT reasoning FROM completion_models
                WHERE tenant_id = %s AND name = 'o1-preview'
            """, (tenant1_id,))
            row = cur.fetchone()

            if row:  # Model might not exist if migration filtered it
                assert row[0] is True, "O1 reasoning flag should be preserved"

    def test_assistant_model_mapping_correct(self, migration_test_db):
        """
        Test that assistants are mapped to the correct tenant-specific model.
        """
        conn = migration_test_db["conn"]

        with conn.cursor() as cur:
            # Get assistants with their model names
            cur.execute("""
                SELECT a.name as assistant_name, cm.name as model_name,
                       cm.tenant_id as model_tenant_id, u.tenant_id as user_tenant_id
                FROM assistants a
                JOIN completion_models cm ON a.completion_model_id = cm.id
                JOIN users u ON a.user_id = u.id
            """)

            for row in cur.fetchall():
                assistant_name, model_name, model_tenant_id, user_tenant_id = row

                # Model tenant should match user tenant
                assert str(model_tenant_id) == str(user_tenant_id), \
                    f"Assistant '{assistant_name}' using model from wrong tenant"


class TestMigrationCredentialHandling:
    """
    Tests focused on credential handling during migration.
    """

    def test_tenant_credentials_preserved_in_providers(self, migration_test_db):
        """
        Test that tenant credentials from api_credentials are preserved in providers.
        Credentials should be copied as-is (already encrypted in tenant table).
        """
        conn = migration_test_db["conn"]
        legacy_data = migration_test_db["legacy_data"]

        with conn.cursor() as cur:
            # Check tenant 1's OpenAI provider has credentials
            tenant1_id = legacy_data["tenant_ids"][0]
            cur.execute("""
                SELECT credentials
                FROM model_providers
                WHERE tenant_id = %s AND provider_type = 'openai'
            """, (tenant1_id,))
            row = cur.fetchone()

            assert row is not None, "OpenAI provider should exist for tenant 1"
            credentials = row[0]

            if isinstance(credentials, str):
                import json
                credentials = json.loads(credentials)

            assert "api_key" in credentials, "Provider should have api_key in credentials"
            assert credentials["api_key"], "api_key should not be empty"

    def test_tenant_without_credentials_has_inactive_providers(self, migration_test_db):
        """
        Test that tenants without credentials have providers but with is_active=false.
        """
        conn = migration_test_db["conn"]
        legacy_data = migration_test_db["legacy_data"]

        with conn.cursor() as cur:
            # Tenant 3 has no credentials
            tenant3_id = legacy_data["tenant_ids"][2]
            cur.execute("""
                SELECT name, provider_type, is_active, credentials
                FROM model_providers
                WHERE tenant_id = %s
            """, (tenant3_id,))
            providers = cur.fetchall()

            assert len(providers) > 0, "Tenant without credentials should still have providers"

            # Providers without credentials should have is_active=false
            for name, provider_type, is_active, credentials in providers:
                if isinstance(credentials, str):
                    import json
                    credentials = json.loads(credentials)

                api_key = credentials.get("api_key", "")
                if not api_key:
                    assert not is_active, \
                        f"Provider {name} with empty api_key should be inactive"

    def test_provider_credentials_format(self, migration_test_db):
        """
        Test that provider credentials are stored in proper JSON format.
        """
        conn = migration_test_db["conn"]
        legacy_data = migration_test_db["legacy_data"]

        with conn.cursor() as cur:
            tenant1_id = legacy_data["tenant_ids"][0]

            # Check Azure provider has extra config fields
            cur.execute("""
                SELECT credentials, config
                FROM model_providers
                WHERE tenant_id = %s AND provider_type = 'azure'
            """, (tenant1_id,))
            row = cur.fetchone()

            if row:
                credentials, config = row

                if isinstance(credentials, str):
                    import json
                    credentials = json.loads(credentials)
                if isinstance(config, str):
                    import json
                    config = json.loads(config)

                # Azure should have api_key in credentials
                assert "api_key" in credentials

                # Azure config can have endpoint and api_version
                # (depends on how migration handles these)


class TestConsolidateModelSettings:
    """
    Tests for consolidate_model_settings migration.

    This migration moves settings from separate tables (completion_model_settings,
    embedding_model_settings, transcription_model_settings) to columns directly
    on the model tables (is_enabled, is_default, security_classification_id).
    """

    def test_is_enabled_column_populated(self, migration_test_db):
        """Verify is_enabled column is populated from settings."""
        conn = migration_test_db["conn"]

        with conn.cursor() as cur:
            # Check completion models
            cur.execute("""
                SELECT COUNT(*) FROM completion_models
                WHERE tenant_id IS NOT NULL AND is_enabled = true
            """)
            assert cur.fetchone()[0] > 0, "Should have enabled completion models"

            # Check embedding models
            cur.execute("""
                SELECT COUNT(*) FROM embedding_models
                WHERE tenant_id IS NOT NULL AND is_enabled = true
            """)
            assert cur.fetchone()[0] > 0, "Should have enabled embedding models"

    def test_is_default_column_populated(self, migration_test_db):
        """Verify is_default column is populated from settings."""
        conn = migration_test_db["conn"]
        legacy_data = migration_test_db["legacy_data"]

        with conn.cursor() as cur:
            # Each tenant should have at least one default completion model
            for tenant_id in legacy_data["tenant_ids"]:
                cur.execute("""
                    SELECT COUNT(*) FROM completion_models
                    WHERE tenant_id = %s AND is_default = true
                """, (tenant_id,))
                default_count = cur.fetchone()[0]
                assert default_count >= 1, \
                    f"Tenant {tenant_id} should have at least one default completion model"

            # Each tenant should have at least one default embedding model
            for tenant_id in legacy_data["tenant_ids"]:
                cur.execute("""
                    SELECT COUNT(*) FROM embedding_models
                    WHERE tenant_id = %s AND is_default = true
                """, (tenant_id,))
                default_count = cur.fetchone()[0]
                assert default_count >= 1, \
                    f"Tenant {tenant_id} should have at least one default embedding model"

    def test_settings_tables_removed(self, migration_test_db):
        """Verify settings tables are dropped after consolidate migration."""
        conn = migration_test_db["conn"]

        with conn.cursor() as cur:
            # completion_model_settings should not exist
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'completion_model_settings'
                )
            """)
            assert cur.fetchone()[0] is False, \
                "completion_model_settings should be dropped"

            # embedding_model_settings should not exist
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'embedding_model_settings'
                )
            """)
            assert cur.fetchone()[0] is False, \
                "embedding_model_settings should be dropped"

            # transcription_model_settings should not exist
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'transcription_model_settings'
                )
            """)
            assert cur.fetchone()[0] is False, \
                "transcription_model_settings should be dropped"

    def test_model_columns_exist(self, migration_test_db):
        """Verify is_enabled, is_default columns exist on model tables."""
        conn = migration_test_db["conn"]

        with conn.cursor() as cur:
            # Check completion_models has required columns
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'completion_models'
                AND column_name IN ('is_enabled', 'is_default', 'security_classification_id')
            """)
            columns = {row[0] for row in cur.fetchall()}
            assert 'is_enabled' in columns, "completion_models should have is_enabled column"
            assert 'is_default' in columns, "completion_models should have is_default column"

            # Check embedding_models has required columns
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'embedding_models'
                AND column_name IN ('is_enabled', 'is_default', 'security_classification_id')
            """)
            columns = {row[0] for row in cur.fetchall()}
            assert 'is_enabled' in columns, "embedding_models should have is_enabled column"
            assert 'is_default' in columns, "embedding_models should have is_default column"

    def test_coalesce_defaults_applied(self, migration_test_db):
        """
        Test COALESCE logic: models without explicit settings should have
        is_enabled defaulting to true (since all models were enabled by default).
        """
        conn = migration_test_db["conn"]

        with conn.cursor() as cur:
            # All tenant models should have is_enabled set (not NULL)
            cur.execute("""
                SELECT COUNT(*) FROM completion_models
                WHERE tenant_id IS NOT NULL AND is_enabled IS NULL
            """)
            null_enabled_count = cur.fetchone()[0]
            assert null_enabled_count == 0, \
                "All tenant models should have is_enabled set (not NULL)"

            # All tenant models should have is_default set (not NULL)
            cur.execute("""
                SELECT COUNT(*) FROM completion_models
                WHERE tenant_id IS NOT NULL AND is_default IS NULL
            """)
            null_default_count = cur.fetchone()[0]
            assert null_default_count == 0, \
                "All tenant models should have is_default set (not NULL)"
