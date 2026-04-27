from __future__ import annotations

import pytest

from intric.flows.ai_builder.ai_builder_flow_name import normalize_flow_name


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
