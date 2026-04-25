from intric.flows.ai_builder.ai_builder_models import InputType
from intric.flows.ai_builder.ai_builder_primary_input_fields import (
    primary_input_shadow_alias_input_types,
)


def test_primary_input_shadow_aliases_cover_all_concrete_input_types() -> None:
    expected = {
        input_type for input_type in InputType if input_type is not InputType.ANY
    }

    assert primary_input_shadow_alias_input_types() == expected
