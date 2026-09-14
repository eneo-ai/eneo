import { describe, expect, it } from "vitest";

import { m } from "$lib/paraglide/messages";

import type { AIBuilderError, AIBuilderLatestTurn } from "./protocol";
import {
  classifyFailure,
  describeFailure,
  type FailurePresentationContext,
  type FailureRecoveryCapabilities
} from "./aiBuilderFailurePresentation";

const error = (overrides: Partial<AIBuilderError> = {}): AIBuilderError => ({
  schema_version: 2,
  code: "planner_stream_failed",
  category: "upstream",
  message: "Modellen svarade inte i tid.",
  phase: "planner",
  request_id: "req-1",
  eneo_error_code: null,
  diagnostic_context: null,
  details: {},
  ...overrides
});

const rejected = {
  another_call_permitted: false,
  provider_disposition: "known_rejection",
  retry_scope: "new_turn"
};

const turn = (state: AIBuilderLatestTurn["state"]): AIBuilderLatestTurn => ({
  client_turn_id: "11111111-1111-4111-8111-111111111111",
  state,
  user_message_id: "11111111-1111-4111-8111-111111111112",
  error: null,
  requires_duplicate_provider_spend_acknowledgement: state === "provider_outcome_unknown",
  retry_request: {
    client_turn_id: "11111111-1111-4111-8111-111111111111",
    message: "Bygg ett flöde",
    ui_language: "sv",
    acknowledge_duplicate_provider_spend: false
  }
});

/** A committed failure whose request can go again as a new turn. */
const committed: FailureRecoveryCapabilities = {
  replay: null,
  canResend: true,
  canStartNewTurn: true,
  turnActive: false
};
const generation: FailurePresentationContext = {
  surface: "generation",
  targetKind: "create",
  offersStartFresh: false
};
const chat: FailurePresentationContext = { ...generation, surface: "chat" };

/** The presentation for a case that has one; the null case has its own test. */
const present = (input: Parameters<typeof describeFailure>[0]) => {
  const presentation = describeFailure(input);
  if (!presentation) throw new Error("Expected something to present");
  return presentation;
};

describe("describeFailure", () => {
  it("presents nothing without an error or a retained replay, and a replay on its own", () => {
    expect(
      describeFailure({ error: null, latestTurn: null, capabilities: committed, context: chat })
    ).toBeNull();
    const replayOnly = present({
      error: null,
      latestTurn: turn("failed_before_provider"),
      capabilities: { ...committed, replay: "failed_before_provider" },
      context: chat
    });
    expect(replayOnly.heading).toBe(m.ai_builder_turn_failed_before_provider_title());
    expect(replayOnly.primary?.kind).toBe("retry_same_turn");
    expect(replayOnly.technical).toBeNull();
  });

  // One case per public failure class on a committed, resendable turn: the
  // heading names what happened, the primary is the one best next step.
  it.each([
    {
      name: "a provider rejection",
      failure: error({ code: "planner_upstream_error", details: rejected }),
      kind: "provider_rejected",
      heading: m.ai_builder_failure_heading_provider_rejected(),
      primary: "retry_new_turn",
      secondary: "clarify"
    },
    {
      name: "an exhausted request budget",
      failure: error({ code: "planner_context_limit_exceeded" }),
      kind: "request_budget_exhausted",
      heading: m.ai_builder_failure_heading_request_budget_exhausted(),
      primary: "clarify",
      secondary: null
    },
    {
      name: "a truncated answer",
      failure: error({ code: "planner_output_too_long", phase: "proposal" }),
      kind: "output_too_long",
      heading: m.ai_builder_failure_heading_output_too_long(),
      primary: "clarify",
      secondary: "retry_new_turn"
    },
    {
      name: "an invalid proposal after repairs",
      failure: error({ code: "self_correction_invalid_plan", phase: "self_correction" }),
      kind: "invalid_proposal",
      heading: m.ai_builder_failure_heading_invalid_proposal(),
      primary: "clarify",
      secondary: "retry_new_turn"
    },
    {
      name: "a transport failure this client saw",
      failure: error({ code: "network", category: "network", phase: "client" }),
      kind: "network_loss",
      heading: m.ai_builder_failure_heading_network_loss_generation(),
      primary: "retry_new_turn",
      secondary: "clarify"
    },
    {
      name: "anything the client cannot name, quoting the server",
      failure: error(),
      kind: "other",
      heading: m.ai_builder_failure_heading_other_generation(),
      primary: "retry_new_turn",
      secondary: "clarify"
    }
  ] as const)("presents $name", ({ failure, kind, heading, primary, secondary }) => {
    const presentation = present({
      error: failure,
      latestTurn: turn("committed"),
      capabilities: committed,
      context: generation
    });

    expect(classifyFailure(failure, turn("committed"))).toBe(kind);
    expect(presentation.kind).toBe(kind);
    expect(presentation.heading).toBe(heading);
    expect(presentation.primary?.kind).toBe(primary);
    expect(presentation.secondary?.kind ?? null).toBe(secondary);
    expect(presentation.consequence.endsWith(m.ai_builder_failure_preserved_create())).toBe(true);
    expect(presentation.technical).toEqual({ code: failure.code, requestId: "req-1" });
  });

  it("lets the turn state outrank the payload for the two classes only the server knows", () => {
    const rejection = error({ code: "planner_upstream_error", details: rejected });
    expect(classifyFailure(rejection, turn("provider_outcome_unknown"))).toBe(
      "provider_outcome_unknown"
    );
    expect(classifyFailure(rejection, turn("failed_before_provider"))).toBe(
      "failed_before_provider"
    );
    // Without a turn, the payload's own disposition still names it.
    expect(
      classifyFailure(
        error({ details: { provider_disposition: "provider_outcome_unknown" } }),
        null
      )
    ).toBe("provider_outcome_unknown");
  });

  it("offers only the paid replay for an unknown outcome and says what it costs", () => {
    const presentation = present({
      error: error({ code: "session_turn_provider_outcome_unknown" }),
      latestTurn: turn("provider_outcome_unknown"),
      capabilities: { ...committed, replay: "provider_outcome_unknown", canStartNewTurn: false },
      context: generation
    });

    expect(presentation.heading).toBe(m.ai_builder_failure_heading_provider_outcome_unknown());
    expect(presentation.consequence).toContain(
      m.ai_builder_failure_cause_provider_outcome_unknown()
    );
    expect(presentation.primary).toMatchObject({
      kind: "retry_same_turn_acknowledged",
      label: m.ai_builder_turn_retry_with_cost_acknowledgement(),
      records: "retry_with_acknowledgement_requested"
    });
    expect(presentation.secondary).toBeNull();
  });

  it("offers the safe replay and names the fact that no model was called", () => {
    const presentation = present({
      error: error({ code: "planner_budget_missing", message: "No planner budget." }),
      latestTurn: turn("failed_before_provider"),
      // A retained pre-provider turn fences new messages: no rewording offer.
      capabilities: { ...committed, replay: "failed_before_provider", canStartNewTurn: false },
      context: generation
    });

    expect(presentation.kind).toBe("failed_before_provider");
    expect(presentation.heading).toBe(m.ai_builder_turn_failed_before_provider_title());
    expect(presentation.consequence).toContain(
      m.ai_builder_turn_failed_before_provider_description()
    );
    expect(presentation.consequence).not.toContain("No planner budget.");
    expect(presentation.primary).toMatchObject({
      kind: "retry_same_turn",
      records: "retry_requested"
    });
    expect(presentation.secondary).toBeNull();
  });

  it("only fetches the latest state while the lost turn still runs or a refresh is owed", () => {
    const network = error({ code: "network", category: "network", phase: "client" });
    const running = present({
      error: network,
      latestTurn: turn("processing"),
      capabilities: { ...committed, canStartNewTurn: false, turnActive: true },
      context: generation
    });
    expect(running.consequence).toContain(m.ai_builder_failure_cause_network_loss_turn_active());
    expect(running.primary).toMatchObject({ kind: "refresh", records: "refresh_requested" });
    expect(running.secondary).toBeNull();

    const owed = present({
      error: network,
      latestTurn: turn("committed"),
      capabilities: { ...committed, canStartNewTurn: false },
      context: generation
    });
    expect(owed.primary?.kind).toBe("refresh");
  });

  it("falls back to rewording when the server retained nothing to send again", () => {
    const presentation = present({
      error: error({ code: "planner_upstream_error", details: rejected }),
      latestTurn: { ...turn("committed"), retry_request: null },
      capabilities: { ...committed, canResend: false },
      context: generation
    });

    expect(presentation.primary).toMatchObject({ kind: "clarify", records: "conversation_opened" });
    expect(presentation.secondary).toBeNull();
  });

  it("names the shorter task for size failures and the clearer task otherwise", () => {
    const shorten = present({
      error: error({ code: "planner_output_too_long" }),
      latestTurn: turn("committed"),
      capabilities: committed,
      context: generation
    });
    const clarify = present({
      error: error({ code: "self_correction_invalid_plan" }),
      latestTurn: turn("committed"),
      capabilities: committed,
      context: generation
    });
    expect(shorten.primary?.label).toBe(m.ai_builder_failure_action_shorten());
    expect(clarify.primary?.label).toBe(m.ai_builder_failure_action_clarify());
  });

  it("tells an edit session that the saved flow is untouched", () => {
    const presentation = present({
      error: error(),
      latestTurn: turn("committed"),
      capabilities: committed,
      context: { ...generation, targetKind: "edit" }
    });
    expect(presentation.consequence.endsWith(m.ai_builder_failure_preserved_edit())).toBe(true);
  });

  it("gives the chat surface the same words but only what that surface can do", () => {
    const rejection = error({ code: "planner_upstream_error", details: rejected });
    const onChat = present({
      error: rejection,
      latestTurn: turn("committed"),
      capabilities: committed,
      context: chat
    });
    const onGeneration = present({
      error: rejection,
      latestTurn: turn("committed"),
      capabilities: committed,
      context: generation
    });

    expect(onChat.heading).toBe(onGeneration.heading);
    // Only the generation surface may say a plan was being drafted.
    const network = error({ code: "network", category: "network", phase: "client" });
    expect(
      present({
        error: network,
        latestTurn: turn("committed"),
        capabilities: committed,
        context: chat
      }).heading
    ).toBe(m.ai_builder_failure_heading_network_loss());
    expect(
      present({
        error: network,
        latestTurn: turn("committed"),
        capabilities: committed,
        context: generation
      }).heading
    ).toBe(m.ai_builder_failure_heading_network_loss_generation());
    // No preservation claim away from the plan that failed to arrive.
    expect(onChat.consequence).toBe(m.ai_builder_failure_cause_provider_rejected());
    expect(onChat.primary).toMatchObject({ kind: "dismiss", records: "dismissed" });
    expect(onChat.secondary).toBeNull();
    // The server's replay is the same offer on both surfaces.
    const replay = { ...committed, replay: "provider_outcome_unknown" as const };
    expect(
      present({
        error: rejection,
        latestTurn: turn("provider_outcome_unknown"),
        capabilities: replay,
        context: chat
      }).primary?.kind
    ).toBe("retry_same_turn_acknowledged");
  });

  it("puts a named template problem and its one fix in front of the user", () => {
    const refused = error({
      code: "architecture_materialization_failed",
      category: "bad_request",
      phase: "proposal",
      details: {
        failure_code: "template_attachment_selection_invalid",
        architecture_repair_disposition: "user_action"
      }
    });
    const shown = present({
      error: refused,
      latestTurn: null,
      capabilities: committed,
      context: generation
    });
    expect(shown.kind).toBe("other");
    expect(shown.consequence).toContain(
      m.ai_builder_failure_problem_template_attachment_selection_invalid()
    );
    expect(shown.consequence).not.toContain(refused.message);
    expect(shown.primary).toEqual({
      kind: "clarify",
      label: m.ai_builder_failure_problem_action_select_docx_template(),
      records: "conversation_opened"
    });
    expect(shown.secondary).toBeNull();

    const unresolved = present({
      error: error({
        code: "architecture_materialization_failed",
        details: {
          failure_code: "template_placeholder_unresolved",
          unresolved_placeholders: "diarienummer, handläggare"
        }
      }),
      latestTurn: null,
      capabilities: committed,
      context: generation
    });
    expect(unresolved.consequence).toContain("diarienummer, handläggare");
    expect(unresolved.primary?.label).toBe(
      m.ai_builder_failure_problem_action_describe_template_fields()
    );
  });

  it("keeps the named problem's words on the chat surface but only that surface's action", () => {
    const shown = present({
      error: error({
        code: "architecture_materialization_failed",
        details: { failure_code: "template_attachment_unreadable" }
      }),
      latestTurn: null,
      capabilities: committed,
      context: chat
    });
    expect(shown.consequence).toContain(
      m.ai_builder_failure_problem_template_attachment_unreadable()
    );
    expect(shown.primary?.kind).toBe("dismiss");
  });

  it("falls back to the generic words when the reason is not one the user can act on", () => {
    const shown = present({
      error: error({
        code: "architecture_materialization_failed",
        message: "Servern kunde inte bygga flödet.",
        details: { failure_code: "scoped_edit_preservation_failed" }
      }),
      latestTurn: null,
      capabilities: committed,
      context: generation
    });
    expect(shown.consequence).toContain("Servern kunde inte bygga flödet.");
    expect(shown.primary?.kind).toBe("retry_new_turn");
  });

  it("keeps the question refusals and the standing start-over offer in the user's terms", () => {
    const refusal = present({
      error: error({
        code: "invalid_question_payload",
        category: "bad_request",
        details: { reason: "delegation_without_recommendation" }
      }),
      latestTurn: null,
      capabilities: committed,
      context: chat
    });
    expect(refusal.heading).toBe(m.ai_builder_question_delegate());
    expect(refusal.consequence).toBe(m.ai_builder_question_delegation_unavailable());
    expect(refusal.primary?.kind).toBe("dismiss");

    const unsupported = present({
      error: error({ code: "unsupported_architecture", category: "bad_request" }),
      latestTurn: null,
      capabilities: committed,
      context: { ...chat, offersStartFresh: true }
    });
    expect(unsupported.heading).toBe(m.ai_builder_unsupported_architecture_title());
    expect(unsupported.primary).toMatchObject({
      kind: "start_fresh",
      label: m.ai_builder_start_fresh(),
      records: "start_fresh_requested"
    });
  });
});
