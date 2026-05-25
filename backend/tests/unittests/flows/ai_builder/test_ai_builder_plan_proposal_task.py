from __future__ import annotations

from datetime import datetime, timezone

from intric.flows.ai_builder.ai_builder_event_models import (
    RequirementsSummaryPayload,
)
from intric.flows.ai_builder.ai_builder_plan_proposal_task import (
    build_plan_proposal_system_prompt,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
    build_ai_builder_resource_catalog,
)
from intric.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    PlanningState,
    StepTriple,
)


def _requirements(**overrides: object) -> RequirementsSummaryPayload:
    payload = {
        "summary": "Test",
        "key_decisions": [],
        "input_description": "Test",
        "output_description": "Test",
    }
    payload.update(overrides)
    return RequirementsSummaryPayload.model_validate(payload)


def _empty_catalog() -> AIBuilderResourceCatalog:
    return build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[],
    )


def test_plan_proposal_prompt_includes_readable_resources_without_execution_surface():
    state = PlanningState.empty().model_copy(
        update={
            "architecture_commit": ArchitectureCommit(
                chosen_patterns=["mcp_lookup"],
                required_capabilities=["mcp_policy"],
                committed_at=datetime.now(timezone.utc),
                architecture_hash="a" * 64,
                tuples_chain=[
                    StepTriple(
                        input_type="text",
                        output_type="json",
                        output_mode="pass_through",
                    )
                ],
            )
        }
    )

    catalog = build_ai_builder_resource_catalog(
        available_models=[
            {
                "id": "model-fast",
                "ref": "model-fast",
                "name": "Fast model",
                "display_name": "Fast model",
                "provider": "test",
            },
        ],
        available_kbs=[
            {
                "id": "kb-policy",
                "ref": "kb-policy",
                "name": "Policy KB",
                "display_name": "Policy KB",
                "description": "Local policy reference material.",
            }
        ],
        available_mcps=[
            {
                "ref": "case-server",
                "display_name": "Case system",
                "description": "Reads current case data.",
                "tools": [
                    {
                        "ref": "case-lookup",
                        "display_name": "Lookup case",
                        "description": "Fetches a case by ID.",
                        "input_schema": {"type": "object"},
                    }
                ],
            }
        ],
    )

    prompt = build_plan_proposal_system_prompt(
        planning_state=state,
        confirmed_requirements=_requirements(
            summary="Look up a case and summarize it."
        ),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=catalog,
    )

    assert "Available resources:" in prompt
    assert "ref=`model.fast-model`" in prompt
    assert "ref=`knowledge.policy-kb`" in prompt
    assert "server_ref=`mcp_server.case-system`" in prompt
    assert "tool_ref=`mcp_tool.case-system-lookup-case`" in prompt
    assert (
        "Exception: when the Available resources section gives portable resource slot refs"
        in prompt
    )
    assert "human-readable `flow_name`" in prompt
    assert "mcp_lookup" not in prompt
    assert "mcp_policy" not in prompt
    assert "must not execute MCP tools" in prompt
    assert "input_schema" not in prompt
    assert "assistant_ref" not in prompt


def test_plan_proposal_prompt_honors_continue_without_mcp_decision():
    prompt = build_plan_proposal_system_prompt(
        planning_state=PlanningState.empty(),
        confirmed_requirements=_requirements(
            summary="Answer without external integrations."
        ),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
        mcp_selection_values={"without_mcp"},
    )

    assert "MCP selection decision:" in prompt
    assert "continue without MCP tools" in prompt
    assert "`mcp_server_refs` or `mcp_tool_refs`" in prompt
    assert (
        "do not claim that the flow fetches live or external data by itself" in prompt
    )
    assert "collect it as runtime input" in prompt


def test_plan_proposal_prompt_identifies_runtime_metadata_as_compiler_policy():
    prompt = build_plan_proposal_system_prompt(
        planning_state=PlanningState.empty(),
        confirmed_requirements=_requirements(
            summary="Skapa ett svenskt ljud till DOCX-flöde."
        ),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert "input_fields" in prompt
    assert "Runtime metadata policy" in prompt
    assert "compiler" in prompt
    assert "clearly ask for runtime metadata" in prompt


def test_plan_proposal_prompt_teaches_direct_text_transform_restraint():
    prompt = build_plan_proposal_system_prompt(
        planning_state=PlanningState.empty(),
        confirmed_requirements=_requirements(
            summary="Översätt en kort mening till engelska.",
        ),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert "Direct text transformations" in prompt
    assert "default to one text step" in prompt
    assert "only when the user explicitly asks" in prompt


def test_plan_proposal_prompt_omits_confirmed_requirement_boilerplate():
    prompt = build_plan_proposal_system_prompt(
        planning_state=PlanningState.empty(),
        confirmed_requirements=_requirements(
            summary="Översätt en kort svensk text till engelska.",
            input_description="Primär indata vid körning behöver granskas.",
            output_description="Huvudsakligt slutresultat behöver granskas.",
            assumptions=[
                "Planen ska följa kraven och underlaget i konversationen.",
                "Användaren ska kunna granska och ändra planen innan den tillämpas.",
                "Inga extra fält.",
            ],
        ),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert "- summary: Översätt en kort svensk text till engelska." in prompt
    assert "behöver granskas" not in prompt
    assert "Användaren ska kunna granska" not in prompt
    assert "Inga extra fält." in prompt


def test_plan_proposal_prompt_does_not_render_requirements_version() -> None:
    prompt = build_plan_proposal_system_prompt(
        planning_state=PlanningState.empty(),
        confirmed_requirements=_requirements(
            requirements_version="do-not-render",
            summary="Sammanfatta kunddialogen.",
            key_decisions=[{"topic": "Indata", "decision": "Ljudfil vid körning."}],
        ),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert "do-not-render" not in prompt
    assert "- Indata: Ljudfil vid körning." in prompt


def test_plan_proposal_prompt_scopes_audio_transcription_to_backend():
    prompt = build_plan_proposal_system_prompt(
        planning_state=PlanningState.empty(),
        confirmed_requirements=_requirements(
            summary="Skapa ett svenskt ljud till DOCX-flöde."
        ),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert "committed audio input" in prompt
    assert "backend inserts the first transcription/upload step" in prompt
    assert "after transcription" in prompt
    assert "include the leading transcription step with review_mode" in prompt
    assert "set that step's review_mode" in prompt
    assert "separate AI step" in prompt


def test_plan_proposal_prompt_honors_selected_mcp_server():
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "ref": "time-server",
                "display_name": "Time MCP",
                "description": "Kan hämta tiden.",
                "tools": [
                    {
                        "ref": "current-time",
                        "display_name": "get_current_time",
                        "description": "Get current time in a specific timezone.",
                    }
                ],
            }
        ],
    )

    prompt = build_plan_proposal_system_prompt(
        planning_state=PlanningState.empty(),
        confirmed_requirements=_requirements(
            summary="Use an enabled MCP for live data."
        ),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=catalog,
        mcp_selection_values={"use_mcp_server:mcp_server.time-mcp"},
    )

    assert "The user allowed these MCP server refs: `mcp_server.time-mcp`." in prompt
    assert "Prefer specific `mcp_tool_refs`" in prompt
    assert "Selected MCP tools available for step-level use" in prompt
    assert "tool_ref=`mcp_tool.time-mcp-get-current-time`" in prompt
    assert "server_ref=`mcp_server.time-mcp`" in prompt


def test_plan_proposal_prompt_drops_selected_mcp_ref_that_is_not_in_catalog():
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "ref": "time-server",
                "display_name": "Time MCP",
                "tools": [{"ref": "current-time", "display_name": "get_current_time"}],
            }
        ],
    )

    prompt = build_plan_proposal_system_prompt(
        planning_state=PlanningState.empty(),
        confirmed_requirements=_requirements(
            summary="Use an enabled MCP for live data."
        ),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=catalog,
        mcp_selection_values={"use_mcp_server:missing-server"},
    )

    assert "Available resources:" in prompt
    assert "server_ref=`mcp_server.time-mcp`" in prompt
    assert "MCP selection decision:" not in prompt
    assert "missing-server" not in prompt
