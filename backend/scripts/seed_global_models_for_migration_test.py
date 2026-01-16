#!/usr/bin/env python3
"""
Seed global AI models for testing the migration locally.

This script creates:
1. Tenants with api_credentials (simulating pre-migration state)
2. Global models (tenant_id=NULL, provider_id=NULL)
3. Model settings so models are visible in UI

Usage:
    python scripts/seed_global_models_for_migration_test.py

After running this, you can:
1. View models in UI (should see global models)
2. Run: alembic upgrade migrate_global_to_tenant_models
3. View models in UI again (should see tenant-specific models)
4. Verify providers were created

Note: This script is for LOCAL TESTING ONLY. Remove before production.
"""

import asyncio
import sys
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone

# Add backend to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir / "src"))

from sqlalchemy import text
from intric.database.database import sessionmanager
from intric.main.config import get_settings


async def seed_global_models():
    """Seed global models and test tenants."""

    # Initialize database connection
    settings = get_settings()
    sessionmanager.init(settings.database_url)

    async with sessionmanager.connect() as conn:
        print("\n" + "="*70)
        print("SEEDING GLOBAL MODELS FOR MIGRATION TEST")
        print("="*70)

        # =====================================================================
        # 1. Clean existing TEST data only (keep production data)
        # =====================================================================
        print("\n[1/6] Cleaning existing test data...")

        # Only delete migration test-related data
        await conn.execute(text("""
            DELETE FROM completion_model_settings
            WHERE tenant_id IN (SELECT id FROM tenants WHERE name LIKE 'Migration Test Tenant%')
        """))
        await conn.execute(text("""
            DELETE FROM embedding_model_settings
            WHERE tenant_id IN (SELECT id FROM tenants WHERE name LIKE 'Migration Test Tenant%')
        """))
        await conn.execute(text("""
            DELETE FROM transcription_model_settings
            WHERE tenant_id IN (SELECT id FROM tenants WHERE name LIKE 'Migration Test Tenant%')
        """))
        await conn.execute(text("""
            DELETE FROM spaces
            WHERE tenant_id IN (SELECT id FROM tenants WHERE name LIKE 'Migration Test Tenant%')
        """))
        await conn.execute(text("""
            DELETE FROM users
            WHERE tenant_id IN (SELECT id FROM tenants WHERE name LIKE 'Migration Test Tenant%')
        """))
        await conn.execute(text("DELETE FROM tenants WHERE name LIKE 'Migration Test Tenant%'"))

        # Clean global models (these will be recreated)
        await conn.execute(text("DELETE FROM completion_model_settings WHERE completion_model_id IN (SELECT id FROM completion_models WHERE tenant_id IS NULL)"))
        await conn.execute(text("DELETE FROM embedding_model_settings WHERE embedding_model_id IN (SELECT id FROM embedding_models WHERE tenant_id IS NULL)"))
        await conn.execute(text("DELETE FROM transcription_model_settings WHERE transcription_model_id IN (SELECT id FROM transcription_models WHERE tenant_id IS NULL)"))
        await conn.execute(text("DELETE FROM spaces_completion_models WHERE completion_model_id IN (SELECT id FROM completion_models WHERE tenant_id IS NULL)"))
        await conn.execute(text("DELETE FROM spaces_embedding_models WHERE embedding_model_id IN (SELECT id FROM embedding_models WHERE tenant_id IS NULL)"))
        await conn.execute(text("DELETE FROM completion_models WHERE tenant_id IS NULL"))
        await conn.execute(text("DELETE FROM embedding_models WHERE tenant_id IS NULL"))
        await conn.execute(text("DELETE FROM transcription_models WHERE tenant_id IS NULL"))

        # Clean providers (will be recreated by migration)
        await conn.execute(text("DELETE FROM model_providers"))

        print("   ✓ Cleaned test data (kept existing users/tenants)")

        # =====================================================================
        # 2. Create test tenants
        # =====================================================================
        print("\n[2/6] Creating test tenants...")

        tenant1_id = str(uuid4())
        tenant2_id = str(uuid4())
        tenant3_id = str(uuid4())
        now = datetime.now(timezone.utc)

        # Tenant 1: Full credentials (OpenAI + Azure)
        await conn.execute(text("""
            INSERT INTO tenants (id, name, quota_limit, api_credentials, state, created_at, updated_at)
            VALUES (
                :id, :name, 1000000,
                CAST(:creds AS jsonb),
                'active', :now, :now
            )
        """), {
            "id": tenant1_id,
            "name": "Migration Test Tenant 1 (Full Creds)",
            "creds": '{"openai": {"api_key": "sk-test-key-1"}, "azure": {"api_key": "azure-test-1"}}',
            "now": now
        })

        # Tenant 2: OpenAI only
        await conn.execute(text("""
            INSERT INTO tenants (id, name, quota_limit, api_credentials, state, created_at, updated_at)
            VALUES (
                :id, :name, 1000000,
                CAST(:creds AS jsonb),
                'active', :now, :now
            )
        """), {
            "id": tenant2_id,
            "name": "Migration Test Tenant 2 (OpenAI Only)",
            "creds": '{"openai": {"api_key": "sk-test-key-2"}}',
            "now": now
        })

        # Tenant 3: No credentials
        await conn.execute(text("""
            INSERT INTO tenants (id, name, quota_limit, api_credentials, state, created_at, updated_at)
            VALUES (
                :id, :name, 1000000,
                CAST(:creds AS jsonb),
                'active', :now, :now
            )
        """), {
            "id": tenant3_id,
            "name": "Migration Test Tenant 3 (No Creds)",
            "creds": '{}',
            "now": now
        })

        print("   ✓ Created 3 test tenants")

        # =====================================================================
        # 3. Create test users with login credentials
        # =====================================================================
        print("\n[3/8] Creating test users...")

        # Create extension for password hashing if not exists
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))

        # Get Owner role ID
        owner_role_result = await conn.execute(text("SELECT id FROM predefined_roles WHERE name = 'Owner'"))
        owner_role_id = owner_role_result.scalar()

        # User 1 for Tenant 1
        salt1 = await conn.execute(text("SELECT gen_salt('bf')"))
        salt1 = salt1.scalar()
        hashed_pw1 = await conn.execute(text("SELECT crypt(:pw, :salt)"), {"pw": "test123", "salt": salt1})
        hashed_pw1 = hashed_pw1.scalar()
        user1_id = str(uuid4())

        await conn.execute(text("""
            INSERT INTO users (
                id, tenant_id, email, username, salt, password,
                email_verified, is_active, used_tokens, state,
                created_at, updated_at
            ) VALUES (
                :id, :tenant_id, :email, :username, :salt, :password,
                true, true, 0, 'active', :now, :now
            )
        """), {
            "id": user1_id, "tenant_id": tenant1_id,
            "email": "admin1@test.com", "username": "admin1",
            "salt": salt1, "password": hashed_pw1, "now": now
        })

        # Assign Owner role to user1
        await conn.execute(text("""
            INSERT INTO users_predefined_roles (user_id, predefined_role_id)
            VALUES (:user_id, :role_id)
        """), {"user_id": user1_id, "role_id": owner_role_id})

        # User 2 for Tenant 2
        salt2 = await conn.execute(text("SELECT gen_salt('bf')"))
        salt2 = salt2.scalar()
        hashed_pw2 = await conn.execute(text("SELECT crypt(:pw, :salt)"), {"pw": "test123", "salt": salt2})
        hashed_pw2 = hashed_pw2.scalar()
        user2_id = str(uuid4())

        await conn.execute(text("""
            INSERT INTO users (
                id, tenant_id, email, username, salt, password,
                email_verified, is_active, used_tokens, state,
                created_at, updated_at
            ) VALUES (
                :id, :tenant_id, :email, :username, :salt, :password,
                true, true, 0, 'active', :now, :now
            )
        """), {
            "id": user2_id, "tenant_id": tenant2_id,
            "email": "admin2@test.com", "username": "admin2",
            "salt": salt2, "password": hashed_pw2, "now": now
        })

        # Assign Owner role to user2
        await conn.execute(text("""
            INSERT INTO users_predefined_roles (user_id, predefined_role_id)
            VALUES (:user_id, :role_id)
        """), {"user_id": user2_id, "role_id": owner_role_id})

        # User 3 for Tenant 3
        salt3 = await conn.execute(text("SELECT gen_salt('bf')"))
        salt3 = salt3.scalar()
        hashed_pw3 = await conn.execute(text("SELECT crypt(:pw, :salt)"), {"pw": "test123", "salt": salt3})
        hashed_pw3 = hashed_pw3.scalar()
        user3_id = str(uuid4())

        await conn.execute(text("""
            INSERT INTO users (
                id, tenant_id, email, username, salt, password,
                email_verified, is_active, used_tokens, state,
                created_at, updated_at
            ) VALUES (
                :id, :tenant_id, :email, :username, :salt, :password,
                true, true, 0, 'active', :now, :now
            )
        """), {
            "id": user3_id, "tenant_id": tenant3_id,
            "email": "admin3@test.com", "username": "admin3",
            "salt": salt3, "password": hashed_pw3, "now": now
        })

        # Assign Owner role to user3
        await conn.execute(text("""
            INSERT INTO users_predefined_roles (user_id, predefined_role_id)
            VALUES (:user_id, :role_id)
        """), {"user_id": user3_id, "role_id": owner_role_id})

        print("   ✓ Created 3 admin users with Owner role (password: test123)")

        # =====================================================================
        # 4. Create global completion models
        # =====================================================================
        print("\n[4/8] Creating global completion models...")

        # All models from ai_models.yml
        # Format: (name, nickname, family, token_limit, vision, reasoning, is_deprecated, stability, hosting, org, deployment_name, litellm_model_name, base_url, open_source, nr_billion_parameters)
        completion_models = [
            # OpenAI models
            ("gpt-4-turbo", "GPT-4", "openai", 128000, True, False, False, "stable", "usa", "OpenAI", None, None, None, False, None),
            ("gpt-3.5-turbo", "ChatGPT", "openai", 16385, False, False, False, "stable", "usa", "OpenAI", None, None, None, False, None),
            ("o3-mini", "o3-mini", "openai", 200000, False, True, False, "stable", "usa", "OpenAI", None, None, None, False, None),
            ("gpt-4o", "GPT-4o", "openai", 128000, True, False, False, "stable", "usa", "OpenAI", None, None, None, False, None),
            ("gpt-4o-mini", "GPT-4o mini", "openai", 128000, True, False, False, "stable", "usa", "OpenAI", None, None, None, False, None),

            # Claude models
            ("claude-3-opus-latest", "Claude 3 Opus", "claude", 200000, True, False, False, "stable", "usa", "Anthropic", None, None, None, False, None),
            ("claude-3-sonnet-20240229", "Claude 3 Sonnet", "claude", 200000, True, False, False, "stable", "usa", "Anthropic", None, None, None, False, None),
            ("claude-3-haiku-20240307", "Claude 3 Haiku", "claude", 200000, True, False, False, "stable", "usa", "Anthropic", None, None, None, False, None),
            ("claude-3-5-sonnet-latest", "Claude 3.5 Sonnet", "claude", 200000, True, False, False, "stable", "usa", "Anthropic", None, None, None, False, None),
            ("claude-3-7-sonnet-latest", "Claude 3.7 Sonnet", "claude", 200000, True, False, False, "stable", "usa", "Anthropic", None, None, None, False, None),

            # Azure models
            ("gpt-4-azure", "GPT-4 (Azure)", "azure", 128000, True, False, False, "stable", "swe", "Microsoft", "gpt-4", None, None, False, None),
            ("gpt-4o-azure", "GPT-4o (Azure)", "azure", 128000, True, False, False, "stable", "swe", "Microsoft", "gpt-4o-2", None, None, False, None),
            ("gpt-4o-mini-azure", "GPT-4o mini (Azure)", "azure", 128000, True, False, False, "stable", "swe", "Microsoft", "gpt-4o-mini", None, None, False, None),
            ("o3-mini-azure", "o3-mini (Azure)", "azure", 200000, False, True, False, "stable", "swe", "Microsoft", "o3-mini", None, None, False, None),
            ("gpt-5-azure", "GPT-5 (Azure)", "azure", 400000, True, True, False, "experimental", "swe", "Microsoft", "gpt-5", "azure/gpt-5", None, False, None),
            ("gpt-5-mini-azure", "GPT-5 mini (Azure)", "azure", 400000, True, True, False, "experimental", "swe", "Microsoft", "gpt-5-mini", "azure/gpt-5-mini", None, False, None),
            ("gpt-5-nano-azure", "GPT-5 nano (Azure)", "azure", 400000, True, True, False, "experimental", "swe", "Microsoft", "gpt-5-nano", "azure/gpt-5-nano", None, False, None),

            # Mistral models
            ("mistralai/Mixtral-8x7B-Instruct-v0.1", "Mixtral", "mistral", 16384, False, False, True, "experimental", "eu", "Mistral", None, None, None, False, None),
            ("mistral-large-latest", "Mistral Large", "mistral", 131000, False, False, False, "stable", "eu", "Mistral", None, None, None, False, None),

            # vLLM models
            ("Qwen/Qwen1.5-14B-Chat", "Qwen", "vllm", 32000, False, False, True, "experimental", "eu", "Alibaba", None, None, None, False, 14),
            ("meta-llama/Meta-Llama-3-8B-Instruct", "Llama 3", "vllm", 8192, False, False, True, "experimental", "eu", "Meta", None, None, None, True, 8),
            ("meta-llama/Meta-Llama-3.1-8B-Instruct", "Llama 3.1", "vllm", 128000, False, False, True, "experimental", "eu", "Meta", None, None, None, True, 8),
            ("google/gemma-3-27b-it", "Gemma 3", "vllm", 128000, False, False, False, "experimental", "eu", "Google", None, None, None, True, 27),

            # OVHCloud models
            ("Meta-Llama-3_3-70B-Instruct", "Llama 3.3", "ovhcloud", 128000, False, False, False, "stable", "eu", "Meta", None, None, "https://llama-3-3-70b-instruct.endpoints.kepler.ai.cloud.ovh.net/api/openai_compat/v1", True, 70),

            # GDM models (Swedish provider)
            ("gemma3-27b-it", "Gemma 3 27B", "openai", 128000, False, False, False, "stable", "swe", "GDM", None, "gdm/gemma3-27b-it", None, False, None),
        ]

        cm_ids = []
        for model_data in completion_models:
            name, nickname, family, token_limit, vision, reasoning, is_deprecated, stability, hosting, org, deployment_name, litellm_model_name, base_url, open_source, nr_billion_parameters = model_data
            cm_id = str(uuid4())
            cm_ids.append(cm_id)
            await conn.execute(text("""
                INSERT INTO completion_models (
                    id, tenant_id, provider_id, name, nickname, family,
                    token_limit, vision, reasoning, is_deprecated,
                    stability, hosting, org, deployment_name, litellm_model_name,
                    base_url, open_source, nr_billion_parameters,
                    created_at, updated_at
                ) VALUES (
                    :id, NULL, NULL, :name, :nickname, :family,
                    :token_limit, :vision, :reasoning, :is_deprecated,
                    :stability, :hosting, :org, :deployment_name, :litellm_model_name,
                    :base_url, :open_source, :nr_billion_parameters,
                    :now, :now
                )
            """), {
                "id": cm_id, "name": name, "nickname": nickname, "family": family,
                "token_limit": token_limit, "vision": vision, "reasoning": reasoning,
                "is_deprecated": is_deprecated, "stability": stability, "hosting": hosting,
                "org": org, "deployment_name": deployment_name, "litellm_model_name": litellm_model_name,
                "base_url": base_url, "open_source": open_source, "nr_billion_parameters": nr_billion_parameters,
                "now": now
            })

        print(f"   ✓ Created {len(completion_models)} global completion models")

        # =====================================================================
        # 5. Create global embedding models
        # =====================================================================
        print("\n[5/8] Creating global embedding models...")

        # All embedding models from ai_models.yml
        # Format: (name, family, dimensions, max_input, max_batch_size, is_deprecated, stability, hosting, org, litellm_model_name, open_source)
        embedding_models = [
            # OpenAI models
            ("text-embedding-3-small", "openai", 512, 8191, 32, False, "stable", "usa", "OpenAI", None, False),
            ("text-embedding-ada-002", "openai", None, 8191, 32, False, "stable", "usa", "OpenAI", None, False),

            # E5/Berget models
            ("multilingual-e5-large", "e5", None, 1400, 32, False, "experimental", "swe", "Berget", "berget/intfloat/multilingual-e5-large", True),
            ("multilingual-e5-large-instruct", "e5", None, 1400, 32, False, "experimental", "swe", "GDM", "gdm/multilingual-e5-large-instruct", True),

            # Azure embedding models
            ("text-embedding-3-large-azure", "openai", 3072, 8191, 16, False, "stable", "swe", "Microsoft", "azure/text-embedding-3-large", False),
        ]

        em_ids = []
        for model_data in embedding_models:
            name, family, dimensions, max_input, max_batch_size, is_deprecated, stability, hosting, org, litellm_model_name, open_source = model_data
            em_id = str(uuid4())
            em_ids.append(em_id)
            await conn.execute(text("""
                INSERT INTO embedding_models (
                    id, tenant_id, provider_id, name, family,
                    dimensions, max_input, max_batch_size, is_deprecated,
                    stability, hosting, org, litellm_model_name, open_source,
                    created_at, updated_at
                ) VALUES (
                    :id, NULL, NULL, :name, :family,
                    :dimensions, :max_input, :max_batch_size, :is_deprecated,
                    :stability, :hosting, :org, :litellm_model_name, :open_source,
                    :now, :now
                )
            """), {
                "id": em_id, "name": name, "family": family,
                "dimensions": dimensions, "max_input": max_input,
                "max_batch_size": max_batch_size, "is_deprecated": is_deprecated,
                "stability": stability, "hosting": hosting, "org": org,
                "litellm_model_name": litellm_model_name, "open_source": open_source,
                "now": now
            })

        print(f"   ✓ Created {len(embedding_models)} global embedding models")

        # =====================================================================
        # 6. Create global transcription models
        # =====================================================================
        print("\n[6/8] Creating global transcription models...")

        transcription_models = [
            ("whisper-1", "Whisper", "openai"),
            ("whisper-large-v3", "Whisper Large V3", "openai"),
        ]

        tm_ids = []
        for model_name, name, family in transcription_models:
            tm_id = str(uuid4())
            tm_ids.append(tm_id)
            await conn.execute(text("""
                INSERT INTO transcription_models (
                    id, tenant_id, provider_id, model_name, name, family,
                    is_deprecated, stability, hosting, base_url, created_at, updated_at
                ) VALUES (
                    :id, NULL, NULL, :model_name, :name, :family,
                    false, 'stable', 'usa', '', :now, :now
                )
            """), {
                "id": tm_id, "model_name": model_name, "name": name,
                "family": family, "now": now
            })

        print(f"   ✓ Created {len(transcription_models)} global transcription models")

        # =====================================================================
        # 7. Create spaces for users
        # =====================================================================
        print("\n[7/8] Creating spaces...")

        # Get user IDs
        result = await conn.execute(text("SELECT id, tenant_id FROM users ORDER BY email"))
        users = result.fetchall()

        for user_id, tenant_id in users:
            # Create personal space for each user
            await conn.execute(text("""
                INSERT INTO spaces (id, tenant_id, user_id, name, created_at, updated_at)
                VALUES (:id, :tenant_id, :user_id, 'Personal', :now, :now)
            """), {
                "id": str(uuid4()), "tenant_id": tenant_id,
                "user_id": user_id, "now": now
            })

        print(f"   ✓ Created personal spaces for {len(users)} users")

        # =====================================================================
        # 8. Create model settings for all tenants
        # =====================================================================
        print("\n[8/8] Creating model settings...")

        for tenant_id in [tenant1_id, tenant2_id, tenant3_id]:
            # Completion model settings
            for cm_id in cm_ids:
                await conn.execute(text("""
                    INSERT INTO completion_model_settings (
                        tenant_id, completion_model_id, is_org_enabled, is_org_default,
                        created_at, updated_at
                    ) VALUES (:tenant_id, :model_id, true, false, :now, :now)
                """), {"tenant_id": tenant_id, "model_id": cm_id, "now": now})

            # Embedding model settings
            for em_id in em_ids:
                await conn.execute(text("""
                    INSERT INTO embedding_model_settings (
                        tenant_id, embedding_model_id, is_org_enabled, is_org_default,
                        created_at, updated_at
                    ) VALUES (:tenant_id, :model_id, true, false, :now, :now)
                """), {"tenant_id": tenant_id, "model_id": em_id, "now": now})

            # Transcription model settings
            for tm_id in tm_ids:
                await conn.execute(text("""
                    INSERT INTO transcription_model_settings (
                        tenant_id, transcription_model_id, is_org_enabled, is_org_default,
                        created_at, updated_at
                    ) VALUES (:tenant_id, :model_id, true, false, :now, :now)
                """), {"tenant_id": tenant_id, "model_id": tm_id, "now": now})

        print("   ✓ Created model settings for all tenants")

        # =====================================================================
        # Summary
        # =====================================================================
        print("\n" + "="*70)
        print("✓ SEEDING COMPLETE")
        print("="*70)
        print("\nCreated:")
        print("  • 3 test tenants with different credential configurations")
        print(f"  • {len(completion_models)} global completion models")
        print(f"  • {len(embedding_models)} global embedding models")
        print(f"  • {len(transcription_models)} global transcription models")
        print("  • Model settings for all tenants")

        print("\nModel families included:")
        print("  • openai (GPT-4, GPT-4o, etc.)")
        print("  • claude (Claude 3, Claude 3.5, etc.)")
        print("  • azure (GPT-4 Azure, GPT-4o Azure, etc.)")
        print("  • mistral (Mixtral, Mistral Large)")
        print("  • vllm (Qwen, Llama 3, Gemma)")
        print("  • ovhcloud (Llama 3.3)")
        print("  • e5/berget (multilingual-e5-large)")

        print("\nTest tenants & login credentials:")
        print(f"  1. {tenant1_id} - Full creds (OpenAI + Azure)")
        print("     → Login: admin1@test.com / test123")
        print(f"  2. {tenant2_id} - OpenAI only")
        print("     → Login: admin2@test.com / test123")
        print(f"  3. {tenant3_id} - No credentials")
        print("     → Login: admin3@test.com / test123")

        print("\nNext steps:")
        print("  1. Login to UI with one of the test users above")
        print("  2. Verify in UI: You should see global models")
        print("  3. Run migration: alembic upgrade migrate_global_to_tenant_models")
        print("  4. Login again and verify: Models should be tenant-specific")
        print("  5. Check providers: Should have providers for each family")
        print("\n" + "="*70 + "\n")

    # Cleanup
    await sessionmanager.close()


if __name__ == "__main__":
    asyncio.run(seed_global_models())
