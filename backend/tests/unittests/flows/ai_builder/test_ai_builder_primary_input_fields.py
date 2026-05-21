from intric.flows.ai_builder.ai_builder_primary_input_fields import (
    is_primary_runtime_input_shadow_field,
    primary_input_shadow_alias_input_types,
)
from intric.flows.flow_authoring_spec import (
    InputType,
)


def test_primary_input_shadow_aliases_cover_all_concrete_input_types() -> None:
    expected = {
        input_type for input_type in InputType if input_type is not InputType.ANY
    }

    assert primary_input_shadow_alias_input_types() == expected


def test_audio_transcript_names_shadow_primary_audio_input() -> None:
    for variable_name in (
        "transcript",
        "transcription",
        "transcribed_text",
        "transkribering",
        "transkription",
    ):
        assert is_primary_runtime_input_shadow_field(
            variable_name=variable_name,
            field_type="text",
            runtime_input_type=InputType.AUDIO,
        )
