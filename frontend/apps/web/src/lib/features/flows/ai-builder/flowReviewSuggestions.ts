import { m } from "$lib/paraglide/messages";
import type {
  AIBuilderError,
  AIBuilderFlowReviewSuggestion,
  AIBuilderFlowReviewSuggestions
} from "./protocol";

type SuggestionSource = AIBuilderFlowReviewSuggestion["sources"][number];

export function suggestionKindLabel(kind: AIBuilderFlowReviewSuggestion["kind"]): string {
  switch (kind) {
    case "duplicated_work":
      return m.ai_builder_review_suggestion_kind_duplicated_work();
    case "instruction_outcome_drift":
      return m.ai_builder_review_suggestion_kind_instruction_outcome_drift();
    case "step_not_useful":
      return m.ai_builder_review_suggestion_kind_step_not_useful();
    case "missing_check":
      return m.ai_builder_review_suggestion_kind_missing_check();
  }
}

export function suggestionStepsLabel(stepOrders: number[]): string {
  return m.ai_builder_review_suggestion_steps({ steps: formatSteps(stepOrders) });
}

/** "2 och 3", "1, 2 och 3": the same reading the server's message uses. */
function formatSteps(stepOrders: number[]): string {
  const steps = [...new Set(stepOrders)].sort((a, b) => a - b).map(String);
  if (steps.length <= 1) return steps.join("");
  return `${steps.slice(0, -1).join(", ")} och ${steps[steps.length - 1]}`;
}

/** The fixed handoff text. The server writes the same text from the typed
 *  reference and ignores what the client sends, so this only shows the user
 *  what the turn will say. */
export function investigationMessage(suggestion: AIBuilderFlowReviewSuggestion): string {
  return m.ai_builder_review_suggestion_investigate_message({
    kind: suggestionKindLabel(suggestion.kind).toLocaleLowerCase(),
    steps: suggestionStepsLabel(suggestion.step_orders).toLocaleLowerCase()
  });
}

export function suggestionSourceLabel(
  source: SuggestionSource,
  sampleRunIds: AIBuilderFlowReviewSuggestions["sample"]["run_ids"]
): string {
  const runIndex = sampleRunIds.indexOf(source.run_id);
  const field =
    source.field === "prompt"
      ? m.ai_builder_review_suggestion_field_prompt()
      : source.field === "input"
        ? m.ai_builder_review_suggestion_field_input()
        : m.ai_builder_review_suggestion_field_output();
  return m.ai_builder_review_suggestion_source({
    run: String(runIndex >= 0 ? runIndex + 1 : "?"),
    step: String(source.step_order),
    field
  });
}

export function suggestionsFailureCopy(error: AIBuilderError): {
  title: string;
  body: string | null;
  retry: boolean;
} {
  switch (error.code) {
    case "review_suggestions_invalid_output":
      return {
        title: m.ai_builder_review_suggestions_failed(),
        body: m.ai_builder_review_suggestions_invalid_output(),
        retry: true
      };
    case "review_sample_timeout":
      return {
        title: m.ai_builder_review_suggestions_failed(),
        body: m.ai_builder_review_suggestions_timeout(),
        retry: true
      };
    case "planner_model_below_evidence_level":
      return {
        title: m.ai_builder_review_suggestions_failed(),
        body: m.ai_builder_review_suggestions_below_level(),
        retry: false
      };
    case "no_planner_model_available":
      return {
        title: m.ai_builder_review_suggestions_failed(),
        body: m.ai_builder_review_suggestions_no_model(),
        retry: false
      };
    default:
      return { title: m.ai_builder_review_suggestions_failed(), body: error.message, retry: true };
  }
}
