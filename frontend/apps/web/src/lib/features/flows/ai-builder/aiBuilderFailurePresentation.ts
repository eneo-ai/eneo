import { m } from "$lib/paraglide/messages";

import type {
  AIBuilderClientErrorFirstAction,
  AIBuilderClientErrorPresentation,
  AIBuilderError,
  AIBuilderLatestTurn,
  AIBuilderTurnRecoveryState,
  TargetKind
} from "./protocol";

/**
 * The one owner of how a Builder failure is put to the user: what happened
 * (cause), what it means for them (consequence), the single best next step
 * and at most one alternative (actions), and the quiet technical facts. The
 * generation card and the turn alert both render this object, so the two
 * surfaces never disagree on words or on what the turn state allows.
 *
 * Eligibility is never derived from the turn alone: the surface passes the
 * driver's recovery capabilities (which already fold in the authoritative
 * refresh and any recovery in flight) and its own presentation context.
 */

export type FailureKind = AIBuilderClientErrorPresentation;

export type FailureSurface = "generation" | "chat";

export interface FailureRecoveryCapabilities {
  /** The same-turn replay the server retained, when its state allows one. */
  replay: AIBuilderTurnRecoveryState | null;
  /** A committed failure whose retained request can go again as a new turn. */
  canResend: boolean;
  /** The session accepts a new message right now. */
  canStartNewTurn: boolean;
  /** The latest turn is still open or processing on the server. */
  turnActive: boolean;
  /** The model a same-turn replay runs when it is not the one the composer
   *  shows: its listed name, "previous" when it is no longer listed, or null
   *  when they are the same (or the retained request named none). A replay
   *  keeps its retained request, so the button has to say which model runs. */
  replayModel: string | "previous" | null;
}

export interface FailurePresentationContext {
  surface: FailureSurface;
  targetKind: TargetKind;
  /** The create-mode start-over offer that stands while a refusal is shown. */
  offersStartFresh: boolean;
}

export type FailureActionKind =
  | "retry_same_turn"
  | "retry_same_turn_acknowledged"
  | "retry_new_turn"
  | "clarify"
  | "attach_template"
  | "refresh"
  | "start_fresh"
  | "dismiss";

export interface FailureAction {
  kind: FailureActionKind;
  label: string;
  /** What the observation records when the user chooses this control. */
  records: AIBuilderClientErrorFirstAction;
}

export interface FailurePresentation {
  kind: FailureKind;
  heading: string;
  consequence: string;
  primary: FailureAction | null;
  secondary: FailureAction | null;
  /** Null when the server retained a turn state but no error payload. */
  technical: { code: string; requestId: string | null } | null;
}

const INVALID_PROPOSAL_CODES: ReadonlySet<string> = new Set([
  "planner_invalid_repair_response",
  "planner_parse_error",
  "self_correction_invalid_payload",
  "self_correction_invalid_plan",
  "self_correction_quality_failure"
]);

/** A refusal that names a problem the user can act on: the server's own
 *  reason selects the words and the one matching next step. Display text is
 *  never parsed.
 *
 *  The reason arrives in one of two shapes, because the same problem is
 *  refused at two points in the turn. Before planning, the action policy
 *  refuses with a top-level `AIBuilderErrorCode` — the generated, closed
 *  vocabulary, and the common path. During planning, an architecture producer
 *  raises a `user_action` failure whose typed `failure_code` is published in
 *  `details`. Both are server declarations; neither is inferred here.
 *
 *  Producer reasons declared `model_correctable` are deliberately absent: they
 *  become a repair round, never a terminal error, so mapping them would be
 *  dead copy. A repair round that exhausts its budget reports its codes under
 *  the plural `details.failure_codes`, which this never reads — one actionable
 *  problem out of a set needs a server-side choice, not a client guess. */
interface ActionableProblem {
  cause: string;
  actionLabel: string;
  /** The control needed to resolve the problem in the conversation. */
  fix: "attach_template" | "clarify" | "change_model";
}

function actionableProblem(error: AIBuilderError): ActionableProblem | null {
  const detailReason = error.details.failure_code;
  const reason = typeof detailReason === "string" ? detailReason : error.code;
  switch (reason) {
    case "planner_model_incompatible_token_limits":
      return {
        cause: m.ai_builder_model_capacity_too_small(),
        actionLabel: m.choose_a_completion_model(),
        fix: "change_model"
      };
    case "template_attachment_selection_invalid":
      return {
        cause: m.ai_builder_failure_problem_template_attachment_selection_invalid(),
        actionLabel: m.ai_builder_failure_problem_action_select_docx_template(),
        fix: "attach_template"
      };
    case "template_attachment_unreadable":
    case "template_placeholder_path_invalid":
      return {
        cause:
          reason === "template_attachment_unreadable"
            ? m.ai_builder_failure_problem_template_attachment_unreadable()
            : m.ai_builder_failure_problem_template_placeholder_path_invalid(),
        actionLabel: m.ai_builder_failure_problem_action_replace_docx_template(),
        fix: "attach_template"
      };
    case "template_placeholder_unresolved": {
      const placeholders = error.details.unresolved_placeholders;
      return {
        cause:
          typeof placeholders === "string" && placeholders.trim()
            ? m.ai_builder_failure_problem_template_placeholder_unresolved_named({
                placeholders
              })
            : m.ai_builder_failure_problem_template_placeholder_unresolved(),
        actionLabel: m.ai_builder_failure_problem_action_describe_template_fields(),
        fix: "clarify"
      };
    }
    default:
      return null;
  }
}

/** Which public failure the user is looking at, in the closed vocabulary the
 *  observation persists. The turn state outranks the payload: only the
 *  server knows whether an outcome is still unknown or whether a model was
 *  ever called. A network loss is only claimed for a transport failure this
 *  client saw. */
export function classifyFailure(
  error: AIBuilderError,
  latestTurn: AIBuilderLatestTurn | null
): FailureKind {
  const state = latestTurn?.state ?? null;
  if (state === "provider_outcome_unknown") return "provider_outcome_unknown";
  if (state === "failed_before_provider") return "failed_before_provider";
  if (
    state === null &&
    (error.code === "session_turn_provider_outcome_unknown" ||
      error.details.provider_disposition === "provider_outcome_unknown")
  ) {
    return "provider_outcome_unknown";
  }
  if (error.category === "network") return "network_loss";
  if (error.details.provider_disposition === "known_rejection") return "provider_rejected";
  if (error.code === "planner_context_limit_exceeded") return "request_budget_exhausted";
  if (error.code === "planner_output_too_long") return "output_too_long";
  if (INVALID_PROPOSAL_CODES.has(error.code)) return "invalid_proposal";
  return "other";
}

/** Refusals that are about one question or one setup rather than the turn:
 *  named in the user's terms, never as a payload error. */
function specialCase(error: AIBuilderError): { heading: string; cause: string } | null {
  if (error.code === "unsupported_architecture") {
    return {
      heading: m.ai_builder_unsupported_architecture_title(),
      cause: m.ai_builder_unsupported_architecture_description()
    };
  }
  if (error.code !== "invalid_question_payload") return null;
  const reason = error.details.reason;
  if (reason === "delegation_without_recommendation") {
    return {
      heading: m.ai_builder_question_delegate(),
      cause: m.ai_builder_question_delegation_unavailable()
    };
  }
  if (reason === "delegation_without_pending_question") {
    return {
      heading: m.ai_builder_question_delegate(),
      cause: m.ai_builder_question_delegation_stale()
    };
  }
  if (reason === "requirements_version_stale") {
    return {
      heading: m.ai_builder_question_delegate(),
      cause: m.ai_builder_content_field_edit_stale()
    };
  }
  if (reason === "invalid_field_name") {
    const field = error.details.field_name;
    return {
      heading: m.ai_builder_question_delegate(),
      cause:
        typeof field === "string" && field.trim()
          ? m.ai_builder_content_field_edit_invalid_named({ field })
          : m.ai_builder_content_field_edit_invalid()
    };
  }
  return null;
}

function heading(kind: FailureKind, surface: FailureSurface): string {
  switch (kind) {
    case "provider_outcome_unknown":
      return m.ai_builder_failure_heading_provider_outcome_unknown();
    case "failed_before_provider":
      return m.ai_builder_turn_failed_before_provider_title();
    case "network_loss":
      // Only the generation surface knows a plan was being drafted.
      return surface === "generation"
        ? m.ai_builder_failure_heading_network_loss_generation()
        : m.ai_builder_failure_heading_network_loss();
    case "provider_rejected":
      return m.ai_builder_failure_heading_provider_rejected();
    case "request_budget_exhausted":
      return m.ai_builder_failure_heading_request_budget_exhausted();
    case "output_too_long":
      return m.ai_builder_failure_heading_output_too_long();
    case "invalid_proposal":
      return m.ai_builder_failure_heading_invalid_proposal();
    case "other":
      // The one class this client cannot name; only the generation surface
      // knows which operation failed.
      return surface === "generation"
        ? m.ai_builder_failure_heading_other_generation()
        : m.ai_builder_failure_heading_other();
  }
}

function cause(
  kind: FailureKind,
  error: AIBuilderError | null,
  capabilities: FailureRecoveryCapabilities,
  surface: FailureSurface
): string {
  switch (kind) {
    case "provider_outcome_unknown":
      return m.ai_builder_failure_cause_provider_outcome_unknown();
    case "failed_before_provider":
      // The fact that nothing was spent stands alone; the code is in the
      // technical line and the server's words in the diagnostic report.
      return m.ai_builder_turn_failed_before_provider_description();
    case "network_loss":
      if (capabilities.turnActive) return m.ai_builder_failure_cause_network_loss_turn_active();
      return surface === "generation"
        ? m.ai_builder_failure_cause_network_loss_generation()
        : m.ai_builder_failure_cause_network_loss();
    case "provider_rejected":
      return m.ai_builder_failure_cause_provider_rejected();
    case "request_budget_exhausted":
      return m.ai_builder_failure_cause_request_budget_exhausted();
    case "output_too_long":
      return m.ai_builder_failure_cause_output_too_long();
    case "invalid_proposal":
      return m.ai_builder_failure_cause_invalid_proposal();
    case "other":
      return error?.message ?? "";
  }
}

const SHORTEN_KINDS: ReadonlySet<FailureKind> = new Set([
  "request_budget_exhausted",
  "output_too_long"
]);

const action = {
  retrySameTurn: (model: FailureRecoveryCapabilities["replayModel"]): FailureAction => ({
    kind: "retry_same_turn",
    label:
      model === null
        ? m.ai_builder_turn_retry()
        : model === "previous"
          ? m.ai_builder_turn_retry_previous_model()
          : m.ai_builder_turn_retry_with_model({ model }),
    records: "retry_requested"
  }),
  retryAcknowledged: (model: FailureRecoveryCapabilities["replayModel"]): FailureAction => ({
    kind: "retry_same_turn_acknowledged",
    label:
      model === null
        ? m.ai_builder_turn_retry_with_cost_acknowledgement()
        : model === "previous"
          ? m.ai_builder_turn_retry_previous_model_and_cost_acknowledgement()
          : m.ai_builder_turn_retry_with_model_and_cost_acknowledgement({ model }),
    records: "retry_with_acknowledgement_requested"
  }),
  retryNewTurn: (): FailureAction => ({
    kind: "retry_new_turn",
    label: m.ai_builder_turn_retry(),
    records: "resend_requested"
  }),
  clarify: (kind: FailureKind): FailureAction => ({
    kind: "clarify",
    label: SHORTEN_KINDS.has(kind)
      ? m.ai_builder_failure_action_shorten()
      : m.ai_builder_failure_action_clarify(),
    records: "conversation_opened"
  }),
  // The named problem is fixed in the conversation; the kind says which
  // control the user lands on there, and the label says which fix it is.
  // Both open the conversation, so both record that it was opened.
  fixProblem: (problem: ActionableProblem): FailureAction => ({
    kind: problem.fix === "change_model" ? "clarify" : problem.fix,
    label: problem.actionLabel,
    records: "conversation_opened"
  }),
  refresh: (): FailureAction => ({
    kind: "refresh",
    label: m.ai_builder_failure_action_refresh(),
    records: "refresh_requested"
  }),
  startFresh: (): FailureAction => ({
    kind: "start_fresh",
    label: m.ai_builder_start_fresh(),
    records: "start_fresh_requested"
  }),
  dismiss: (): FailureAction => ({
    kind: "dismiss",
    label: m.ai_builder_dismiss(),
    records: "dismissed"
  })
};

type Actions = Pick<FailurePresentation, "primary" | "secondary">;

function actionsFor(
  kind: FailureKind,
  special: boolean,
  capabilities: FailureRecoveryCapabilities,
  context: FailurePresentationContext,
  problem: ActionableProblem | null = null
): Actions {
  const chat = context.surface === "chat";
  if (context.offersStartFresh) return { primary: action.startFresh(), secondary: null };
  if (special) return { primary: chat ? action.dismiss() : null, secondary: null };
  // Same-turn replays are the server's to offer; nothing else is a replay.
  if (capabilities.replay === "provider_outcome_unknown") {
    return { primary: action.retryAcknowledged(capabilities.replayModel), secondary: null };
  }
  if (capabilities.replay === "failed_before_provider") {
    // Rewording is only offered where the composer will accept it; a
    // retained pre-provider turn usually fences new messages.
    return {
      primary: action.retrySameTurn(capabilities.replayModel),
      secondary: !chat && capabilities.canStartNewTurn ? action.clarify(kind) : null
    };
  }
  // A turn still running, a refresh still owed, or a recovery in flight: the
  // only honest step is to fetch the state.
  if (capabilities.turnActive || !capabilities.canStartNewTurn) {
    return { primary: action.refresh(), secondary: null };
  }
  // The chat surface shows failures of any operation; it offers no resend and
  // no reword of the plan there, only the way to acknowledge the message.
  if (chat) return { primary: action.dismiss(), secondary: null };
  if (problem?.fix === "change_model") {
    return { primary: action.fixProblem(problem), secondary: null };
  }
  if (!capabilities.canResend) return { primary: action.clarify(kind), secondary: null };
  // A named problem has one fix; sending the same request again cannot be it.
  if (problem) return { primary: action.fixProblem(problem), secondary: null };
  // A committed generation failure: the same request again is pointless when
  // it was too big, worth one more try when the answer was merely cut off or
  // malformed, and the first thing to do when the service did not deliver.
  switch (kind) {
    case "request_budget_exhausted":
      return { primary: action.clarify(kind), secondary: null };
    case "output_too_long":
    case "invalid_proposal":
      return { primary: action.clarify(kind), secondary: action.retryNewTurn() };
    case "provider_outcome_unknown":
    case "failed_before_provider":
    case "network_loss":
    case "provider_rejected":
    case "other":
      return { primary: action.retryNewTurn(), secondary: action.clarify(kind) };
  }
}

/** Null when there is nothing to present: no error, and no retained turn
 *  state that offers a replay. */
export function describeFailure({
  error,
  latestTurn,
  capabilities,
  context
}: {
  error: AIBuilderError | null;
  latestTurn: AIBuilderLatestTurn | null;
  capabilities: FailureRecoveryCapabilities;
  context: FailurePresentationContext;
}): FailurePresentation | null {
  if (error === null && capabilities.replay === null) return null;
  const kind: FailureKind = error ? classifyFailure(error, latestTurn) : capabilities.replay!;
  const special = error ? specialCase(error) : null;
  const problem = error && special === null ? actionableProblem(error) : null;
  const words = special ?? {
    heading: heading(kind, context.surface),
    cause: problem?.cause ?? cause(kind, error, capabilities, context.surface)
  };
  // The preservation claim belongs to the operation that failed: a plan that
  // never arrived created nothing. Other surfaces make no such promise.
  const preserved =
    context.surface === "generation"
      ? ` ${
          context.targetKind === "edit"
            ? m.ai_builder_failure_preserved_edit()
            : m.ai_builder_failure_preserved_create()
        }`
      : "";
  return {
    kind,
    heading: words.heading,
    consequence: `${words.cause}${preserved}`,
    ...actionsFor(kind, special !== null, capabilities, context, problem),
    technical: error ? { code: error.code, requestId: error.request_id } : null
  };
}
