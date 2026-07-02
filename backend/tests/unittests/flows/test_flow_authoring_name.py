from __future__ import annotations

import pytest

from eneo.flows.flow_authoring_name import (
    MAX_FLOW_NAME_LENGTH,
    normalize_flow_name,
    normalize_optional_flow_name,
)


def test_normalize_flow_name_preserves_human_names() -> None:
    assert normalize_flow_name("  Utvecklingssamtal PDF  ") == "Utvecklingssamtal PDF"
    assert normalize_flow_name("customer_api_sync") == "customer_api_sync"


def test_normalize_flow_name_humanizes_generated_slug_like_names() -> None:
    assert (
        normalize_flow_name(
            "audio_to_artifact_report_lone_revision_development_talk_pdf"
        )
        == "Audio Report Development Talk PDF"
    )


def test_normalize_flow_name_rejects_empty_names() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        normalize_flow_name("   ")


def test_normalize_flow_name_rejects_names_above_length_limit() -> None:
    with pytest.raises(ValueError, match=f"at most {MAX_FLOW_NAME_LENGTH}"):
        normalize_flow_name("a" * (MAX_FLOW_NAME_LENGTH + 1))


def test_normalize_optional_flow_name_preserves_absent_value() -> None:
    assert normalize_optional_flow_name(None) is None


def test_normalize_optional_flow_name_normalizes_present_value() -> None:
    assert normalize_optional_flow_name("  report_pdf  ") == "report_pdf"
