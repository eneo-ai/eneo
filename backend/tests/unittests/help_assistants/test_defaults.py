import importlib.util
from enum import Enum
from pathlib import Path
from typing import cast

import pytest

from intric.help_assistants.defaults import (
    DEFAULTS_BY_KIND,
    PROMPT_GUIDE_DEFAULTS,
    HelperAssistantDefaults,
    HelperKind,
    get_defaults,
)


# The seed migration keeps its own frozen copy of the Prompt Guide defaults
# because alembic version files may not import from intric.* (those modules
# get refactored over time). The parity tests below guard the copy against
# drifting from the runtime registry — see this file's sister migration
# docstring for the runbook.
_MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "alembic"
    / "versions"
    / "202605211400_seed_help_assistants_per_tenant.py"
)


def _load_seed_migration():
    spec = importlib.util.spec_from_file_location(
        "_seed_help_assistants_per_tenant", _MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_get_defaults_returns_registered_prompt_guide_defaults():
    result = get_defaults(HelperKind.PROMPT_GUIDE)

    assert result is PROMPT_GUIDE_DEFAULTS
    assert isinstance(result, HelperAssistantDefaults)
    assert result.name == "Prompt Guide"
    assert result.logging_enabled is False
    assert result.insight_enabled is False
    assert result.data_retention_days == 30
    assert DEFAULTS_BY_KIND[HelperKind.PROMPT_GUIDE] is result


def test_get_defaults_raises_keyerror_for_unknown_kind():
    class _FakeKind(str, Enum):
        UNKNOWN = "unknown"

        def __str__(self) -> str:
            return self.value

    with pytest.raises(KeyError):
        get_defaults(cast(HelperKind, _FakeKind.UNKNOWN))


def test_prompt_guide_prompt_includes_ui_language_instruction():
    prompt = PROMPT_GUIDE_DEFAULTS.prompt_text

    assert "Swedish" in prompt
    assert "English" in prompt


def test_prompt_guide_prompt_teaches_eneo_question_envelope():
    # Sanity-check the structural contract the frontend parser depends on:
    # the LLM must know to emit multi-choice questions in an `eneo-question`
    # fenced block and reserve untagged fences for the final artifact. If
    # this assertion breaks, the structured-question UI will silently fall
    # back to prose-only.
    prompt = PROMPT_GUIDE_DEFAULTS.prompt_text

    assert "eneo-question" in prompt
    assert "untagged" in prompt
    assert "multiSelect" in prompt


def test_seed_migration_prompt_text_matches_runtime_defaults():
    migration = _load_seed_migration()

    assert migration.PROMPT_GUIDE_PROMPT_TEXT == PROMPT_GUIDE_DEFAULTS.prompt_text


def test_seed_migration_description_matches_runtime_defaults():
    migration = _load_seed_migration()

    assert migration.PROMPT_GUIDE_DESCRIPTION == PROMPT_GUIDE_DEFAULTS.description


def test_seed_migration_name_matches_runtime_defaults():
    migration = _load_seed_migration()

    assert migration.PROMPT_GUIDE_NAME == PROMPT_GUIDE_DEFAULTS.name


def test_seed_migration_retention_matches_runtime_defaults():
    migration = _load_seed_migration()

    assert (
        migration.PROMPT_GUIDE_DATA_RETENTION_DAYS
        == PROMPT_GUIDE_DEFAULTS.data_retention_days
    )
