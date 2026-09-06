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

/** "2 och 3", "1, 2 och 3" (or "and"): the same reading the server's message uses. */
function formatSteps(stepOrders: number[]): string {
  const steps = [...new Set(stepOrders)].sort((a, b) => a - b).map(String);
  if (steps.length <= 1) return steps.join("");
  const conjunction = m.ai_builder_review_suggestion_steps_join();
  return `${steps.slice(0, -1).join(", ")} ${conjunction} ${steps[steps.length - 1]}`;
}

export type SuggestionFocus = {
  suggestion_kind: AIBuilderFlowReviewSuggestion["kind"];
  step_orders: number[];
};

/** The selected suggestions as the server canonicalises them: one focus per
 *  distinct kind and step set, ordered by kind then steps, so the payload,
 *  the fingerprint and the sentence agree however the cards were picked. */
export function canonicalFoci(suggestions: AIBuilderFlowReviewSuggestion[]): SuggestionFocus[] {
  const byKey = new Map<string, SuggestionFocus>();
  for (const suggestion of suggestions) {
    const focus = suggestionFocus(suggestion);
    byKey.set(`${focus.suggestion_kind}|${focus.step_orders.join(",")}`, focus);
  }
  return [...byKey.values()].sort((a, b) => {
    if (a.suggestion_kind !== b.suggestion_kind) {
      return a.suggestion_kind < b.suggestion_kind ? -1 : 1;
    }
    const length = Math.min(a.step_orders.length, b.step_orders.length);
    for (let i = 0; i < length; i += 1) {
      if (a.step_orders[i] !== b.step_orders[i]) return a.step_orders[i] - b.step_orders[i];
    }
    return a.step_orders.length - b.step_orders.length;
  });
}

function messageKindLabel(kind: AIBuilderFlowReviewSuggestion["kind"]): string {
  switch (kind) {
    case "duplicated_work":
      return m.ai_builder_review_suggestion_message_kind_duplicated_work();
    case "instruction_outcome_drift":
      return m.ai_builder_review_suggestion_message_kind_instruction_outcome_drift();
    case "step_not_useful":
      return m.ai_builder_review_suggestion_message_kind_step_not_useful();
    case "missing_check":
      return m.ai_builder_review_suggestion_message_kind_missing_check();
  }
}

/** The typed reference one suggestion travels as: kind and steps, canonical
 *  the same way the server canonicalises them, so a retry of the same
 *  investigation is the same request. */
export function suggestionFocus(suggestion: AIBuilderFlowReviewSuggestion): SuggestionFocus {
  return {
    suggestion_kind: suggestion.kind,
    step_orders: [...new Set(suggestion.step_orders)].sort((a, b) => a - b)
  };
}

/** The fixed handoff text. The server writes the same text from the typed
 *  reference and ignores what the client sends, so this only shows the user
 *  what the turn will say. */
export function investigationMessage(foci: SuggestionFocus[]): string {
  const items = foci.map((focus) =>
    m.ai_builder_review_suggestion_investigate_item({
      kind: messageKindLabel(focus.suggestion_kind),
      steps: m.ai_builder_review_suggestion_message_step({ steps: formatSteps(focus.step_orders) })
    })
  );
  if (items.length === 1) {
    return m.ai_builder_review_suggestion_investigate_message({ items: items[0] });
  }
  // Several suggestions become one turn and one sentence, as on the server.
  return m.ai_builder_review_suggestion_investigate_message_many({ items: items.join("; ") });
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
