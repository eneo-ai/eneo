"""Persisted capability cleanup for governed reasoning effort."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import psycopg2
import pytest

from alembic import command
from alembic.config import Config
from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.completion_models.domain.model_kwargs_capabilities import (
    SupportedModelKwargs,
)
from eneo.completion_models.infrastructure.adapters.tenant_model_adapter import (
    TenantModelAdapter,
)
from eneo.governance_policy.domain.policy_resolver import (
    EffectiveConfig,
    select_effective_reasoning_effort,
)

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202608101300"
REASONING_REVISION = "202608121500"


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parent.parent.parent.parent
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(autouse=True)
def cleanup_database():
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    yield


@pytest.fixture
def reasoning_db(test_settings):
    config = _alembic_cfg(test_settings.sync_database_url)
    connection = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    connection.autocommit = True
    command.upgrade(config, PRE_REVISION)
    try:
        yield connection, config
    finally:
        connection.close()


def _legacy_capabilities() -> dict[str, object]:
    return {
        "temperature": {"supported": False},
        "reasoning_effort": {
            "supported": True,
            "control": "select",
            "options": ["none", "low", "medium", "high"],
        },
        "verbosity": {
            "supported": True,
            "control": "select",
            "options": ["low", "medium", "high"],
        },
    }


def _insert_legacy_model(connection) -> str:
    model_id = str(uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO completion_models (
                id, name, nickname, max_input_tokens, max_output_tokens,
                family, stability, hosting, reasoning,
                model_kwargs_capabilities, created_at, updated_at
            )
            VALUES (
                %s, 'legacy-reasoning-model', 'Legacy reasoning model', 4096, 1024,
                'openai', 'stable', 'usa', true, %s::jsonb, now(), now()
            )
            """,
            (model_id, json.dumps(_legacy_capabilities())),
        )
    return model_id


def _capabilities(connection, model_id: str) -> dict[str, object]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT model_kwargs_capabilities FROM completion_models WHERE id = %s",
            (model_id,),
        )
        return cursor.fetchone()[0]


def _prepare_kwargs(reasoning_effort: str) -> dict[str, object]:
    adapter = object.__new__(TenantModelAdapter)
    adapter.credential_resolver = Mock()
    adapter.litellm_model = "openai/reasoning-model"
    adapter.provider_type = "openai"
    adapter.model = SimpleNamespace(max_output_tokens=4096)

    with (
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter."
            "build_litellm_provider_kwargs",
            return_value={},
        ),
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter."
            "_get_supported_openai_params",
            return_value=["reasoning_effort"],
        ),
    ):
        return adapter._prepare_kwargs(
            model_kwargs=ModelKwargs(reasoning_effort=reasoning_effort)
        )


def test_upgrade_removes_unverified_none_before_policy_and_dispatch(
    reasoning_db,
) -> None:
    connection, config = reasoning_db
    model_id = _insert_legacy_model(connection)

    command.upgrade(config, REASONING_REVISION)

    capabilities = _capabilities(connection, model_id)
    assert capabilities["reasoning_effort"]["options"] == [
        "low",
        "medium",
        "high",
    ]
    assert capabilities["verbosity"]["options"] == ["low", "medium", "high"]

    supported_kwargs = SupportedModelKwargs.model_validate(capabilities)
    selected_model = SimpleNamespace(
        get_supported_model_kwargs=lambda: supported_kwargs
    )
    effective_config = EffectiveConfig(
        models_enforced=False,
        available_models=[],
        locked_model=None,
        policy_default_model=None,
        mcp_enforced=False,
        available_mcp_servers=[],
        prompt_enforced=False,
        enforced_prompt_text=None,
        reasoning_policy_configured=True,
        default_reasoning_effort="high",
        reasoning_effort_user_configurable=True,
    )

    selected_effort = select_effective_reasoning_effort(
        selected_model=selected_model,
        stored_effort="none",
        effective_config=effective_config,
    )

    assert selected_effort == "high"
    assert _prepare_kwargs(selected_effort)["reasoning_effort"] == "high"
