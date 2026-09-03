from __future__ import annotations

import pytest

from eneo.flows.domain.flow_step_validation import (
    FlowStepValidationError,
    FlowStepValidationView,
)
from eneo.flows.domain.speaker_mapping_config import (
    speaker_mapping_infer_names,
    speaker_mapping_participants_field,
    validate_speaker_mapping_output_config,
)
from eneo.flows.enums import (
    FlowInputSource,
    FlowInputType,
    FlowOutputMode,
    FlowOutputType,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode, FlowStepReviewPolicy


def _step(output_config: dict[str, object] | None) -> FlowStepValidationView:
    return FlowStepValidationView(
        step_order=2,
        timeout_seconds=None,
        user_description="Namnge talare",
        input_source=FlowInputSource.PREVIOUS_STEP,
        input_type=FlowInputType.TEXT,
        input_contract=None,
        output_mode=FlowOutputMode.SPEAKER_MAPPING,
        output_type=FlowOutputType.JSON,
        output_contract=None,
        input_bindings=None,
        input_config=None,
        output_config=output_config,
        review_policy=FlowStepReviewPolicy(mode=FlowStepReviewMode.EDIT),
    )


FIELDS = {
    "deltagare": "text",
    "antal": "number",
    "roller": "multiselect",
    "namn": "list",
}


def test_participants_field_reads_the_config_block() -> None:
    assert speaker_mapping_participants_field(None) is None
    assert speaker_mapping_participants_field({"speaker_mapping": {}}) is None
    assert (
        speaker_mapping_participants_field(
            {"speaker_mapping": {"participants_field": "deltagare"}}
        )
        == "deltagare"
    )


def test_draft_allows_missing_block_but_publish_requires_it() -> None:
    validate_speaker_mapping_output_config(
        step=_step(None), form_field_types=FIELDS, require_complete_config=False
    )
    with pytest.raises(FlowStepValidationError):
        validate_speaker_mapping_output_config(
            step=_step(None), form_field_types=FIELDS, require_complete_config=True
        )


@pytest.mark.parametrize("field", ["deltagare", "roller", "namn"])
def test_publish_accepts_text_multiselect_or_list_fields(field: str) -> None:
    validate_speaker_mapping_output_config(
        step=_step({"speaker_mapping": {"participants_field": field}}),
        form_field_types=FIELDS,
        require_complete_config=True,
    )


@pytest.mark.parametrize("field", ["antal", "okänt", None])
def test_publish_rejects_unusable_fields(field: str | None) -> None:
    with pytest.raises(FlowStepValidationError):
        validate_speaker_mapping_output_config(
            step=_step({"speaker_mapping": {"participants_field": field}}),
            form_field_types=FIELDS,
            require_complete_config=True,
        )


@pytest.mark.parametrize("count_field", ["antal", None])
def test_publish_accepts_number_speaker_count_field(count_field: str | None) -> None:
    validate_speaker_mapping_output_config(
        step=_step(
            {
                "speaker_mapping": {
                    "participants_field": "deltagare",
                    "speaker_count_field": count_field,
                }
            }
        ),
        form_field_types=FIELDS,
        require_complete_config=True,
    )


@pytest.mark.parametrize("count_field", ["deltagare", "okänt", ""])
def test_publish_rejects_non_number_speaker_count_field(count_field: str) -> None:
    with pytest.raises(FlowStepValidationError):
        validate_speaker_mapping_output_config(
            step=_step(
                {
                    "speaker_mapping": {
                        "participants_field": "deltagare",
                        "speaker_count_field": count_field,
                    }
                }
            ),
            form_field_types=FIELDS,
            require_complete_config=True,
        )


@pytest.mark.parametrize("block", ["nope", {"participants_field": ""}])
def test_malformed_block_is_rejected_even_in_drafts(block: object) -> None:
    with pytest.raises(FlowStepValidationError):
        validate_speaker_mapping_output_config(
            step=_step({"speaker_mapping": block}),
            form_field_types=FIELDS,
            require_complete_config=False,
        )


def test_infer_names_is_off_unless_literally_true() -> None:
    assert speaker_mapping_infer_names(None) is False
    assert speaker_mapping_infer_names({"speaker_mapping": {}}) is False
    assert speaker_mapping_infer_names({"speaker_mapping": {"infer_names": 1}}) is False
    assert (
        speaker_mapping_infer_names({"speaker_mapping": {"infer_names": True}}) is True
    )


def test_publish_allows_no_participants_field_only_with_inference() -> None:
    validate_speaker_mapping_output_config(
        step=_step(
            {"speaker_mapping": {"participants_field": None, "infer_names": True}}
        ),
        form_field_types=FIELDS,
        require_complete_config=True,
    )
    with pytest.raises(FlowStepValidationError):
        validate_speaker_mapping_output_config(
            step=_step(
                {"speaker_mapping": {"participants_field": None, "infer_names": False}}
            ),
            form_field_types=FIELDS,
            require_complete_config=True,
        )


def test_inference_still_requires_a_usable_field_when_one_is_named() -> None:
    with pytest.raises(FlowStepValidationError):
        validate_speaker_mapping_output_config(
            step=_step(
                {
                    "speaker_mapping": {
                        "participants_field": "antal",
                        "infer_names": True,
                    }
                }
            ),
            form_field_types=FIELDS,
            require_complete_config=True,
        )


@pytest.mark.parametrize("value", ["yes", 1])
def test_infer_names_must_be_a_bool_when_present(value: object) -> None:
    with pytest.raises(FlowStepValidationError):
        validate_speaker_mapping_output_config(
            step=_step(
                {
                    "speaker_mapping": {
                        "participants_field": "deltagare",
                        "infer_names": value,
                    }
                }
            ),
            form_field_types=FIELDS,
            require_complete_config=False,
        )
