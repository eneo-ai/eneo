from intric.completion_models.infrastructure.tenant_model_capabilities import (
    StructuredOutputCapabilityDecision,
    StructuredOutputDecisionSource,
    StructuredOutputMode,
)
from intric.flows.ai_builder.ai_builder_response_format import (
    build_planner_request_response_format,
    planner_output_strict_schema_blockers,
)


def _decision(mode: StructuredOutputMode) -> StructuredOutputCapabilityDecision:
    if mode is StructuredOutputMode.STRICT_JSON_SCHEMA:
        return StructuredOutputCapabilityDecision(
            mode=mode,
            source=StructuredOutputDecisionSource.LITELLM_RESPONSE_SCHEMA,
            supports_response_schema=True,
            supports_response_format=True,
        )
    if mode is StructuredOutputMode.JSON_OBJECT:
        return StructuredOutputCapabilityDecision(
            mode=mode,
            source=StructuredOutputDecisionSource.LITELLM_RESPONSE_FORMAT,
            supports_response_schema=False,
            supports_response_format=True,
        )
    return StructuredOutputCapabilityDecision(
        mode=mode,
        source=StructuredOutputDecisionSource.NO_PROVIDER_SUPPORT,
        supports_response_schema=False,
        supports_response_format=False,
    )


def test_planner_output_strict_schema_blockers_pin_current_contract_gap() -> None:
    blockers = planner_output_strict_schema_blockers()

    assert any("oneOf" in blocker for blocker in blockers)
    assert any("optional properties" in blocker for blocker in blockers)
    assert any("default" in blocker for blocker in blockers)
    assert any("additionalProperties=false" in blocker for blocker in blockers)


def test_strict_capable_provider_uses_json_object_for_current_planner_contract() -> (
    None
):
    selection = build_planner_request_response_format(
        _decision(StructuredOutputMode.STRICT_JSON_SCHEMA)
    )

    assert selection.request_mode is StructuredOutputMode.JSON_OBJECT
    assert selection.planner_output_strict_blocked is True
    assert selection.litellm_kwargs == {"response_format": {"type": "json_object"}}


def test_json_object_capable_provider_uses_json_object() -> None:
    selection = build_planner_request_response_format(
        _decision(StructuredOutputMode.JSON_OBJECT)
    )

    assert selection.request_mode is StructuredOutputMode.JSON_OBJECT
    assert selection.planner_output_strict_blocked is False
    assert selection.litellm_kwargs == {"response_format": {"type": "json_object"}}


def test_unsupported_provider_uses_prompt_validation_without_response_format() -> None:
    selection = build_planner_request_response_format(
        _decision(StructuredOutputMode.PROMPT_WITH_PYDANTIC_VALIDATION)
    )

    assert (
        selection.request_mode is StructuredOutputMode.PROMPT_WITH_PYDANTIC_VALIDATION
    )
    assert selection.planner_output_strict_blocked is False
    assert selection.litellm_kwargs == {}
