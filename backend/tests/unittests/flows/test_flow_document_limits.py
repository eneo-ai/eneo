import pytest

from eneo.flows.flow_document_limits import (
    FLOW_DOCUMENT_RENDER_HARD_LIMITS,
    apply_flow_document_render_limits_patch,
    resolve_flow_document_render_limits,
    validate_flow_document_render_limits_object,
)
from eneo.flows.runtime.document_rendering.limits import (
    DEFAULT_DOCUMENT_RENDER_LIMITS,
)
from eneo.main.exceptions import BadRequestException


def test_resolve_defaults_when_tenant_settings_missing() -> None:
    assert resolve_flow_document_render_limits(None) == DEFAULT_DOCUMENT_RENDER_LIMITS


def test_resolve_uses_tenant_overrides() -> None:
    limits = resolve_flow_document_render_limits(
        {
            "document_render_limits": {
                "max_source_chars": 750_000,
                "max_table_cells": 75_000,
            }
        }
    )

    assert limits.max_source_chars == 750_000
    assert limits.max_table_cells == 75_000
    assert limits.max_blocks == DEFAULT_DOCUMENT_RENDER_LIMITS.max_blocks


def test_resolve_ignores_invalid_stored_overrides() -> None:
    limits = resolve_flow_document_render_limits(
        {
            "document_render_limits": {
                "max_source_chars": "many",
                "max_table_cells": FLOW_DOCUMENT_RENDER_HARD_LIMITS.max_table_cells + 1,
            }
        }
    )

    assert limits.max_source_chars == DEFAULT_DOCUMENT_RENDER_LIMITS.max_source_chars
    assert limits.max_table_cells == DEFAULT_DOCUMENT_RENDER_LIMITS.max_table_cells


def test_apply_patch_preserves_unrelated_flow_settings() -> None:
    updated = apply_flow_document_render_limits_patch(
        {
            "input_limits": {"max_files_per_run": 10},
            "document_render_limits": {"max_source_chars": 700_000},
        },
        max_table_cells=60_000,
    )

    assert updated["input_limits"] == {"max_files_per_run": 10}
    assert updated["document_render_limits"] == {
        "max_source_chars": 700_000,
        "max_table_cells": 60_000,
    }


def test_apply_patch_removes_overrides_for_explicit_null() -> None:
    updated = apply_flow_document_render_limits_patch(
        {
            "document_render_limits": {
                "max_source_chars": 700_000,
                "max_table_cells": 60_000,
            }
        },
        remove_keys={"max_source_chars"},
    )

    assert updated["document_render_limits"] == {"max_table_cells": 60_000}


def test_apply_patch_removes_empty_document_render_section() -> None:
    updated = apply_flow_document_render_limits_patch(
        {"document_render_limits": {"max_source_chars": 700_000}},
        remove_keys={"max_source_chars"},
    )

    assert "document_render_limits" not in updated


def test_apply_patch_rejects_values_over_hard_ceiling() -> None:
    with pytest.raises(BadRequestException, match="max_source_chars"):
        apply_flow_document_render_limits_patch(
            {},
            max_source_chars=FLOW_DOCUMENT_RENDER_HARD_LIMITS.max_source_chars + 1,
        )


def test_validate_rejects_unknown_fields() -> None:
    with pytest.raises(BadRequestException, match="Unsupported document render limit"):
        validate_flow_document_render_limits_object({"unknown": 1})


def test_validate_returns_typed_limit_overrides() -> None:
    assert validate_flow_document_render_limits_object(
        {
            "max_source_chars": 750_000,
            "max_table_cells": 75_000,
        }
    ) == {
        "max_source_chars": 750_000,
        "max_table_cells": 75_000,
    }


def test_validate_rejects_non_string_limit_names() -> None:
    with pytest.raises(BadRequestException, match="limit names must be strings"):
        validate_flow_document_render_limits_object({1: 750_000})


def test_validate_rejects_bool_limit_values() -> None:
    with pytest.raises(BadRequestException, match="max_blocks must be an integer"):
        validate_flow_document_render_limits_object({"max_blocks": True})


def test_validate_rejects_non_positive_limit_values() -> None:
    with pytest.raises(
        BadRequestException, match="max_source_chars must be greater than zero"
    ):
        validate_flow_document_render_limits_object({"max_source_chars": 0})


def test_validate_rejects_values_over_hard_ceiling() -> None:
    with pytest.raises(
        BadRequestException, match="max_source_chars must be less than or equal to"
    ):
        validate_flow_document_render_limits_object(
            {"max_source_chars": FLOW_DOCUMENT_RENDER_HARD_LIMITS.max_source_chars + 1}
        )
