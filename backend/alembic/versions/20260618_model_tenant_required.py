"""repair residual global models and require tenant ownership.

Revision ID: 20260618_model_tenant_required
Revises: 202605251000
Create Date: 2026-06-18
"""

from __future__ import annotations

import json
from typing import Any, NamedTuple
from urllib.parse import urlparse
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260618_model_tenant_required"
down_revision = "202605251000"
branch_labels = None
depends_on = None


class ProviderDescriptor(NamedTuple):
    provider_type: str
    name: str
    config: dict[str, object]


class ProviderSelection(NamedTuple):
    id: UUID
    is_active: bool
    was_created: bool


class ModelSpec(NamedTuple):
    kind: str
    table: str
    key_columns: tuple[str, ...]


MODEL_SPECS = (
    ModelSpec(
        kind="completion",
        table="completion_models",
        key_columns=("name", "litellm_model_name", "deployment_name"),
    ),
    ModelSpec(
        kind="embedding",
        table="embedding_models",
        key_columns=("name", "litellm_model_name"),
    ),
    ModelSpec(
        kind="transcription",
        table="transcription_models",
        key_columns=("model_name",),
    ),
)


PROVIDER_TYPES: dict[str, tuple[str, str]] = {
    "anthropic": ("anthropic", "Anthropic"),
    "azure": ("azure", "Azure OpenAI"),
    "claude": ("anthropic", "Anthropic"),
    "cohere": ("cohere", "Cohere"),
    "gemini": ("gemini", "Google Gemini"),
    "mistral": ("mistral", "Mistral AI"),
    "openai": ("openai", "OpenAI"),
    "ovhcloud": ("ovhcloud", "OVHcloud"),
}


def _execute(conn: sa.Connection, sql: str, params: dict[str, object] | None = None):
    return conn.execute(sa.text(sql), params or {})


def _lower(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text.lower() if text else None


def _normalize_endpoint(endpoint: object | None) -> str | None:
    if endpoint is None:
        return None
    value = str(endpoint).strip().rstrip("/")
    return value.lower() if value else None


def _endpoint_config(endpoint: str | None) -> dict[str, object]:
    return {"endpoint": endpoint} if endpoint else {}


def _provider_name_from_endpoint(endpoint: str | None) -> str:
    if not endpoint:
        return "Hosted vLLM"
    parsed = urlparse(endpoint)
    host = parsed.netloc or parsed.path
    return host or "Hosted vLLM"


def _combined_provider_hints(row: Any) -> str:
    values = [
        getattr(row, "family", None),
        getattr(row, "org", None),
        getattr(row, "base_url", None),
        getattr(row, "litellm_model_name", None),
        getattr(row, "name", None),
        getattr(row, "model_name", None),
    ]
    return " ".join(str(value).lower() for value in values if value is not None)


def _descriptor_for_row(kind: str, row: Any) -> ProviderDescriptor:
    family = _lower(getattr(row, "family", None))
    hints = _combined_provider_hints(row)
    base_url = _normalize_endpoint(getattr(row, "base_url", None))

    if "berget" in hints or family in {"berget", "e5"}:
        endpoint = "https://api.berget.ai/v1"
        return ProviderDescriptor(
            provider_type="hosted_vllm",
            name="Berget.ai",
            config=_endpoint_config(endpoint),
        )

    if "gdm" in hints:
        endpoint = "https://ai.gdm.se/api/v1"
        return ProviderDescriptor(
            provider_type="hosted_vllm",
            name="GDM",
            config=_endpoint_config(endpoint),
        )

    if family == "vllm":
        return ProviderDescriptor(
            provider_type="hosted_vllm",
            name=getattr(row, "org", None) or _provider_name_from_endpoint(base_url),
            config=_endpoint_config(base_url),
        )

    if family == "azure":
        config = {
            "endpoint": base_url or "",
            "api_version": "",
            "deployment_name": getattr(row, "deployment_name", None) or "",
        }
        return ProviderDescriptor(
            provider_type="azure",
            name="Azure OpenAI",
            config=config,
        )

    if family in PROVIDER_TYPES:
        provider_type, name = PROVIDER_TYPES[family]
        return ProviderDescriptor(provider_type=provider_type, name=name, config={})

    if base_url:
        return ProviderDescriptor(
            provider_type="hosted_vllm",
            name=getattr(row, "org", None) or _provider_name_from_endpoint(base_url),
            config=_endpoint_config(base_url),
        )

    raise RuntimeError(
        f"Cannot map {kind} model {row.id} ({getattr(row, 'name', None)!r}) "
        f"with family={getattr(row, 'family', None)!r} to a tenant provider."
    )


def _all_tenant_ids(conn: sa.Connection) -> list[UUID]:
    return [
        row.id
        for row in _execute(
            conn,
            """
            SELECT id
            FROM tenants
            ORDER BY created_at, id
            """,
        ).fetchall()
    ]


def _referencing_tenant_ids(conn: sa.Connection, kind: str, model_id: UUID) -> set[UUID]:
    queries = {
        "completion": """
            SELECT DISTINCT tenant_id FROM (
                SELECT u.tenant_id
                FROM assistants a
                JOIN users u ON u.id = a.user_id
                WHERE a.completion_model_id = :id
                UNION
                SELECT tenant_id FROM apps WHERE completion_model_id = :id
                UNION
                SELECT tenant_id FROM app_runs WHERE completion_model_id = :id
                UNION
                SELECT u.tenant_id
                FROM services s
                JOIN users u ON u.id = s.user_id
                WHERE s.completion_model_id = :id
                UNION
                SELECT tenant_id FROM questions WHERE completion_model_id = :id
                UNION
                SELECT tenant_id FROM app_templates
                WHERE completion_model_id = :id AND tenant_id IS NOT NULL
                UNION
                SELECT tenant_id FROM assistant_templates
                WHERE completion_model_id = :id AND tenant_id IS NOT NULL
                UNION
                SELECT s.tenant_id
                FROM spaces_completion_models scm
                JOIN spaces s ON s.id = scm.space_id
                WHERE scm.completion_model_id = :id
                UNION
                SELECT gp.tenant_id
                FROM governance_policy_completion_models gpcm
                JOIN governance_policies gp ON gp.id = gpcm.policy_id
                WHERE gpcm.completion_model_id = :id
                UNION
                SELECT tenant_id FROM completion_model_migration_history
                WHERE from_model_id = :id OR to_model_id = :id
                UNION
                SELECT tenant_id FROM completion_models
                WHERE migrated_to_model_id = :id AND tenant_id IS NOT NULL
            ) tenants
            """,
        "embedding": """
            SELECT DISTINCT tenant_id FROM (
                SELECT tenant_id FROM groups WHERE embedding_model_id = :id
                UNION
                SELECT tenant_id FROM info_blobs WHERE embedding_model_id = :id
                UNION
                SELECT tenant_id FROM websites WHERE embedding_model_id = :id
                UNION
                SELECT tenant_id FROM integration_knowledge WHERE embedding_model_id = :id
                UNION
                SELECT s.tenant_id
                FROM spaces_embedding_models sem
                JOIN spaces s ON s.id = sem.space_id
                WHERE sem.embedding_model_id = :id
            ) tenants
            """,
        "transcription": """
            SELECT DISTINCT tenant_id FROM (
                SELECT tenant_id FROM apps WHERE transcription_model_id = :id
                UNION
                SELECT s.tenant_id
                FROM spaces_transcription_models stm
                JOIN spaces s ON s.id = stm.space_id
                WHERE stm.transcription_model_id = :id
                UNION
                SELECT tenant_id FROM transcription_model_migration_history
                WHERE from_model_id = :id OR to_model_id = :id
                UNION
                SELECT tenant_id FROM transcription_models
                WHERE migrated_to_model_id = :id AND tenant_id IS NOT NULL
            ) tenants
            """,
    }
    return {
        row.tenant_id
        for row in _execute(conn, queries[kind], {"id": model_id}).fetchall()
        if row.tenant_id is not None
    }


def _provider_endpoint_clause(descriptor: ProviderDescriptor) -> tuple[str, dict[str, object]]:
    endpoint = _normalize_endpoint(descriptor.config.get("endpoint"))
    if endpoint is None:
        return "", {}
    return (
        "AND lower(trim(trailing '/' from COALESCE(config->>'endpoint', ''))) = :endpoint",
        {"endpoint": endpoint},
    )


def _provider_by_name(
    conn: sa.Connection, tenant_id: UUID, descriptor: ProviderDescriptor
) -> ProviderSelection | None:
    row = _execute(
        conn,
        """
        SELECT id, is_active
        FROM model_providers
        WHERE tenant_id = :tenant_id
          AND provider_type = :provider_type
          AND lower(name) = lower(:name)
        ORDER BY is_active DESC, created_at, id
        LIMIT 1
        """,
        {
            "tenant_id": tenant_id,
            "provider_type": descriptor.provider_type,
            "name": descriptor.name,
        },
    ).first()
    if row is None:
        return None
    return ProviderSelection(id=row.id, is_active=row.is_active, was_created=False)


def _provider_by_endpoint(
    conn: sa.Connection, tenant_id: UUID, descriptor: ProviderDescriptor
) -> ProviderSelection | None:
    endpoint_clause, params = _provider_endpoint_clause(descriptor)
    if not endpoint_clause:
        return None
    row = _execute(
        conn,
        f"""
        SELECT id, is_active
        FROM model_providers
        WHERE tenant_id = :tenant_id
          AND provider_type = :provider_type
          {endpoint_clause}
        ORDER BY is_active DESC, created_at, id
        LIMIT 1
        """,
        {
            "tenant_id": tenant_id,
            "provider_type": descriptor.provider_type,
            **params,
        },
    ).first()
    if row is None:
        return None
    return ProviderSelection(id=row.id, is_active=row.is_active, was_created=False)


def _single_provider_by_type(
    conn: sa.Connection, tenant_id: UUID, descriptor: ProviderDescriptor
) -> ProviderSelection | None:
    rows = _execute(
        conn,
        """
        SELECT id, is_active
        FROM model_providers
        WHERE tenant_id = :tenant_id
          AND provider_type = :provider_type
        ORDER BY is_active DESC, created_at, id
        """,
        {"tenant_id": tenant_id, "provider_type": descriptor.provider_type},
    ).fetchall()
    if len(rows) != 1:
        return None
    return ProviderSelection(id=rows[0].id, is_active=rows[0].is_active, was_created=False)


def _unique_provider_name(conn: sa.Connection, tenant_id: UUID, base_name: str) -> str:
    candidate = base_name
    suffix = 2
    while _execute(
        conn,
        """
        SELECT 1
        FROM model_providers
        WHERE tenant_id = :tenant_id
          AND lower(name) = lower(:name)
        LIMIT 1
        """,
        {"tenant_id": tenant_id, "name": candidate},
    ).first():
        candidate = f"{base_name} ({suffix})"
        suffix += 1
    return candidate


def _create_inactive_provider(
    conn: sa.Connection, tenant_id: UUID, descriptor: ProviderDescriptor
) -> ProviderSelection:
    provider_id = uuid4()
    provider_name = _unique_provider_name(conn, tenant_id, descriptor.name)
    _execute(
        conn,
        """
        INSERT INTO model_providers (
            id, tenant_id, name, provider_type, credentials, config, is_active,
            created_at, updated_at
        )
        VALUES (
            :id, :tenant_id, :name, :provider_type,
            CAST(:credentials AS jsonb), CAST(:config AS jsonb), false,
            now(), now()
        )
        """,
        {
            "id": provider_id,
            "tenant_id": tenant_id,
            "name": provider_name,
            "provider_type": descriptor.provider_type,
            "credentials": json.dumps({}),
            "config": json.dumps(descriptor.config),
        },
    )
    return ProviderSelection(id=provider_id, is_active=False, was_created=True)


def _find_or_create_provider(
    conn: sa.Connection, tenant_id: UUID, descriptor: ProviderDescriptor
) -> ProviderSelection:
    endpoint_match = _provider_by_endpoint(conn, tenant_id, descriptor)
    if endpoint_match is not None:
        return endpoint_match

    if "endpoint" in descriptor.config:
        return _create_inactive_provider(conn, tenant_id, descriptor)

    name_match = _provider_by_name(conn, tenant_id, descriptor)
    if name_match is not None:
        return name_match

    single_type_match = _single_provider_by_type(conn, tenant_id, descriptor)
    if single_type_match is not None:
        return single_type_match

    return _create_inactive_provider(conn, tenant_id, descriptor)


def _provider_selection_by_id(
    conn: sa.Connection, tenant_id: UUID, provider_id: UUID
) -> ProviderSelection | None:
    row = _execute(
        conn,
        """
        SELECT id, is_active
        FROM model_providers
        WHERE id = :provider_id
          AND tenant_id = :tenant_id
        """,
        {"provider_id": provider_id, "tenant_id": tenant_id},
    ).first()
    if row is None:
        return None
    return ProviderSelection(id=row.id, is_active=row.is_active, was_created=False)


def _provider_tenant_id(conn: sa.Connection, provider_id: UUID) -> UUID | None:
    row = _execute(
        conn,
        "SELECT tenant_id FROM model_providers WHERE id = :provider_id",
        {"provider_id": provider_id},
    ).first()
    return row.tenant_id if row is not None else None


def _active_default_exists(conn: sa.Connection, table: str, tenant_id: UUID) -> bool:
    return (
        _execute(
            conn,
            f"""
            SELECT 1
            FROM {table}
            WHERE tenant_id = :tenant_id
              AND is_default = true
              AND is_deprecated = false
              AND deleted_at IS NULL
            LIMIT 1
            """,
            {"tenant_id": tenant_id},
        ).first()
        is not None
    )


def _value_lower(row: Any, column: str) -> str | None:
    return _lower(getattr(row, column, None))


def _find_existing_model(
    conn: sa.Connection,
    spec: ModelSpec,
    tenant_id: UUID,
    provider_id: UUID,
    source_row: Any,
) -> UUID | None:
    params: dict[str, object] = {
        "tenant_id": tenant_id,
        "provider_id": provider_id,
    }
    comparisons: list[str] = []
    for index, column in enumerate(spec.key_columns):
        value = _value_lower(source_row, column)
        if value is None:
            continue
        param_name = f"key_{index}"
        params[param_name] = value
        comparisons.append(f"lower({column}) = :{param_name}")

    if not comparisons:
        raise RuntimeError(f"Cannot derive model identity for {spec.kind} row {source_row.id}")

    row = _execute(
        conn,
        f"""
        SELECT id
        FROM {spec.table}
        WHERE tenant_id = :tenant_id
          AND provider_id = :provider_id
          AND deleted_at IS NULL
          AND ({' OR '.join(comparisons)})
        ORDER BY is_deprecated, created_at, id
        LIMIT 1
        """,
        params,
    ).first()
    return row.id if row is not None else None


def _unique_nickname(
    conn: sa.Connection,
    table: str,
    tenant_id: UUID,
    provider_id: UUID,
    nickname: str | None,
) -> str | None:
    if nickname is None:
        return None

    candidate = nickname
    suffix = 2
    while _execute(
        conn,
        f"""
        SELECT 1
        FROM {table}
        WHERE tenant_id = :tenant_id
          AND provider_id = :provider_id
          AND deleted_at IS NULL
          AND is_deprecated = false
          AND nickname IS NOT NULL
          AND lower(nickname) = lower(:nickname)
        LIMIT 1
        """,
        {
            "tenant_id": tenant_id,
            "provider_id": provider_id,
            "nickname": candidate,
        },
    ).first():
        candidate = f"{nickname} ({suffix})"
        suffix += 1
    return candidate


def _copy_is_enabled(source_row: Any, provider: ProviderSelection) -> bool:
    return bool(
        getattr(source_row, "is_enabled", False)
        and provider.is_active
        and getattr(source_row, "deleted_at", None) is None
    )


def _copy_is_default(
    conn: sa.Connection,
    spec: ModelSpec,
    tenant_id: UUID,
    source_row: Any,
    provider: ProviderSelection,
) -> bool:
    if not _copy_is_enabled(source_row, provider):
        return False
    if not bool(getattr(source_row, "is_default", False)):
        return False
    if bool(getattr(source_row, "is_deprecated", False)):
        return False
    return not _active_default_exists(conn, spec.table, tenant_id)


def _promote_existing_default_if_needed(
    conn: sa.Connection,
    spec: ModelSpec,
    tenant_id: UUID,
    model_id: UUID,
    source_row: Any,
) -> None:
    if not bool(getattr(source_row, "is_default", False)):
        return
    if bool(getattr(source_row, "is_deprecated", False)):
        return
    if _active_default_exists(conn, spec.table, tenant_id):
        return
    _execute(
        conn,
        f"""
        UPDATE {spec.table}
        SET is_default = true
        WHERE id = :model_id
          AND tenant_id = :tenant_id
          AND deleted_at IS NULL
          AND is_deprecated = false
          AND is_enabled = true
        """,
        {"model_id": model_id, "tenant_id": tenant_id},
    )


def _insert_completion_copy(
    conn: sa.Connection,
    tenant_id: UUID,
    provider_id: UUID,
    source_id: UUID,
    nickname: str | None,
    is_enabled: bool,
    is_default: bool,
) -> UUID:
    new_id = uuid4()
    _execute(
        conn,
        """
        INSERT INTO completion_models (
            id, created_at, updated_at, name, nickname, open_source,
            max_input_tokens, max_output_tokens, is_deprecated,
            nr_billion_parameters, hf_link, family, stability, hosting,
            description, deployment_name, org, vision, reasoning,
            supports_tool_calling, base_url, litellm_model_name,
            model_kwargs_capabilities, input_cost_per_token, output_cost_per_token,
            tenant_id, provider_id, is_enabled, is_default,
            security_classification_id, migrated_to_model_id, deleted_at
        )
        SELECT
            :new_id, created_at, now(), name, :nickname, open_source,
            max_input_tokens, max_output_tokens, is_deprecated,
            nr_billion_parameters, hf_link, family, stability, hosting,
            description, deployment_name, org, vision, reasoning,
            supports_tool_calling, base_url, litellm_model_name,
            model_kwargs_capabilities, input_cost_per_token, output_cost_per_token,
            :tenant_id, :provider_id, :is_enabled, :is_default,
            NULL, NULL, deleted_at
        FROM completion_models
        WHERE id = :source_id
        """,
        {
            "new_id": new_id,
            "tenant_id": tenant_id,
            "provider_id": provider_id,
            "source_id": source_id,
            "nickname": nickname,
            "is_enabled": is_enabled,
            "is_default": is_default,
        },
    )
    return new_id


def _insert_embedding_copy(
    conn: sa.Connection,
    tenant_id: UUID,
    provider_id: UUID,
    source_id: UUID,
    nickname: str | None,
    is_enabled: bool,
    is_default: bool,
) -> UUID:
    new_id = uuid4()
    _execute(
        conn,
        """
        INSERT INTO embedding_models (
            id, created_at, updated_at, name, nickname, open_source,
            dimensions, max_input, max_batch_size, is_deprecated, hf_link,
            family, stability, hosting, description, org, litellm_model_name,
            input_cost_per_token, output_cost_per_token, tenant_id, provider_id,
            is_enabled, is_default, security_classification_id, deleted_at
        )
        SELECT
            :new_id, created_at, now(), name, :nickname, open_source,
            dimensions, max_input, max_batch_size, is_deprecated, hf_link,
            family, stability, hosting, description, org, litellm_model_name,
            input_cost_per_token, output_cost_per_token, :tenant_id, :provider_id,
            :is_enabled, :is_default, NULL, deleted_at
        FROM embedding_models
        WHERE id = :source_id
        """,
        {
            "new_id": new_id,
            "tenant_id": tenant_id,
            "provider_id": provider_id,
            "source_id": source_id,
            "nickname": nickname,
            "is_enabled": is_enabled,
            "is_default": is_default,
        },
    )
    return new_id


def _insert_transcription_copy(
    conn: sa.Connection,
    tenant_id: UUID,
    provider_id: UUID,
    source_id: UUID,
    nickname: str | None,
    is_enabled: bool,
    is_default: bool,
) -> UUID:
    new_id = uuid4()
    _execute(
        conn,
        """
        INSERT INTO transcription_models (
            id, created_at, updated_at, name, model_name, nickname, open_source,
            is_deprecated, hf_link, family, stability, hosting, description,
            org, base_url, cost_per_minute, tenant_id, provider_id, is_enabled,
            is_default, security_classification_id, migrated_to_model_id, deleted_at
        )
        SELECT
            :new_id, created_at, now(), name, model_name, :nickname, open_source,
            is_deprecated, hf_link, family, stability, hosting, description,
            org, base_url, cost_per_minute, :tenant_id, :provider_id, :is_enabled,
            :is_default, NULL, NULL, deleted_at
        FROM transcription_models
        WHERE id = :source_id
        """,
        {
            "new_id": new_id,
            "tenant_id": tenant_id,
            "provider_id": provider_id,
            "source_id": source_id,
            "nickname": nickname,
            "is_enabled": is_enabled,
            "is_default": is_default,
        },
    )
    return new_id


def _insert_copy(
    conn: sa.Connection,
    spec: ModelSpec,
    tenant_id: UUID,
    provider: ProviderSelection,
    source_row: Any,
) -> UUID:
    nickname = _unique_nickname(
        conn,
        spec.table,
        tenant_id,
        provider.id,
        getattr(source_row, "nickname", None) or getattr(source_row, "name", None),
    )
    is_enabled = _copy_is_enabled(source_row, provider)
    is_default = _copy_is_default(conn, spec, tenant_id, source_row, provider)
    if spec.kind == "completion":
        return _insert_completion_copy(
            conn, tenant_id, provider.id, source_row.id, nickname, is_enabled, is_default
        )
    if spec.kind == "embedding":
        return _insert_embedding_copy(
            conn, tenant_id, provider.id, source_row.id, nickname, is_enabled, is_default
        )
    if spec.kind == "transcription":
        return _insert_transcription_copy(
            conn, tenant_id, provider.id, source_row.id, nickname, is_enabled, is_default
        )
    raise AssertionError(f"Unexpected model kind {spec.kind}")


def _record_mapping(
    conn: sa.Connection, kind: str, old_id: UUID, tenant_id: UUID, new_id: UUID
) -> None:
    _execute(
        conn,
        """
        INSERT INTO model_tenant_repair_map (kind, old_id, tenant_id, new_id)
        VALUES (:kind, :old_id, :tenant_id, :new_id)
        ON CONFLICT (kind, old_id, tenant_id) DO UPDATE
        SET new_id = EXCLUDED.new_id
        """,
        {
            "kind": kind,
            "old_id": old_id,
            "tenant_id": tenant_id,
            "new_id": new_id,
        },
    )


def _map_global_models(conn: sa.Connection) -> None:
    all_tenant_ids = _all_tenant_ids(conn)
    for spec in MODEL_SPECS:
        global_rows = _execute(
            conn,
            f"""
            SELECT *
            FROM {spec.table}
            WHERE tenant_id IS NULL OR provider_id IS NULL
            ORDER BY created_at, id
            """,
        ).fetchall()

        for source_row in global_rows:
            if source_row.tenant_id is not None:
                target_tenants = {source_row.tenant_id}
            elif source_row.provider_id is not None:
                provider_tenant_id = _provider_tenant_id(conn, source_row.provider_id)
                target_tenants = {provider_tenant_id} if provider_tenant_id else set()
            elif source_row.deleted_at is None:
                target_tenants = set(all_tenant_ids)
            else:
                target_tenants = _referencing_tenant_ids(conn, spec.kind, source_row.id)

            if not target_tenants:
                continue

            descriptor: ProviderDescriptor | None = None
            for tenant_id in sorted(target_tenants, key=str):
                provider = None
                if source_row.provider_id is not None:
                    provider = _provider_selection_by_id(
                        conn, tenant_id, source_row.provider_id
                    )
                if provider is None:
                    if descriptor is None:
                        descriptor = _descriptor_for_row(spec.kind, source_row)
                    provider = _find_or_create_provider(conn, tenant_id, descriptor)
                existing_id = _find_existing_model(
                    conn, spec, tenant_id, provider.id, source_row
                )
                if existing_id is not None:
                    _promote_existing_default_if_needed(
                        conn, spec, tenant_id, existing_id, source_row
                    )
                    _record_mapping(conn, spec.kind, source_row.id, tenant_id, existing_id)
                    continue

                new_id = _insert_copy(conn, spec, tenant_id, provider, source_row)
                _record_mapping(conn, spec.kind, source_row.id, tenant_id, new_id)


def _rewrite_completion_references(conn: sa.Connection) -> None:
    for table, tenant_expr in (
        ("apps", "apps.tenant_id"),
        ("app_runs", "app_runs.tenant_id"),
        ("questions", "questions.tenant_id"),
    ):
        _execute(
            conn,
            f"""
            UPDATE {table}
            SET completion_model_id = m.new_id
            FROM model_tenant_repair_map m
            WHERE m.kind = 'completion'
              AND {table}.completion_model_id = m.old_id
              AND {tenant_expr} = m.tenant_id
            """,
        )

    for table in ("assistants", "services"):
        _execute(
            conn,
            f"""
            UPDATE {table}
            SET completion_model_id = m.new_id
            FROM users u, model_tenant_repair_map m
            WHERE m.kind = 'completion'
              AND {table}.user_id = u.id
              AND {table}.completion_model_id = m.old_id
              AND u.tenant_id = m.tenant_id
            """,
        )

    for table in ("app_templates", "assistant_templates"):
        _execute(
            conn,
            f"""
            UPDATE {table}
            SET completion_model_id = m.new_id
            FROM model_tenant_repair_map m
            WHERE m.kind = 'completion'
              AND {table}.completion_model_id = m.old_id
              AND {table}.tenant_id = m.tenant_id
            """,
        )
        _execute(
            conn,
            f"""
            UPDATE {table}
            SET completion_model_id = NULL
            WHERE tenant_id IS NULL
              AND completion_model_id IN (
                  SELECT old_id FROM model_tenant_repair_map WHERE kind = 'completion'
              )
            """,
        )

    _execute(
        conn,
        """
        INSERT INTO spaces_completion_models (
            space_id, completion_model_id, created_at, updated_at
        )
        SELECT scm.space_id, m.new_id, scm.created_at, scm.updated_at
        FROM spaces_completion_models scm
        JOIN spaces s ON s.id = scm.space_id
        JOIN model_tenant_repair_map m
          ON m.kind = 'completion'
         AND m.old_id = scm.completion_model_id
         AND m.tenant_id = s.tenant_id
        ON CONFLICT (space_id, completion_model_id) DO NOTHING
        """,
    )
    _execute(
        conn,
        """
        DELETE FROM spaces_completion_models scm
        USING spaces s, model_tenant_repair_map m
        WHERE m.kind = 'completion'
          AND scm.space_id = s.id
          AND scm.completion_model_id = m.old_id
          AND s.tenant_id = m.tenant_id
        """,
    )

    _execute(
        conn,
        """
        INSERT INTO governance_policy_completion_models (
            policy_id, completion_model_id, is_default, created_at, updated_at
        )
        SELECT gpcm.policy_id, m.new_id, false, gpcm.created_at, gpcm.updated_at
        FROM governance_policy_completion_models gpcm
        JOIN governance_policies gp ON gp.id = gpcm.policy_id
        JOIN model_tenant_repair_map m
          ON m.kind = 'completion'
         AND m.old_id = gpcm.completion_model_id
         AND m.tenant_id = gp.tenant_id
        ON CONFLICT (policy_id, completion_model_id) DO NOTHING
        """,
    )
    _execute(
        conn,
        """
        UPDATE governance_policy_completion_models target
        SET is_default = true
        FROM governance_policy_completion_models old_link
        JOIN governance_policies gp ON gp.id = old_link.policy_id
        JOIN model_tenant_repair_map m
          ON m.kind = 'completion'
         AND m.old_id = old_link.completion_model_id
         AND m.tenant_id = gp.tenant_id
        WHERE target.policy_id = old_link.policy_id
          AND target.completion_model_id = m.new_id
          AND old_link.is_default = true
          AND NOT EXISTS (
              SELECT 1
              FROM governance_policy_completion_models other
              WHERE other.policy_id = old_link.policy_id
                AND other.is_default = true
                AND other.completion_model_id NOT IN (old_link.completion_model_id, m.new_id)
          )
        """,
    )
    _execute(
        conn,
        """
        DELETE FROM governance_policy_completion_models gpcm
        USING governance_policies gp, model_tenant_repair_map m
        WHERE m.kind = 'completion'
          AND gpcm.policy_id = gp.id
          AND gpcm.completion_model_id = m.old_id
          AND gp.tenant_id = m.tenant_id
        """,
    )

    _execute(
        conn,
        """
        UPDATE completion_model_migration_history h
        SET from_model_id = m.new_id
        FROM model_tenant_repair_map m
        WHERE m.kind = 'completion'
          AND h.from_model_id = m.old_id
          AND h.tenant_id = m.tenant_id
        """,
    )
    _execute(
        conn,
        """
        UPDATE completion_model_migration_history h
        SET to_model_id = m.new_id
        FROM model_tenant_repair_map m
        WHERE m.kind = 'completion'
          AND h.to_model_id = m.old_id
          AND h.tenant_id = m.tenant_id
        """,
    )


def _rewrite_embedding_references(conn: sa.Connection) -> None:
    for table in ("groups", "info_blobs", "websites", "integration_knowledge"):
        _execute(
            conn,
            f"""
            UPDATE {table}
            SET embedding_model_id = m.new_id
            FROM model_tenant_repair_map m
            WHERE m.kind = 'embedding'
              AND {table}.embedding_model_id = m.old_id
              AND {table}.tenant_id = m.tenant_id
            """,
        )

    _execute(
        conn,
        """
        INSERT INTO spaces_embedding_models (
            space_id, embedding_model_id, created_at, updated_at
        )
        SELECT sem.space_id, m.new_id, sem.created_at, sem.updated_at
        FROM spaces_embedding_models sem
        JOIN spaces s ON s.id = sem.space_id
        JOIN model_tenant_repair_map m
          ON m.kind = 'embedding'
         AND m.old_id = sem.embedding_model_id
         AND m.tenant_id = s.tenant_id
        ON CONFLICT (space_id, embedding_model_id) DO NOTHING
        """,
    )
    _execute(
        conn,
        """
        DELETE FROM spaces_embedding_models sem
        USING spaces s, model_tenant_repair_map m
        WHERE m.kind = 'embedding'
          AND sem.space_id = s.id
          AND sem.embedding_model_id = m.old_id
          AND s.tenant_id = m.tenant_id
        """,
    )


def _rewrite_transcription_references(conn: sa.Connection) -> None:
    _execute(
        conn,
        """
        UPDATE apps
        SET transcription_model_id = m.new_id
        FROM model_tenant_repair_map m
        WHERE m.kind = 'transcription'
          AND apps.transcription_model_id = m.old_id
          AND apps.tenant_id = m.tenant_id
        """,
    )

    _execute(
        conn,
        """
        INSERT INTO spaces_transcription_models (
            space_id, transcription_model_id, created_at, updated_at
        )
        SELECT stm.space_id, m.new_id, stm.created_at, stm.updated_at
        FROM spaces_transcription_models stm
        JOIN spaces s ON s.id = stm.space_id
        JOIN model_tenant_repair_map m
          ON m.kind = 'transcription'
         AND m.old_id = stm.transcription_model_id
         AND m.tenant_id = s.tenant_id
        ON CONFLICT (space_id, transcription_model_id) DO NOTHING
        """,
    )
    _execute(
        conn,
        """
        DELETE FROM spaces_transcription_models stm
        USING spaces s, model_tenant_repair_map m
        WHERE m.kind = 'transcription'
          AND stm.space_id = s.id
          AND stm.transcription_model_id = m.old_id
          AND s.tenant_id = m.tenant_id
        """,
    )

    _execute(
        conn,
        """
        UPDATE transcription_model_migration_history h
        SET from_model_id = m.new_id
        FROM model_tenant_repair_map m
        WHERE m.kind = 'transcription'
          AND h.from_model_id = m.old_id
          AND h.tenant_id = m.tenant_id
        """,
    )
    _execute(
        conn,
        """
        UPDATE transcription_model_migration_history h
        SET to_model_id = m.new_id
        FROM model_tenant_repair_map m
        WHERE m.kind = 'transcription'
          AND h.to_model_id = m.old_id
          AND h.tenant_id = m.tenant_id
        """,
    )


def _rewrite_migrated_to_links(conn: sa.Connection) -> None:
    for kind, table in (
        ("completion", "completion_models"),
        ("transcription", "transcription_models"),
    ):
        _execute(
            conn,
            f"""
            UPDATE {table} tenant_copy
            SET migrated_to_model_id = target_map.new_id
            FROM model_tenant_repair_map source_map
            JOIN {table} source_global ON source_global.id = source_map.old_id
            JOIN model_tenant_repair_map target_map
              ON target_map.kind = :kind
             AND target_map.old_id = source_global.migrated_to_model_id
             AND target_map.tenant_id = source_map.tenant_id
            WHERE source_map.kind = :kind
              AND tenant_copy.id = source_map.new_id
            """,
            {"kind": kind},
        )
        _execute(
            conn,
            f"""
            UPDATE {table} tenant_model
            SET migrated_to_model_id = m.new_id
            FROM model_tenant_repair_map m
            WHERE m.kind = :kind
              AND tenant_model.migrated_to_model_id = m.old_id
              AND tenant_model.tenant_id = m.tenant_id
            """,
            {"kind": kind},
        )
        _execute(
            conn,
            f"""
            UPDATE {table}
            SET migrated_to_model_id = NULL
            WHERE migrated_to_model_id IN (
                SELECT id FROM {table} WHERE tenant_id IS NULL OR provider_id IS NULL
            )
            """,
        )


def _remaining_global_reference_count(conn: sa.Connection) -> int:
    queries = (
        """
        SELECT count(*)
        FROM assistants a
        JOIN completion_models cm ON cm.id = a.completion_model_id
        WHERE cm.tenant_id IS NULL OR cm.provider_id IS NULL
        """,
        """
        SELECT count(*)
        FROM services s
        JOIN completion_models cm ON cm.id = s.completion_model_id
        WHERE cm.tenant_id IS NULL OR cm.provider_id IS NULL
        """,
        """
        SELECT count(*)
        FROM apps a
        LEFT JOIN completion_models cm ON cm.id = a.completion_model_id
        LEFT JOIN transcription_models tm ON tm.id = a.transcription_model_id
        WHERE (
              a.completion_model_id IS NOT NULL
          AND (cm.tenant_id IS NULL OR cm.provider_id IS NULL)
        )
           OR (
              a.transcription_model_id IS NOT NULL
          AND (tm.tenant_id IS NULL OR tm.provider_id IS NULL)
        )
        """,
        """
        SELECT count(*)
        FROM app_runs ar
        JOIN completion_models cm ON cm.id = ar.completion_model_id
        WHERE cm.tenant_id IS NULL OR cm.provider_id IS NULL
        """,
        """
        SELECT count(*)
        FROM questions q
        JOIN completion_models cm ON cm.id = q.completion_model_id
        WHERE cm.tenant_id IS NULL OR cm.provider_id IS NULL
        """,
        """
        SELECT count(*)
        FROM app_templates t
        JOIN completion_models cm ON cm.id = t.completion_model_id
        WHERE cm.tenant_id IS NULL OR cm.provider_id IS NULL
        """,
        """
        SELECT count(*)
        FROM assistant_templates t
        JOIN completion_models cm ON cm.id = t.completion_model_id
        WHERE cm.tenant_id IS NULL OR cm.provider_id IS NULL
        """,
        """
        SELECT count(*)
        FROM spaces_completion_models scm
        JOIN completion_models cm ON cm.id = scm.completion_model_id
        WHERE cm.tenant_id IS NULL OR cm.provider_id IS NULL
        """,
        """
        SELECT count(*)
        FROM governance_policy_completion_models gpcm
        JOIN completion_models cm ON cm.id = gpcm.completion_model_id
        WHERE cm.tenant_id IS NULL OR cm.provider_id IS NULL
        """,
        """
        SELECT count(*)
        FROM groups g
        JOIN embedding_models em ON em.id = g.embedding_model_id
        WHERE em.tenant_id IS NULL OR em.provider_id IS NULL
        """,
        """
        SELECT count(*)
        FROM info_blobs ib
        JOIN embedding_models em ON em.id = ib.embedding_model_id
        WHERE em.tenant_id IS NULL OR em.provider_id IS NULL
        """,
        """
        SELECT count(*)
        FROM websites w
        JOIN embedding_models em ON em.id = w.embedding_model_id
        WHERE em.tenant_id IS NULL OR em.provider_id IS NULL
        """,
        """
        SELECT count(*)
        FROM integration_knowledge ik
        JOIN embedding_models em ON em.id = ik.embedding_model_id
        WHERE em.tenant_id IS NULL OR em.provider_id IS NULL
        """,
        """
        SELECT count(*)
        FROM spaces_embedding_models sem
        JOIN embedding_models em ON em.id = sem.embedding_model_id
        WHERE em.tenant_id IS NULL OR em.provider_id IS NULL
        """,
        """
        SELECT count(*)
        FROM spaces_transcription_models stm
        JOIN transcription_models tm ON tm.id = stm.transcription_model_id
        WHERE tm.tenant_id IS NULL OR tm.provider_id IS NULL
        """,
        """
        SELECT count(*)
        FROM completion_model_migration_history h
        LEFT JOIN completion_models from_model ON from_model.id = h.from_model_id
        LEFT JOIN completion_models to_model ON to_model.id = h.to_model_id
        WHERE (
              h.from_model_id IS NOT NULL
          AND (from_model.tenant_id IS NULL OR from_model.provider_id IS NULL)
        )
           OR (
              h.to_model_id IS NOT NULL
          AND (to_model.tenant_id IS NULL OR to_model.provider_id IS NULL)
        )
        """,
        """
        SELECT count(*)
        FROM transcription_model_migration_history h
        LEFT JOIN transcription_models from_model ON from_model.id = h.from_model_id
        LEFT JOIN transcription_models to_model ON to_model.id = h.to_model_id
        WHERE (
              h.from_model_id IS NOT NULL
          AND (from_model.tenant_id IS NULL OR from_model.provider_id IS NULL)
        )
           OR (
              h.to_model_id IS NOT NULL
          AND (to_model.tenant_id IS NULL OR to_model.provider_id IS NULL)
        )
        """,
    )
    total = 0
    for query in queries:
        total += int(_execute(conn, query).scalar() or 0)
    return total


def _delete_global_rows(conn: sa.Connection) -> None:
    remaining_refs = _remaining_global_reference_count(conn)
    if remaining_refs:
        raise RuntimeError(
            f"Cannot delete residual global models; {remaining_refs} references still point at them."
        )

    for table in ("completion_models", "transcription_models", "embedding_models"):
        _execute(
            conn,
            f"""
            DELETE FROM {table}
            WHERE tenant_id IS NULL OR provider_id IS NULL
            """,
        )


def _enforce_tenant_provider_required(table: str, old_constraint: str, new_constraint: str) -> None:
    op.execute(
        f"""
        ALTER TABLE {table}
        ADD CONSTRAINT {new_constraint}
        CHECK (tenant_id IS NOT NULL AND provider_id IS NOT NULL)
        NOT VALID
        """
    )
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {new_constraint}")
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {old_constraint}")
    op.alter_column(
        table,
        "tenant_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.alter_column(
        table,
        "provider_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )


def _recreate_active_nickname_index(table: str) -> None:
    op.execute(f"DROP INDEX IF EXISTS uq_{table}_active_nickname")
    op.execute(
        f"""
        CREATE UNIQUE INDEX uq_{table}_active_nickname
        ON {table} (tenant_id, provider_id, lower(nickname))
        WHERE deleted_at IS NULL
          AND is_deprecated = false
          AND nickname IS NOT NULL
        """
    )


def upgrade() -> None:
    conn = op.get_bind()
    _execute(
        conn,
        """
        CREATE TEMPORARY TABLE model_tenant_repair_map (
            kind text NOT NULL,
            old_id uuid NOT NULL,
            tenant_id uuid NOT NULL,
            new_id uuid NOT NULL,
            PRIMARY KEY (kind, old_id, tenant_id)
        ) ON COMMIT DROP
        """,
    )

    _map_global_models(conn)
    _rewrite_completion_references(conn)
    _rewrite_embedding_references(conn)
    _rewrite_transcription_references(conn)
    _rewrite_migrated_to_links(conn)
    _delete_global_rows(conn)

    for table in ("completion_models", "embedding_models", "transcription_models"):
        _recreate_active_nickname_index(table)

    _enforce_tenant_provider_required(
        "completion_models",
        "ck_completion_models_tenant_provider",
        "ck_completion_models_tenant_provider_required",
    )
    _enforce_tenant_provider_required(
        "embedding_models",
        "ck_embedding_models_tenant_provider",
        "ck_embedding_models_tenant_provider_required",
    )
    _enforce_tenant_provider_required(
        "transcription_models",
        "ck_transcription_models_tenant_provider",
        "ck_transcription_models_tenant_provider_required",
    )


def downgrade() -> None:
    raise NotImplementedError(
        "20260618_model_tenant_required deletes legacy global model rows after "
        "rewriting tenant references. Restore from backup to downgrade."
    )
