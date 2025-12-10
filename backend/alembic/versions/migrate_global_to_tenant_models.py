"""migrate_global_to_tenant_models

Migrates global AI models (tenant_id=NULL) to tenant-specific models.
For each tenant:
1. Creates providers based on tenant api_credentials or ENV variables
2. Creates tenant-specific copies of all global models
3. Updates all FK references to point to tenant-specific models
4. Deletes global models after all tenants are migrated

Revision ID: migrate_global_to_tenant_models
Revises: f7f7647d5327
Create Date: 2025-12-09
"""

from alembic import op
from sqlalchemy import text
from uuid import uuid4
from datetime import datetime, timezone
import os
import json

# revision identifiers, used by Alembic
revision = 'migrate_global_to_tenant_models'
down_revision = 'f7f7647d5327'
branch_labels = None
depends_on = None


# =============================================================================
# CONFIGURATION
# =============================================================================

# Map model family to provider type
FAMILY_TO_PROVIDER_TYPE = {
    "openai": "openai",
    "azure": "azure",
    "claude": "anthropic",
    "anthropic": "anthropic",
    "mistral": "mistral",
    "vllm": "vllm",
    "ovhcloud": "ovhcloud",
    "berget": "berget",
    "e5": "berget",  # E5 models hosted by Berget
    "cohere": "cohere",
    "gemini": "gemini",
    "gdm": "gdm",
}

# Human-friendly provider names
PROVIDER_NAMES = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "azure": "Azure OpenAI",
    "mistral": "Mistral AI",
    "vllm": "vLLM",
    "ovhcloud": "OVHcloud",
    "berget": "Berget.ai",
    "cohere": "Cohere",
    "gemini": "Google Gemini",
    "gdm": "Google DeepMind",
}

# ENV variable names per provider
ENV_KEY_MAP = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "azure": "AZURE_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "vllm": "VLLM_API_KEY",
    "ovhcloud": "OVHCLOUD_API_KEY",
    "berget": "BERGET_API_KEY",
    "cohere": "COHERE_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "gdm": "GDM_API_KEY",
}


# =============================================================================
# ENCRYPTION SUPPORT
# =============================================================================

def get_fernet_instance():
    """Get Fernet instance if ENCRYPTION_KEY is configured.

    Returns None if encryption is not available (key not set or invalid).
    """
    encryption_key = os.environ.get("ENCRYPTION_KEY", "").strip()
    if not encryption_key:
        return None

    try:
        from cryptography.fernet import Fernet
        return Fernet(encryption_key.encode())
    except Exception as e:
        print(f"  Warning: Invalid ENCRYPTION_KEY, credentials will not be encrypted: {e}")
        return None


def encrypt_api_key(api_key: str, fernet) -> str:
    """Encrypt API key using Fernet, matching EncryptionService format.

    Format: enc:fernet:v1:<base64-ciphertext>

    Args:
        api_key: Plaintext API key to encrypt
        fernet: Fernet instance (or None to skip encryption)

    Returns:
        Encrypted string with version prefix, or original if fernet is None
    """
    if not fernet or not api_key:
        return api_key

    encrypted_bytes = fernet.encrypt(api_key.encode())
    ciphertext = encrypted_bytes.decode()
    return f"enc:fernet:v1:{ciphertext}"


def is_already_encrypted(value: str) -> bool:
    """Check if value is already encrypted with versioned format."""
    return value.startswith("enc:fernet:v") if value else False


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_provider_type_for_family(family: str) -> str:
    """Map model family to provider type."""
    if not family:
        return "openai"  # Default fallback
    return FAMILY_TO_PROVIDER_TYPE.get(family.lower(), family.lower())


def get_provider_name(provider_type: str) -> str:
    """Get human-friendly provider name."""
    return PROVIDER_NAMES.get(provider_type, provider_type.title())


def get_env_credentials(provider_type: str) -> dict:
    """Get credentials from environment variables."""
    env_key = ENV_KEY_MAP.get(provider_type)
    if not env_key:
        return {}

    api_key = os.environ.get(env_key, "")
    if not api_key:
        return {}

    credentials = {"api_key": api_key}

    # Azure needs extra config
    if provider_type == "azure":
        credentials["endpoint"] = os.environ.get("AZURE_ENDPOINT", "")
        credentials["api_version"] = os.environ.get("AZURE_API_VERSION", "2024-02-01")

    # vLLM needs endpoint
    if provider_type == "vllm":
        credentials["endpoint"] = os.environ.get("VLLM_MODEL_URL", "")

    return credentials


# =============================================================================
# PHASE 1: GET DATA
# =============================================================================

def get_active_tenants(conn):
    """Get all active tenants with their api_credentials."""
    result = conn.execute(text("""
        SELECT id, name, api_credentials
        FROM tenants
        WHERE state = 'active' OR state IS NULL
        ORDER BY created_at
    """))
    return result.fetchall()


def get_global_completion_models(conn):
    """Get all global completion models."""
    result = conn.execute(text("""
        SELECT id, name, nickname, family, token_limit, is_deprecated,
               nr_billion_parameters, hf_link, stability, hosting,
               description, deployment_name, org, vision, reasoning,
               base_url, litellm_model_name, open_source
        FROM completion_models
        WHERE tenant_id IS NULL AND provider_id IS NULL
        ORDER BY name
    """))
    return result.fetchall()


def get_global_embedding_models(conn):
    """Get all global embedding models."""
    result = conn.execute(text("""
        SELECT id, name, family, open_source, dimensions, max_input, max_batch_size,
               is_deprecated, hf_link, stability, hosting, description, org,
               litellm_model_name
        FROM embedding_models
        WHERE tenant_id IS NULL AND provider_id IS NULL
        ORDER BY name
    """))
    return result.fetchall()


def get_global_transcription_models(conn):
    """Get all global transcription models."""
    result = conn.execute(text("""
        SELECT id, name, model_name, open_source, is_deprecated,
               hf_link, family, stability, hosting, description, org, base_url
        FROM transcription_models
        WHERE tenant_id IS NULL AND provider_id IS NULL
        ORDER BY name
    """))
    return result.fetchall()


# =============================================================================
# PHASE 2: CREATE PROVIDERS
# =============================================================================

def create_providers_for_tenant(conn, tenant_id: str, api_credentials: dict,
                                 is_single_tenant: bool, required_provider_types: set,
                                 fernet=None) -> dict:
    """
    Create model providers for a tenant based on credentials.

    Args:
        conn: Database connection
        tenant_id: Tenant UUID string
        api_credentials: Credentials from tenant.api_credentials (already encrypted)
        is_single_tenant: Whether this is a single-tenant deployment
        required_provider_types: Set of provider types needed
        fernet: Optional Fernet instance for encrypting ENV credentials

    Returns: Dict mapping provider_type -> provider_id
    """
    providers_map = {}
    now = datetime.now(timezone.utc)

    for provider_type in required_provider_types:
        credentials = {}
        config = {}

        # 1. Try tenant api_credentials (multi-tenant)
        # These are already encrypted in the tenant table
        if api_credentials and provider_type in api_credentials:
            tenant_creds = api_credentials[provider_type]
            if isinstance(tenant_creds, dict):
                credentials = {"api_key": tenant_creds.get("api_key", "")}
                config = {k: v for k, v in tenant_creds.items()
                         if k not in ["api_key", "set_at", "encrypted_at"]}
            else:
                credentials = {"api_key": str(tenant_creds)}

        # 2. Single-tenant fallback: ENV variables
        # These are plaintext and need encryption if ENCRYPTION_KEY is set
        elif is_single_tenant:
            env_creds = get_env_credentials(provider_type)
            if env_creds:
                api_key = env_creds.get("api_key", "")
                # Encrypt ENV credentials if encryption is available
                if api_key and fernet:
                    api_key = encrypt_api_key(api_key, fernet)
                credentials = {"api_key": api_key}
                config = {k: v for k, v in env_creds.items() if k != "api_key"}

        # 3. Empty credentials - user must configure later
        if not credentials:
            credentials = {"api_key": ""}

        provider_id = str(uuid4())
        provider_name = get_provider_name(provider_type)
        is_active = bool(credentials.get("api_key"))

        conn.execute(text("""
            INSERT INTO model_providers
            (id, tenant_id, name, provider_type, credentials, config, is_active, created_at, updated_at)
            VALUES (:id, :tenant_id, :name, :provider_type, CAST(:credentials AS jsonb), CAST(:config AS jsonb),
                    :is_active, :created_at, :updated_at)
            ON CONFLICT (tenant_id, name) DO UPDATE SET
                credentials = EXCLUDED.credentials,
                config = EXCLUDED.config,
                is_active = EXCLUDED.is_active,
                updated_at = EXCLUDED.updated_at
            RETURNING id
        """), {
            "id": provider_id,
            "tenant_id": tenant_id,
            "name": provider_name,
            "provider_type": provider_type,
            "credentials": json.dumps(credentials),
            "config": json.dumps(config),
            "is_active": is_active,
            "created_at": now,
            "updated_at": now,
        })

        # Get the actual ID (in case of conflict update)
        result = conn.execute(text("""
            SELECT id FROM model_providers
            WHERE tenant_id = :tenant_id AND name = :name
        """), {"tenant_id": tenant_id, "name": provider_name})
        row = result.fetchone()
        if row:
            providers_map[provider_type] = str(row[0])
        else:
            providers_map[provider_type] = provider_id

    return providers_map


# =============================================================================
# PHASE 3: CREATE TENANT-SPECIFIC MODELS
# =============================================================================

def create_tenant_completion_models(conn, tenant_id: str, global_models: list,
                                     providers_map: dict) -> dict:
    """Create tenant-specific copies of global completion models."""
    model_mapping = {}
    now = datetime.now(timezone.utc)

    for model in global_models:
        global_model_id = str(model.id)
        family = (model.family or "openai").lower()
        provider_type = get_provider_type_for_family(family)
        provider_id = providers_map.get(provider_type)

        if not provider_id:
            print(f"    Warning: No provider for family '{family}' (type: {provider_type}), skipping model {model.name}")
            continue

        new_model_id = str(uuid4())

        conn.execute(text("""
            INSERT INTO completion_models (
                id, tenant_id, provider_id,
                name, nickname, family, token_limit, is_deprecated,
                nr_billion_parameters, hf_link, stability, hosting,
                description, deployment_name, org, vision, reasoning,
                base_url, litellm_model_name, open_source,
                created_at, updated_at
            )
            VALUES (
                :new_id, :tenant_id, :provider_id,
                :name, :nickname, :family, :token_limit, :is_deprecated,
                :nr_billion_parameters, :hf_link, :stability, :hosting,
                :description, :deployment_name, :org, :vision, :reasoning,
                :base_url, :litellm_model_name, :open_source,
                :now, :now
            )
        """), {
            "new_id": new_model_id,
            "tenant_id": tenant_id,
            "provider_id": provider_id,
            "name": model.name,
            "nickname": model.nickname,
            "family": model.family,
            "token_limit": model.token_limit,
            "is_deprecated": model.is_deprecated,
            "nr_billion_parameters": model.nr_billion_parameters,
            "hf_link": model.hf_link,
            "stability": model.stability,
            "hosting": model.hosting,
            "description": model.description,
            "deployment_name": model.deployment_name,
            "org": model.org,
            "vision": model.vision,
            "reasoning": model.reasoning,
            "base_url": model.base_url,
            "litellm_model_name": model.litellm_model_name,
            "open_source": model.open_source,
            "now": now,
        })

        model_mapping[global_model_id] = new_model_id

    return model_mapping


def create_tenant_embedding_models(conn, tenant_id: str, global_models: list,
                                    providers_map: dict) -> dict:
    """Create tenant-specific copies of global embedding models."""
    model_mapping = {}
    now = datetime.now(timezone.utc)

    for model in global_models:
        global_model_id = str(model.id)
        family = (model.family or "openai").lower()
        provider_type = get_provider_type_for_family(family)
        provider_id = providers_map.get(provider_type)

        if not provider_id:
            print(f"    Warning: No provider for family '{family}', skipping embedding model {model.name}")
            continue

        new_model_id = str(uuid4())

        conn.execute(text("""
            INSERT INTO embedding_models (
                id, tenant_id, provider_id,
                name, family, open_source, dimensions, max_input, max_batch_size,
                is_deprecated, hf_link, stability, hosting, description, org,
                litellm_model_name, created_at, updated_at
            )
            VALUES (
                :new_id, :tenant_id, :provider_id,
                :name, :family, :open_source, :dimensions, :max_input, :max_batch_size,
                :is_deprecated, :hf_link, :stability, :hosting, :description, :org,
                :litellm_model_name, :now, :now
            )
        """), {
            "new_id": new_model_id,
            "tenant_id": tenant_id,
            "provider_id": provider_id,
            "name": model.name,
            "family": model.family,
            "open_source": model.open_source,
            "dimensions": model.dimensions,
            "max_input": model.max_input,
            "max_batch_size": model.max_batch_size,
            "is_deprecated": model.is_deprecated,
            "hf_link": model.hf_link,
            "stability": model.stability,
            "hosting": model.hosting,
            "description": model.description,
            "org": model.org,
            "litellm_model_name": model.litellm_model_name,
            "now": now,
        })

        model_mapping[global_model_id] = new_model_id

    return model_mapping


def create_tenant_transcription_models(conn, tenant_id: str, global_models: list,
                                        providers_map: dict) -> dict:
    """Create tenant-specific copies of global transcription models."""
    model_mapping = {}
    now = datetime.now(timezone.utc)

    for model in global_models:
        global_model_id = str(model.id)
        family = (model.family or "openai").lower()
        provider_type = get_provider_type_for_family(family)
        provider_id = providers_map.get(provider_type)

        if not provider_id:
            print(f"    Warning: No provider for family '{family}', skipping transcription model {model.name}")
            continue

        new_model_id = str(uuid4())

        conn.execute(text("""
            INSERT INTO transcription_models (
                id, tenant_id, provider_id,
                name, model_name, open_source, is_deprecated,
                hf_link, family, stability, hosting, description, org, base_url,
                created_at, updated_at
            )
            VALUES (
                :new_id, :tenant_id, :provider_id,
                :name, :model_name, :open_source, :is_deprecated,
                :hf_link, :family, :stability, :hosting, :description, :org, :base_url,
                :now, :now
            )
        """), {
            "new_id": new_model_id,
            "tenant_id": tenant_id,
            "provider_id": provider_id,
            "name": model.name,
            "model_name": model.model_name,
            "open_source": model.open_source,
            "is_deprecated": model.is_deprecated,
            "hf_link": model.hf_link,
            "family": model.family,
            "stability": model.stability,
            "hosting": model.hosting,
            "description": model.description,
            "org": model.org,
            "base_url": model.base_url,
            "now": now,
        })

        model_mapping[global_model_id] = new_model_id

    return model_mapping


# =============================================================================
# PHASE 4: UPDATE FK REFERENCES
# =============================================================================

def update_completion_model_references(conn, tenant_id: str, model_mapping: dict):
    """Update all FK references from global to tenant-specific completion models."""
    if not model_mapping:
        return

    now = datetime.now(timezone.utc)

    # Build list of (old_id, new_id) for the update
    for old_id, new_id in model_mapping.items():
        # Assistants (join via users for tenant)
        conn.execute(text("""
            UPDATE assistants
            SET completion_model_id = :new_id, updated_at = :now
            WHERE completion_model_id = :old_id
            AND user_id IN (SELECT id FROM users WHERE tenant_id = :tenant_id)
        """), {"old_id": old_id, "new_id": new_id, "tenant_id": tenant_id, "now": now})

        # Apps
        conn.execute(text("""
            UPDATE apps
            SET completion_model_id = :new_id, updated_at = :now
            WHERE completion_model_id = :old_id
            AND tenant_id = :tenant_id
        """), {"old_id": old_id, "new_id": new_id, "tenant_id": tenant_id, "now": now})

        # App Runs
        conn.execute(text("""
            UPDATE app_runs
            SET completion_model_id = :new_id, updated_at = :now
            WHERE completion_model_id = :old_id
            AND tenant_id = :tenant_id
        """), {"old_id": old_id, "new_id": new_id, "tenant_id": tenant_id, "now": now})

        # Services (join via users for tenant)
        conn.execute(text("""
            UPDATE services
            SET completion_model_id = :new_id, updated_at = :now
            WHERE completion_model_id = :old_id
            AND user_id IN (SELECT id FROM users WHERE tenant_id = :tenant_id)
        """), {"old_id": old_id, "new_id": new_id, "tenant_id": tenant_id, "now": now})

        # Questions
        conn.execute(text("""
            UPDATE questions
            SET completion_model_id = :new_id, updated_at = :now
            WHERE completion_model_id = :old_id
            AND tenant_id = :tenant_id
        """), {"old_id": old_id, "new_id": new_id, "tenant_id": tenant_id, "now": now})

        # App Templates
        conn.execute(text("""
            UPDATE app_templates
            SET completion_model_id = :new_id, updated_at = :now
            WHERE completion_model_id = :old_id
            AND tenant_id = :tenant_id
        """), {"old_id": old_id, "new_id": new_id, "tenant_id": tenant_id, "now": now})

        # Assistant Templates
        conn.execute(text("""
            UPDATE assistant_templates
            SET completion_model_id = :new_id, updated_at = :now
            WHERE completion_model_id = :old_id
            AND tenant_id = :tenant_id
        """), {"old_id": old_id, "new_id": new_id, "tenant_id": tenant_id, "now": now})

        # Spaces Completion Models (many-to-many)
        conn.execute(text("""
            UPDATE spaces_completion_models
            SET completion_model_id = :new_id, updated_at = :now
            WHERE completion_model_id = :old_id
            AND space_id IN (SELECT id FROM spaces WHERE tenant_id = :tenant_id)
        """), {"old_id": old_id, "new_id": new_id, "tenant_id": tenant_id, "now": now})

        # Completion Model Settings - Create new settings for tenant models
        # First check if setting already exists for the new model
        exists = conn.execute(text("""
            SELECT 1 FROM completion_model_settings
            WHERE tenant_id = :tenant_id AND completion_model_id = :new_id
        """), {"tenant_id": tenant_id, "new_id": new_id}).fetchone()

        if not exists:
            conn.execute(text("""
                INSERT INTO completion_model_settings
                (tenant_id, completion_model_id, is_org_enabled, is_org_default,
                 security_classification_id, created_at, updated_at)
                SELECT
                    :tenant_id, :new_id, is_org_enabled, is_org_default,
                    security_classification_id, :now, :now
                FROM completion_model_settings
                WHERE tenant_id = :tenant_id AND completion_model_id = :old_id
            """), {"tenant_id": tenant_id, "old_id": old_id, "new_id": new_id, "now": now})


def update_embedding_model_references(conn, tenant_id: str, model_mapping: dict):
    """Update all FK references for embedding models."""
    if not model_mapping:
        return

    now = datetime.now(timezone.utc)

    for old_id, new_id in model_mapping.items():
        # Groups (collections)
        conn.execute(text("""
            UPDATE groups
            SET embedding_model_id = :new_id, updated_at = :now
            WHERE embedding_model_id = :old_id
            AND tenant_id = :tenant_id
        """), {"old_id": old_id, "new_id": new_id, "tenant_id": tenant_id, "now": now})

        # Info Blobs
        conn.execute(text("""
            UPDATE info_blobs
            SET embedding_model_id = :new_id, updated_at = :now
            WHERE embedding_model_id = :old_id
            AND tenant_id = :tenant_id
        """), {"old_id": old_id, "new_id": new_id, "tenant_id": tenant_id, "now": now})

        # Websites
        conn.execute(text("""
            UPDATE websites
            SET embedding_model_id = :new_id, updated_at = :now
            WHERE embedding_model_id = :old_id
            AND tenant_id = :tenant_id
        """), {"old_id": old_id, "new_id": new_id, "tenant_id": tenant_id, "now": now})

        # Integration Knowledge
        conn.execute(text("""
            UPDATE integration_knowledge
            SET embedding_model_id = :new_id, updated_at = :now
            WHERE embedding_model_id = :old_id
            AND tenant_id = :tenant_id
        """), {"old_id": old_id, "new_id": new_id, "tenant_id": tenant_id, "now": now})

        # Spaces Embedding Models
        conn.execute(text("""
            UPDATE spaces_embedding_models
            SET embedding_model_id = :new_id, updated_at = :now
            WHERE embedding_model_id = :old_id
            AND space_id IN (SELECT id FROM spaces WHERE tenant_id = :tenant_id)
        """), {"old_id": old_id, "new_id": new_id, "tenant_id": tenant_id, "now": now})

        # Embedding Model Settings
        exists = conn.execute(text("""
            SELECT 1 FROM embedding_model_settings
            WHERE tenant_id = :tenant_id AND embedding_model_id = :new_id
        """), {"tenant_id": tenant_id, "new_id": new_id}).fetchone()

        if not exists:
            conn.execute(text("""
                INSERT INTO embedding_model_settings
                (tenant_id, embedding_model_id, is_org_enabled, is_org_default,
                 security_classification_id, created_at, updated_at)
                SELECT
                    :tenant_id, :new_id, is_org_enabled, is_org_default,
                    security_classification_id, :now, :now
                FROM embedding_model_settings
                WHERE tenant_id = :tenant_id AND embedding_model_id = :old_id
            """), {"tenant_id": tenant_id, "old_id": old_id, "new_id": new_id, "now": now})


def update_transcription_model_references(conn, tenant_id: str, model_mapping: dict):
    """Update transcription model settings."""
    if not model_mapping:
        return

    now = datetime.now(timezone.utc)

    for old_id, new_id in model_mapping.items():
        # Transcription Model Settings
        exists = conn.execute(text("""
            SELECT 1 FROM transcription_model_settings
            WHERE tenant_id = :tenant_id AND transcription_model_id = :new_id
        """), {"tenant_id": tenant_id, "new_id": new_id}).fetchone()

        if not exists:
            conn.execute(text("""
                INSERT INTO transcription_model_settings
                (tenant_id, transcription_model_id, is_org_enabled, is_org_default,
                 security_classification_id, created_at, updated_at)
                SELECT
                    :tenant_id, :new_id, is_org_enabled, is_org_default,
                    security_classification_id, :now, :now
                FROM transcription_model_settings
                WHERE tenant_id = :tenant_id AND transcription_model_id = :old_id
            """), {"tenant_id": tenant_id, "old_id": old_id, "new_id": new_id, "now": now})


# =============================================================================
# PHASE 5: VALIDATION
# =============================================================================

def validate_migration(conn, tenant_id: str, cm_mapping: dict, em_mapping: dict):
    """Validate that all references have been migrated for this tenant."""
    global_cm_ids = list(cm_mapping.keys())
    global_em_ids = list(em_mapping.keys())

    if global_cm_ids:
        # Convert to PostgreSQL array literal format
        ids_array = "{" + ",".join(global_cm_ids) + "}"

        # Check assistants
        result = conn.execute(text("""
            SELECT COUNT(*) FROM assistants a
            JOIN users u ON a.user_id = u.id
            WHERE a.completion_model_id = ANY(CAST(:ids AS uuid[]))
            AND u.tenant_id = :tenant_id
        """), {"ids": ids_array, "tenant_id": tenant_id})
        count = result.scalar()
        if count > 0:
            print(f"    Warning: {count} assistants still reference global completion models")

        # Check apps
        result = conn.execute(text("""
            SELECT COUNT(*) FROM apps
            WHERE completion_model_id = ANY(CAST(:ids AS uuid[]))
            AND tenant_id = :tenant_id
        """), {"ids": ids_array, "tenant_id": tenant_id})
        count = result.scalar()
        if count > 0:
            print(f"    Warning: {count} apps still reference global completion models")

    if global_em_ids:
        ids_array = "{" + ",".join(global_em_ids) + "}"

        # Check groups
        result = conn.execute(text("""
            SELECT COUNT(*) FROM groups
            WHERE embedding_model_id = ANY(CAST(:ids AS uuid[]))
            AND tenant_id = :tenant_id
        """), {"ids": ids_array, "tenant_id": tenant_id})
        count = result.scalar()
        if count > 0:
            print(f"    Warning: {count} groups still reference global embedding models")


# =============================================================================
# PHASE 6: CLEANUP
# =============================================================================

def cleanup_global_model_settings(conn, cm_ids: list, em_ids: list, tm_ids: list):
    """Delete settings that reference global models."""

    if cm_ids:
        ids_array = "{" + ",".join(cm_ids) + "}"
        conn.execute(text("""
            DELETE FROM completion_model_settings
            WHERE completion_model_id = ANY(CAST(:ids AS uuid[]))
        """), {"ids": ids_array})

        conn.execute(text("""
            DELETE FROM spaces_completion_models
            WHERE completion_model_id = ANY(CAST(:ids AS uuid[]))
        """), {"ids": ids_array})

    if em_ids:
        ids_array = "{" + ",".join(em_ids) + "}"
        conn.execute(text("""
            DELETE FROM embedding_model_settings
            WHERE embedding_model_id = ANY(CAST(:ids AS uuid[]))
        """), {"ids": ids_array})

        conn.execute(text("""
            DELETE FROM spaces_embedding_models
            WHERE embedding_model_id = ANY(CAST(:ids AS uuid[]))
        """), {"ids": ids_array})

    if tm_ids:
        ids_array = "{" + ",".join(tm_ids) + "}"
        conn.execute(text("""
            DELETE FROM transcription_model_settings
            WHERE transcription_model_id = ANY(CAST(:ids AS uuid[]))
        """), {"ids": ids_array})


def delete_global_models(conn):
    """Delete all global models."""
    # Completion models
    conn.execute(text("""
        DELETE FROM completion_models
        WHERE tenant_id IS NULL AND provider_id IS NULL
    """))

    # Embedding models
    conn.execute(text("""
        DELETE FROM embedding_models
        WHERE tenant_id IS NULL AND provider_id IS NULL
    """))

    # Transcription models
    conn.execute(text("""
        DELETE FROM transcription_models
        WHERE tenant_id IS NULL AND provider_id IS NULL
    """))


# =============================================================================
# MAIN MIGRATION
# =============================================================================

def upgrade() -> None:
    conn = op.get_bind()

    print("\n" + "=" * 60)
    print("MIGRATION: Global to Tenant-Specific AI Models")
    print("=" * 60)

    # Drop global unique constraints on model names to allow per-tenant duplicates
    # These will be replaced with tenant-scoped unique constraints
    # Must drop CONSTRAINT first (which automatically drops the index), or drop index CASCADE
    print("\nDropping global unique constraints on model names...")
    conn.execute(text("ALTER TABLE completion_models DROP CONSTRAINT IF EXISTS completion_models_name_key"))
    print("  Dropped completion_models_name_key (if existed)")

    conn.execute(text("ALTER TABLE embedding_models DROP CONSTRAINT IF EXISTS embedding_models_name_key"))
    print("  Dropped embedding_models_name_key (if existed)")

    conn.execute(text("ALTER TABLE transcription_models DROP CONSTRAINT IF EXISTS transcription_models_name_key"))
    print("  Dropped transcription_models_name_key (if existed)")

    # Create tenant-scoped unique constraints (name must be unique within a tenant)
    print("\nCreating tenant-scoped unique constraints...")
    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_completion_models_tenant_name
        ON completion_models (tenant_id, name)
        WHERE tenant_id IS NOT NULL
    """))
    print("  Created idx_completion_models_tenant_name")

    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_embedding_models_tenant_name
        ON embedding_models (tenant_id, name)
        WHERE tenant_id IS NOT NULL
    """))
    print("  Created idx_embedding_models_tenant_name")

    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_transcription_models_tenant_name
        ON transcription_models (tenant_id, name)
        WHERE tenant_id IS NOT NULL
    """))
    print("  Created idx_transcription_models_tenant_name")

    # Get data
    tenants = get_active_tenants(conn)
    global_completion_models = get_global_completion_models(conn)
    global_embedding_models = get_global_embedding_models(conn)
    global_transcription_models = get_global_transcription_models(conn)

    if not tenants:
        print("No active tenants found - skipping migration")
        return

    if not global_completion_models and not global_embedding_models and not global_transcription_models:
        print("No global models found - skipping migration")
        return

    # Detect single-tenant mode
    is_single_tenant = len(tenants) == 1

    # Initialize encryption for single-tenant ENV credentials
    fernet = None
    if is_single_tenant:
        fernet = get_fernet_instance()
        if fernet:
            print("\nEncryption enabled: ENV credentials will be encrypted")
        else:
            print("\nWarning: ENCRYPTION_KEY not set - ENV credentials will be stored in plaintext")

    print(f"\nFound {len(tenants)} tenant(s)")
    print(f"Found {len(global_completion_models)} global completion models")
    print(f"Found {len(global_embedding_models)} global embedding models")
    print(f"Found {len(global_transcription_models)} global transcription models")
    print(f"Single-tenant mode: {is_single_tenant}")

    # Determine required provider types from model families
    required_provider_types = set()
    for model in global_completion_models:
        required_provider_types.add(get_provider_type_for_family(model.family or "openai"))
    for model in global_embedding_models:
        required_provider_types.add(get_provider_type_for_family(model.family or "openai"))
    for model in global_transcription_models:
        required_provider_types.add(get_provider_type_for_family(model.family or "openai"))

    print(f"Required provider types: {required_provider_types}")

    # Track all global IDs for cleanup
    all_cm_ids = [str(m.id) for m in global_completion_models]
    all_em_ids = [str(m.id) for m in global_embedding_models]
    all_tm_ids = [str(m.id) for m in global_transcription_models]

    # Process each tenant
    for tenant in tenants:
        tenant_id = str(tenant.id)
        tenant_name = tenant.name
        api_credentials = tenant.api_credentials or {}

        print(f"\n--- Processing tenant: {tenant_name} ({tenant_id}) ---")

        # Phase 2: Create providers
        print("  Creating providers...")
        providers_map = create_providers_for_tenant(
            conn, tenant_id, api_credentials, is_single_tenant, required_provider_types, fernet
        )
        print(f"  Created/updated {len(providers_map)} providers")

        # Phase 3: Create tenant-specific models
        print("  Creating tenant completion models...")
        cm_mapping = create_tenant_completion_models(
            conn, tenant_id, global_completion_models, providers_map
        )
        print(f"  Created {len(cm_mapping)} completion models")

        print("  Creating tenant embedding models...")
        em_mapping = create_tenant_embedding_models(
            conn, tenant_id, global_embedding_models, providers_map
        )
        print(f"  Created {len(em_mapping)} embedding models")

        print("  Creating tenant transcription models...")
        tm_mapping = create_tenant_transcription_models(
            conn, tenant_id, global_transcription_models, providers_map
        )
        print(f"  Created {len(tm_mapping)} transcription models")

        # Phase 4: Update FK references
        print("  Updating completion model references...")
        update_completion_model_references(conn, tenant_id, cm_mapping)

        print("  Updating embedding model references...")
        update_embedding_model_references(conn, tenant_id, em_mapping)

        print("  Updating transcription model references...")
        update_transcription_model_references(conn, tenant_id, tm_mapping)

        # Phase 5: Validate
        print("  Validating migration...")
        validate_migration(conn, tenant_id, cm_mapping, em_mapping)

        print(f"  Tenant {tenant_name} migration complete!")

    # Phase 6: Cleanup
    print("\n--- Cleaning up global models ---")
    print("  Removing global model settings...")
    cleanup_global_model_settings(conn, all_cm_ids, all_em_ids, all_tm_ids)

    print("  Deleting global models...")
    delete_global_models(conn)

    print("\n" + "=" * 60)
    print("MIGRATION COMPLETE!")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Delete backend/src/intric/server/dependencies/ai_models.yml")
    print("2. Remove init_models() call from startup")
    print("=" * 60 + "\n")


def downgrade() -> None:
    """
    Downgrade is not supported for this data migration.
    Restore from database backup if needed.
    """
    raise NotImplementedError(
        "Downgrade not supported for this migration. "
        "Restore from database backup if needed."
    )
