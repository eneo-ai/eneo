from __future__ import annotations

from pydantic import BaseModel

from intric.flows.api.flow_template_asset_models import (
    FLOW_TEMPLATE_ASSET_PUBLIC_EXAMPLE,
    FLOW_TEMPLATE_INSPECTION_PUBLIC_EXAMPLE,
    FlowTemplateAssetPublic,
    FlowTemplateInspectionPublic,
    FlowTemplatePlaceholderPublic,
)


def _assert_example_keys_belong_to_model(
    *, model: type[BaseModel], example: dict[str, object]
) -> None:
    assert set(example) <= set(model.model_fields)


def test_flow_template_inspection_example_matches_public_model() -> None:
    _assert_example_keys_belong_to_model(
        model=FlowTemplateInspectionPublic,
        example=FLOW_TEMPLATE_INSPECTION_PUBLIC_EXAMPLE,
    )
    for placeholder in FLOW_TEMPLATE_INSPECTION_PUBLIC_EXAMPLE["placeholders"]:
        _assert_example_keys_belong_to_model(
            model=FlowTemplatePlaceholderPublic,
            example=placeholder,
        )

    parsed = FlowTemplateInspectionPublic.model_validate(
        FLOW_TEMPLATE_INSPECTION_PUBLIC_EXAMPLE
    )

    assert parsed.file_name == FLOW_TEMPLATE_INSPECTION_PUBLIC_EXAMPLE["file_name"]


def test_flow_template_asset_example_matches_public_model() -> None:
    _assert_example_keys_belong_to_model(
        model=FlowTemplateAssetPublic,
        example=FLOW_TEMPLATE_ASSET_PUBLIC_EXAMPLE,
    )

    parsed = FlowTemplateAssetPublic.model_validate(FLOW_TEMPLATE_ASSET_PUBLIC_EXAMPLE)

    assert str(parsed.file_id) == FLOW_TEMPLATE_ASSET_PUBLIC_EXAMPLE["file_id"]
