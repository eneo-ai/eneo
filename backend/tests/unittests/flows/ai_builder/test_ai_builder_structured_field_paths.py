from intric.flows.ai_builder.ai_builder_new_step_models import StructuredFieldDraft
from intric.flows.ai_builder.ai_builder_structured_field_paths import (
    missing_draft_field_path,
)


def test_missing_draft_field_path_requires_array_index() -> None:
    fields = [
        StructuredFieldDraft(
            name="risker",
            field_type="array",
            description="Risker",
            item_fields=[
                StructuredFieldDraft(
                    name="rubrik",
                    field_type="string",
                    description="Rubrik",
                )
            ],
        )
    ]

    assert missing_draft_field_path(fields, "risker.0.rubrik") is None
    assert missing_draft_field_path(fields, "risker.rubrik") == "risker.rubrik"
    assert missing_draft_field_path(fields, "risker") is None
