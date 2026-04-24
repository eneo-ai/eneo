"""Regression coverage for the `draft_plan` subschema prompt contract.

Production parse_failed landed with
`planning_state_delta.draft_plan.plan_reference` / `extra_forbidden`
(failure_fingerprint `b6bb46ca7c87`): the LLM merged two prompt
signals — "populate draft_plan when kind=propose_plan" and
"propose_plan payload has plan_reference" — and placed
`plan_reference` inside `draft_plan`, where it is not a declared
field. The prompt never showed what shape `draft_plan` has.

These tests pin two contracts:

1. The knowledge-pack prompt must declare the `draft_plan` shape
   (the three pinned keys `plan_id`, `steps`, `form_fields`) AND
   must explicitly say `plan_reference` belongs in
   `planner_action.payload`, not in `draft_plan`.
2. A planner output that places `plan_reference` at the correct
   location (`planner_action.payload.plan_reference`) must parse.
   This is the positive shape the fixed prompt steers the LLM
   toward.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from intric.flows.ai_builder.ai_builder_knowledge_pack import (
    build_role_and_protocol,
)
from intric.flows.ai_builder.ai_builder_orchestrator import (
    ProposePlanAction,
    parse_planner_output,
)
from intric.flows.ai_builder.ai_builder_repair import (
    build_parse_repair_user_message,
)


class TestKnowledgePackDeclaresDraftPlanShape:
    def test_create_mode_prompt_shows_draft_plan_subschema(self) -> None:
        prompt = build_role_and_protocol(is_edit_mode=False)
        assert "plan_id" in prompt, (
            "prompt must show `plan_id` as a draft_plan field so the LLM "
            "stops inventing plan_reference-style siblings"
        )
        assert "steps" in prompt, "prompt must show `steps` as a draft_plan field"
        assert "form_fields" in prompt, (
            "prompt must show `form_fields` as a draft_plan field"
        )

    def test_edit_mode_prompt_shows_draft_plan_subschema(self) -> None:
        prompt = build_role_and_protocol(is_edit_mode=True)
        assert "plan_id" in prompt
        assert "steps" in prompt
        assert "form_fields" in prompt

    def test_prompt_places_plan_reference_in_payload_not_draft_plan(self) -> None:
        prompt = build_role_and_protocol(is_edit_mode=False)
        assert "plan_reference" in prompt
        # The anti-confusion directive must call out the right location
        # explicitly — `plan_reference` belongs in `planner_action.payload`.
        assert "planner_action.payload" in prompt or "planner_action" in prompt, (
            "prompt must reference planner_action so the layout is anchored"
        )
        # And an explicit "never in draft_plan" directive is the
        # anti-bug rail for the exact failure this test guards.
        lowered = prompt.lower()
        assert "plan_reference" in prompt and "draft_plan" in lowered, (
            "prompt should co-locate the two terms where the rule is stated"
        )

    def test_prompt_directive_forbids_plan_reference_in_draft_plan(self) -> None:
        """The prompt must include an explicit directive the LLM can ground on.

        The bug repro had both `draft_plan` and `plan_reference` in the
        prompt already but no rule binding them. Landing a directive
        like "plan_reference belongs in planner_action.payload, NEVER
        in draft_plan" is the anti-confusion rail.
        """
        prompt = build_role_and_protocol(is_edit_mode=False)
        lowered = prompt.lower()
        has_directive = (
            "plan_reference" in prompt and "planner_action.payload" in prompt
        ) and ("aldrig" in lowered or "never" in lowered or "inte" in lowered)
        assert has_directive, (
            "prompt must contain a negative directive binding plan_reference "
            "to planner_action.payload (e.g. `plan_reference hör hemma i "
            "planner_action.payload — lägg det ALDRIG i draft_plan`)"
        )


class TestParserAcceptsCorrectlyPlacedPlanReference:
    def test_propose_plan_with_payload_plan_reference_parses(self) -> None:
        raw = json.dumps(
            {
                "planning_state_delta": {
                    "base_planning_state_version": 1,
                    "draft_plan": {
                        "plan_id": "v1",
                        "steps": [],
                        "form_fields": [],
                    },
                },
                "planner_action": {
                    "kind": "propose_plan",
                    "payload": {"plan_reference": "latest"},
                },
            }
        )

        output = parse_planner_output(raw)
        assert isinstance(output.planner_action, ProposePlanAction)
        assert output.planner_action.payload.plan_reference == "latest"

    def test_propose_plan_with_plan_reference_in_draft_plan_is_rejected(
        self,
    ) -> None:
        """Negative contract: the exact production-bug shape stays rejected.

        Losing this rejection would silently accept LLM drift. The
        point of the prompt fix is to STEER the LLM away from this
        shape, NOT to relax the schema.
        """
        raw = json.dumps(
            {
                "planning_state_delta": {
                    "base_planning_state_version": 1,
                    "draft_plan": {"plan_reference": "latest"},
                },
                "planner_action": {
                    "kind": "propose_plan",
                    "payload": {"plan_reference": "latest"},
                },
            }
        )

        with pytest.raises(ValidationError) as exc_info:
            parse_planner_output(raw)

        errors = exc_info.value.errors()
        assert any(
            "draft_plan" in ".".join(str(part) for part in err.get("loc", ()))
            and err.get("type") == "extra_forbidden"
            for err in errors
        ), "extra_forbidden guard on draft_plan must stay live"


class TestParseRepairPromptCarriesLayoutReminder:
    """Parse-repair is defense-in-depth; a short layout reminder rescues
    the retry when the system prompt fix hasn't taken effect yet (e.g. a
    weaker model or a mid-rollout deploy). Codex flagged this as a
    recency-effect fit: the retry user-turn is the most recent context
    the model sees, so a one-liner there catches misplaced keys even
    when the system-prompt directive got lost in 19 KB of context.
    """

    def test_repair_user_message_mentions_plan_reference_location(self) -> None:
        message = build_parse_repair_user_message(
            parse_error_message="Extra inputs are not permitted",
        )
        assert "plan_reference" in message
        assert "planner_action.payload" in message
        assert "draft_plan" in message

    def test_repair_user_message_echoes_parse_error(self) -> None:
        message = build_parse_repair_user_message(
            parse_error_message="some specific validator complaint",
        )
        assert "some specific validator complaint" in message
