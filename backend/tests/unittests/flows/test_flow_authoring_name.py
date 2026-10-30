from __future__ import annotations

import pytest

from eneo.flows.flow_authoring_name import (
    MAX_FLOW_NAME_LENGTH,
    FlowNameTakenError,
    flow_name_family,
    normalize_flow_name,
)
from eneo.main.exceptions import EXCEPTION_MAP
from eneo.server.exception_handlers import DOMAIN_EXCEPTION_MAP


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


@pytest.mark.parametrize(
    ("name", "family"),
    [
        ("Weekly report", "Weekly report"),
        ("Weekly report (2)", "Weekly report"),
        ("Weekly report  (12)", "Weekly report"),
        ("Report (a)", "Report (a)"),
        ("Report (2) draft", "Report (2) draft"),
        ("(3)", ""),
    ],
)
def test_flow_name_family_drops_only_the_numbered_suffix_a_create_adds(
    name: str, family: str
) -> None:
    assert flow_name_family(name) == family


def test_a_taken_name_has_no_http_answer_of_its_own() -> None:
    # Kills the mutant that makes FlowNameTakenError an HTTP conflict. A caller
    # that does not answer it itself, AI Builder apply, would then return a 409
    # that the Builder client reads as a changed revision.
    answered = (*EXCEPTION_MAP, *DOMAIN_EXCEPTION_MAP)
    assert not issubclass(FlowNameTakenError, answered)
