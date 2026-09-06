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

/** The typed reference one suggestion travels as: kind and steps, canonical
 *  the same way the server canonicalises them, so a retry of the same
 *  investigation is the same request. */
export function suggestionFocus(suggestion: AIBuilderFlowReviewSuggestion): {
  suggestion_kind: AIBuilderFlowReviewSuggestion["kind"];
  step_orders: number[];
} {
  return {
    suggestion_kind: suggestion.kind,
    step_orders: [...new Set(suggestion.step_orders)].sort((a, b) => a - b)
  };
}

/** What the turn will say, shown before it is sent. The server builds the
 *  authoritative message from the same typed reference and ignores what the
 *  client sends, so this preview can differ from it in wording order and
 *  language (eneo-y9m). Several suggestions are one turn, so they are one
 *  sentence. */
export function investigationMessage(suggestions: AIBuilderFlowReviewSuggestion[]): string {
  const named = suggestions.map((suggestion) =>
    m.ai_builder_review_suggestion_investigate_item({
      kind: suggestionKindLabel(suggestion.kind).toLocaleLowerCase(),
      steps: suggestionStepsLabel(suggestion.step_orders).toLocaleLowerCase()
    })
  );
  if (named.length === 1) {
    return m.ai_builder_review_suggestion_investigate_message({
      kind: suggestionKindLabel(suggestions[0].kind).toLocaleLowerCase(),
      steps: suggestionStepsLabel(suggestions[0].step_orders).toLocaleLowerCase()
    });
  }
  return m.ai_builder_review_suggestions_investigate_message({ items: named.join("; ") });
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
