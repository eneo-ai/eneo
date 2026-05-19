from __future__ import annotations

import json

from intric.flows.ai_builder.ai_builder_events import build_question_event
from intric.flows.ai_builder.ai_builder_mcp_intent import (
    build_mcp_resource_selection_question,
    explicit_mcp_name_groups,
    find_mcp_usage_without_selection_issue,
    find_named_mcp_reference_issue,
    find_named_mcp_request_issue,
    mcp_resource_selection_values,
    mcp_selection_answer_allows_planning,
    mcp_selection_policy_feedback,
)
from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    ConversationMessage,
    FlowDraftSpecCore,
    InputSource,
    OutputMode,
    OutputType,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    build_ai_builder_resource_catalog,
)

SVELTE_SERVER_SLOT = "mcp_server.svelte-mcp"
SVELTE_TOOL_SLOT = "mcp_tool.svelte-mcp-get-documentation"
TIME_SERVER_SLOT = "mcp_server.time-mcp"
TIME_TOOL_SLOT = "mcp_tool.time-mcp-get-current-time"


def _catalog_with_enabled_svelte_mcp():
    return build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "svelte-server",
                "name": "Svelte mcp",
                "description": "Developer documentation helpers for Svelte apps.",
                "tools": [
                    {
                        "id": "svelte-docs",
                        "name": "get-documentation",
                        "description": "Fetch Svelte documentation sections.",
                    }
                ],
            }
        ],
    )


def _time_catalog():
    return build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "time-server",
                "name": "Time MCP",
                "description": "Kan hämta tiden och konvertera tidszoner.",
                "tools": [
                    {
                        "id": "current-time",
                        "name": "get_current_time",
                        "description": "Get current time in a specific timezone.",
                    }
                ],
            }
        ],
    )


def _spec_with_step(
    *,
    name: str,
    instructions: str,
    mcp_server_refs: list[str] | None = None,
    mcp_tool_refs: list[str] | None = None,
) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="MCP-test",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name=name,
                assistant_spec=AssistantSpec(
                    instructions=instructions,
                    mcp_server_refs=mcp_server_refs or [],
                    mcp_tool_refs=mcp_tool_refs or [],
                ),
                input_source=InputSource.FLOW_INPUT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
            )
        ],
    )


def test_detects_requested_mcp_that_is_not_enabled_in_catalog() -> None:
    issue = find_named_mcp_reference_issue(
        spec=_spec_with_step(
            name="Hämta aktuell tid via Time MCP",
            instructions="Hämta aktuell tid för angiven tidszon.",
            mcp_server_refs=[SVELTE_SERVER_SLOT],
            mcp_tool_refs=[SVELTE_TOOL_SLOT],
        ),
        catalog=_catalog_with_enabled_svelte_mcp(),
        signal_text="Använd Time MCP för tidszonskonvertering.",
    )

    assert issue is not None
    assert issue.reason == "unavailable_requested_server"
    assert issue.requested_name == "Time"
    assert issue.selected_server_refs == frozenset({SVELTE_SERVER_SLOT})


def test_detects_enabled_named_mcp_request_before_planning() -> None:
    issue = find_named_mcp_request_issue(
        catalog=_time_catalog(),
        signal_text="Använd Time MCP för tidszonskonvertering.",
    )

    assert issue is not None
    assert issue.reason == "missing_selection"
    assert issue.resolved_server_ref == TIME_SERVER_SLOT


def test_explicit_mcp_name_prefers_name_before_marker_over_purpose_after_marker() -> (
    None
):
    assert explicit_mcp_name_groups("Använd Time MCP för tidszonskonvertering.") == [
        ("Time",)
    ]


def test_generic_mcp_protocol_words_are_not_named_server_requests() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "standard-server",
                "name": "Standard MCP",
                "description": "Example server whose name overlaps a generic word.",
            }
        ],
    )

    text = "Beskriv standard MCP protokoll och vanliga MCP specifikationer."

    assert explicit_mcp_name_groups(text) == []
    assert find_named_mcp_request_issue(catalog=catalog, signal_text=text) is None


def test_detects_available_named_mcp_without_attached_refs() -> None:
    issue = find_named_mcp_reference_issue(
        spec=_spec_with_step(
            name="Hämta aktuell tid via Time MCP",
            instructions="Använd Time MCP för aktuell tid.",
        ),
        catalog=_time_catalog(),
        signal_text="Använd Time MCP för tidszonskonvertering.",
    )

    assert issue is not None
    assert issue.reason == "missing_selection"
    assert issue.resolved_server_ref == TIME_SERVER_SLOT
    assert issue.selected_server_refs == frozenset()


def test_accepts_matching_tool_ref_for_named_mcp() -> None:
    issue = find_named_mcp_reference_issue(
        spec=_spec_with_step(
            name="Hämta aktuell tid via Time MCP",
            instructions="Hämta aktuell tid för angiven tidszon.",
            mcp_tool_refs=[TIME_TOOL_SLOT],
        ),
        catalog=_time_catalog(),
        signal_text="Använd Time MCP för tidszonskonvertering.",
    )

    assert issue is None


def test_global_named_mcp_request_only_needs_one_matching_step() -> None:
    spec = FlowDraftSpecCore(
        flow_name="MCP-test",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Hämta tid",
                assistant_spec=AssistantSpec(
                    instructions="Hämta aktuell tid.",
                    mcp_tool_refs=[TIME_TOOL_SLOT],
                ),
                input_source=InputSource.FLOW_INPUT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="Formatera svar",
                assistant_spec=AssistantSpec(
                    instructions="Formatera svaret som JSON utan externa verktyg.",
                ),
                input_source=InputSource.PREVIOUS_STEP,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
            ),
        ],
    )

    issue = find_named_mcp_reference_issue(
        spec=spec,
        catalog=_time_catalog(),
        signal_text="Använd Time MCP för tidszonskonvertering.",
    )

    assert issue is None


def test_downstream_step_can_reference_selected_mcp_without_own_tool_ref() -> None:
    spec = FlowDraftSpecCore(
        flow_name="MCP-test",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Hämta tid via Time MCP",
                assistant_spec=AssistantSpec(
                    instructions="Hämta aktuell tid.",
                    mcp_tool_refs=[TIME_TOOL_SLOT],
                ),
                input_source=InputSource.FLOW_INPUT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="Formatera Time MCP-resultat",
                assistant_spec=AssistantSpec(
                    instructions="Formatera resultatet från Time MCP som JSON.",
                ),
                input_source=InputSource.PREVIOUS_STEP,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
            ),
        ],
    )

    issue = find_named_mcp_reference_issue(
        spec=spec,
        catalog=_time_catalog(),
        signal_text="Använd Time MCP för tidszonskonvertering.",
    )

    assert issue is None


def test_downstream_named_mcp_reference_requires_an_owner_step_ref() -> None:
    spec = FlowDraftSpecCore(
        flow_name="MCP-test",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Hämta tid",
                assistant_spec=AssistantSpec(instructions="Hämta aktuell tid."),
                input_source=InputSource.FLOW_INPUT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="Formatera Time MCP-resultat",
                assistant_spec=AssistantSpec(
                    instructions="Formatera resultatet från Time MCP som JSON.",
                ),
                input_source=InputSource.PREVIOUS_STEP,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
            ),
        ],
    )

    issue = find_named_mcp_reference_issue(
        spec=spec,
        catalog=_time_catalog(),
        signal_text="Bygg ett tidsflöde.",
    )

    assert issue is not None
    assert issue.reason == "missing_selection"
    assert issue.step_ref == "step_b"
    assert issue.resolved_server_ref == TIME_SERVER_SLOT


def test_selected_mcp_generic_tool_phrase_does_not_count_as_unavailable_name() -> None:
    issue = find_named_mcp_reference_issue(
        spec=_spec_with_step(
            name="Hämta aktuell tid",
            instructions="Använd valda MCP-verktyg för att hämta aktuell tid.",
            mcp_tool_refs=[TIME_TOOL_SLOT],
        ),
        catalog=_time_catalog(),
        signal_text="Använd Time MCP för tidszonskonvertering.",
    )

    assert issue is None


def test_global_named_mcp_request_still_requires_a_matching_step_ref() -> None:
    issue = find_named_mcp_reference_issue(
        spec=FlowDraftSpecCore(
            flow_name="MCP-test",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    name="Hämta tid",
                    assistant_spec=AssistantSpec(
                        instructions="Hämta aktuell tid.",
                    ),
                    input_source=InputSource.FLOW_INPUT,
                    output_mode=OutputMode.PASS_THROUGH,
                    output_type=OutputType.JSON,
                ),
                StepSpec(
                    plan_step_ref="step_b",
                    name="Formatera svar",
                    assistant_spec=AssistantSpec(
                        instructions="Formatera svaret som JSON.",
                    ),
                    input_source=InputSource.PREVIOUS_STEP,
                    output_mode=OutputMode.PASS_THROUGH,
                    output_type=OutputType.JSON,
                ),
            ],
        ),
        catalog=_time_catalog(),
        signal_text="Använd Time MCP för tidszonskonvertering.",
    )

    assert issue is not None
    assert issue.reason == "missing_selection"
    assert issue.step_ref == "plan"


def test_detects_mcp_usage_before_user_selection() -> None:
    issue = find_mcp_usage_without_selection_issue(
        spec=_spec_with_step(
            name="Hämta tid",
            instructions="Hämta aktuell tid.",
            mcp_tool_refs=[TIME_TOOL_SLOT],
        ),
        catalog=_time_catalog(),
    )

    assert issue is not None
    assert issue.reason == "missing_selection"
    assert issue.resolved_server_ref == TIME_SERVER_SLOT


def test_mcp_selection_question_lists_only_enabled_servers() -> None:
    catalog = _catalog_with_enabled_svelte_mcp()
    issue = find_named_mcp_reference_issue(
        spec=_spec_with_step(
            name="Hämta aktuell tid via Time MCP",
            instructions="Hämta aktuell tid för angiven tidszon.",
        ),
        catalog=catalog,
        signal_text="Använd Time MCP för tidszonskonvertering.",
    )
    assert issue is not None

    question_data, assistant_text = build_mcp_resource_selection_question(
        issue=issue,
        catalog=catalog,
        language="sv",
    )

    assert "aktiverade" in assistant_text
    assert question_data["question_id"] == "mcp_resource_selection"
    assert question_data["requires_confirm"] is True
    labels = [option["label"] for option in question_data["options"]]
    assert labels == [
        "Fortsätt utan MCP",
        "Använd Svelte mcp",
    ]
    assert question_data["allow_custom"] is False
    values = [option["value"] for option in question_data["options"]]
    assert f"use_mcp_server:{SVELTE_SERVER_SLOT}" in values
    assert all(TIME_SERVER_SLOT not in str(value) for value in values)


def test_mcp_selection_question_event_preserves_explicit_confirm_flag() -> None:
    catalog = _time_catalog()
    issue = find_named_mcp_reference_issue(
        spec=_spec_with_step(
            name="Hämta aktuell tid via Time MCP",
            instructions="Hämta aktuell tid för angiven tidszon.",
        ),
        catalog=catalog,
        signal_text="Använd Time MCP för tidszonskonvertering.",
    )
    assert issue is not None
    question_data, _assistant_text = build_mcp_resource_selection_question(
        issue=issue,
        catalog=catalog,
        language="sv",
    )

    event = build_question_event(question_data)
    payload = json.loads(event["data"])

    assert payload["requires_confirm"] is True


def test_policy_feedback_rejects_mcp_after_user_declined() -> None:
    feedback = mcp_selection_policy_feedback(
        conversation=[
            ConversationMessage(
                role="user",
                content="Fortsätt utan MCP",
                metadata={
                    "question_answer": {
                        "question_id": "mcp_resource_selection",
                        "selected_values": ["without_mcp"],
                    }
                },
            )
        ],
        spec=_spec_with_step(
            name="Hämta tid",
            instructions="Hämta aktuell tid.",
            mcp_tool_refs=[TIME_TOOL_SLOT],
        ),
        catalog=_time_catalog(),
    )

    assert feedback is not None
    assert "continue without MCP" in feedback


def test_policy_feedback_rejects_live_data_claim_after_user_declined_mcp() -> None:
    feedback = mcp_selection_policy_feedback(
        conversation=[
            ConversationMessage(
                role="user",
                content="Fortsätt utan MCP",
                metadata={
                    "question_answer": {
                        "question_id": "mcp_resource_selection",
                        "selected_values": ["without_mcp"],
                    }
                },
            )
        ],
        spec=_spec_with_step(
            name="Hämta aktuell tid",
            instructions="Hämta aktuell tid och konvertera den till svensk tid.",
        ),
        catalog=_time_catalog(),
    )

    assert feedback is not None
    assert "fetch live/external data" in feedback


def test_policy_feedback_rejects_outbound_api_delivery_after_user_declined_mcp() -> (
    None
):
    feedback = mcp_selection_policy_feedback(
        conversation=[
            ConversationMessage(
                role="user",
                content="Fortsätt utan MCP",
                metadata={
                    "question_answer": {
                        "question_id": "mcp_resource_selection",
                        "selected_values": ["without_mcp"],
                    }
                },
            )
        ],
        spec=_spec_with_step(
            name="Leverera resultat",
            instructions="Skicka den extraherade informationen till ett API via POST.",
        ),
        catalog=_time_catalog(),
    )

    assert feedback is not None
    assert "live/external data" in feedback


def test_policy_feedback_allows_runtime_input_after_user_declined_mcp() -> None:
    feedback = mcp_selection_policy_feedback(
        conversation=[
            ConversationMessage(
                role="user",
                content="Fortsätt utan MCP",
                metadata={
                    "question_answer": {
                        "question_id": "mcp_resource_selection",
                        "selected_values": ["without_mcp"],
                    }
                },
            )
        ],
        spec=_spec_with_step(
            name="Normalisera angiven tid",
            instructions=(
                "Använd tidpunkten och tidszonen som användaren anger vid körning. "
                "Konvertera det angivna värdet till Europe/Stockholm."
            ),
        ),
        catalog=_time_catalog(),
    )

    assert feedback is None


def test_mcp_selection_answer_expires_after_new_named_mcp_request() -> None:
    conversation = [
        ConversationMessage(
            role="user",
            content="Fortsätt utan MCP",
            metadata={
                "question_answer": {
                    "question_id": "mcp_resource_selection",
                    "selected_values": ["without_mcp"],
                }
            },
        ),
        ConversationMessage(
            role="user",
            content="Jag ändrade mig, använd Time MCP.",
        ),
    ]

    assert mcp_resource_selection_values(conversation) == frozenset()
    assert mcp_selection_answer_allows_planning(conversation) is False


def test_mcp_selection_answer_stays_current_for_without_mcp_free_text() -> None:
    conversation = [
        ConversationMessage(
            role="user",
            content="Fortsätt utan MCP",
            metadata={
                "question_answer": {
                    "question_id": "mcp_resource_selection",
                    "selected_values": ["without_mcp"],
                }
            },
        ),
        ConversationMessage(
            role="user",
            content="Bygg planen utan MCP.",
        ),
    ]

    assert mcp_resource_selection_values(conversation) == frozenset({"without_mcp"})
    assert mcp_selection_answer_allows_planning(conversation) is True


def test_policy_feedback_rejects_unselected_mcp_server() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "time-server",
                "name": "Time MCP",
                "tools": [{"id": "current-time", "name": "get_current_time"}],
            },
            {
                "id": "svelte-server",
                "name": "Svelte mcp",
                "tools": [{"id": "svelte-docs", "name": "get-documentation"}],
            },
        ],
    )

    feedback = mcp_selection_policy_feedback(
        conversation=[
            ConversationMessage(
                role="user",
                content="Använd Time MCP",
                metadata={
                    "question_answer": {
                        "question_id": "mcp_resource_selection",
                            "selected_values": [f"use_mcp_server:{TIME_SERVER_SLOT}"],
                    }
                },
            )
        ],
        spec=_spec_with_step(
            name="Fel MCP",
            instructions="Använd Svelte MCP.",
            mcp_tool_refs=[SVELTE_TOOL_SLOT],
        ),
        catalog=catalog,
    )

    assert feedback is not None
    assert "Svelte mcp" in feedback
    assert "Time MCP" in feedback


def test_policy_feedback_accepts_selected_mcp_tool() -> None:
    feedback = mcp_selection_policy_feedback(
        conversation=[
            ConversationMessage(
                role="user",
                content="Använd Time MCP",
                metadata={
                    "question_answer": {
                        "question_id": "mcp_resource_selection",
                            "selected_values": [f"use_mcp_server:{TIME_SERVER_SLOT}"],
                    }
                },
            )
        ],
        spec=_spec_with_step(
            name="Hämta tid",
            instructions="Hämta aktuell tid.",
            mcp_tool_refs=[TIME_TOOL_SLOT],
        ),
        catalog=_time_catalog(),
    )

    assert feedback is None
