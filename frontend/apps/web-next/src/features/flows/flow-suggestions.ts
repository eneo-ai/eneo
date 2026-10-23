import { queryOptions } from "@tanstack/react-query";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import type { FlowStep } from "./flows-api";
import { stepName } from "./flow-steps";

/**
 * The core's suggestions for a draft (`GET /flows/{id}/suggestions/`): where
 * the flow moves the same data twice. Display only here; the text a person
 * reads is rendered from each suggestion's `code` and `params`, never from
 * its English `message` (that one is for the API and the chat model).
 */

export type FlowSuggestion = Schema<"FlowSuggestionPublic">;
export type FlowSuggestions = Schema<"FlowSuggestionsPublic">;
export type FlowSuggestionCode = Schema<"FlowSuggestionCode">;

type Translate = (key: string, values?: Record<string, string | number>) => string;

export const flowSuggestionKeys = {
  /** Keyed by the draft revision, so a save or a chat tool call refetches. */
  list: (flowId: string, revision: number) => ["flows", flowId, "suggestions", revision] as const
};

export function flowSuggestionsQueryOptions(flowId: string, revision: number) {
  return queryOptions({
    queryKey: flowSuggestionKeys.list(flowId, revision),
    queryFn: (): Promise<FlowSuggestions> =>
      unwrap(
        browserApi.GET("/api/v1/flows/{id}/suggestions/", { params: { path: { id: flowId } } })
      )
  });
}

export type SuggestionText = {
  /** One line: what was found. */
  title: string;
  /** A few sentences: why it matters, shown behind a disclosure. */
  explanation: string;
};

/** One read of `duplicate_read`'s `params.reads`, as the core sites it. */
export type DuplicateRead = { channel: string; site: string; selector: string[] };

const PROMPT_SITE_PREFIX = "assistant_prompt:";
const SOURCE_REF_SITE = /^input_bindings\.source_refs\[(\d+)\]$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function duplicateReads(params: Record<string, unknown>): DuplicateRead[] {
  if (!Array.isArray(params.reads)) return [];
  return params.reads.flatMap((read): DuplicateRead[] => {
    if (!isRecord(read) || typeof read.channel !== "string" || typeof read.site !== "string") {
      return [];
    }
    const selector = Array.isArray(read.selector)
      ? read.selector.filter((part): part is string => typeof part === "string")
      : [];
    return [{ channel: read.channel, site: read.site, selector }];
  });
}

/** "som indata (föregående steg)", "i prompten ({{ step_1.output.text }})", ... */
export function readText(
  read: DuplicateRead,
  t: Translate,
  step?: Pick<FlowStep, "input_source">
): string {
  if (read.site === "input_source") {
    if (step?.input_source === "all_previous_steps") return t("flow_suggestion_read_input_all");
    if (step?.input_source === "previous_step") return t("flow_suggestion_read_input_previous");
    return t("flow_suggestion_read_input");
  }
  if (read.site === "input_bindings.question") return t("flow_suggestion_read_question");
  const sourceRef = SOURCE_REF_SITE.exec(read.site);
  if (sourceRef) {
    return t("flow_suggestion_read_source_ref", { index: Number(sourceRef[1]) + 1 });
  }
  if (read.site.startsWith(PROMPT_SITE_PREFIX)) {
    const expression = read.site.slice(PROMPT_SITE_PREFIX.length);
    return t("flow_suggestion_read_prompt", { token: `{{ ${expression} }}` });
  }
  return t("flow_suggestion_read_other", { site: read.site });
}

/** "a och b", "a, b och c". */
function joinParts(parts: string[], t: Translate): string {
  if (parts.length <= 1) return parts[0] ?? "";
  const head = parts.slice(0, -1).join(", ");
  return t("flow_suggestion_reads_pair", { first: head, second: parts[parts.length - 1]! });
}

/**
 * The title and explanation of a suggestion, from its code and params. The
 * step it is shown on, when known, says how its input reads the earlier step.
 */
export function suggestionText(
  suggestion: FlowSuggestion,
  t: Translate,
  step?: Pick<FlowStep, "input_source">
): SuggestionText {
  const code: string = suggestion.code;
  switch (code) {
    case "duplicate_read": {
      const params = suggestion.params;
      const producer =
        typeof params.producer_step_order === "number" ? params.producer_step_order : 0;
      const contained = params.contained === true;
      const reads = joinParts(
        duplicateReads(params).map((read) => readText(read, t, step)),
        t
      );
      return contained
        ? {
            title: t("flow_suggestion_duplicate_read_title_contained", { producer }),
            explanation: t("flow_suggestion_duplicate_read_explanation_contained", { reads })
          }
        : {
            title: t("flow_suggestion_duplicate_read_title", { producer }),
            explanation: t("flow_suggestion_duplicate_read_explanation", { reads })
          };
    }
    default:
      return {
        title: t("flow_suggestion_unknown_title"),
        explanation: t("flow_suggestion_unknown_explanation")
      };
  }
}

/** A suggestion shown on the step it is about: the first of its steps. */
export type ShownSuggestion = { suggestion: FlowSuggestion; step: FlowStep };

/**
 * The suggestions the draft can show, each with the step it is about. One
 * whose step the draft no longer has (the answer is from a revision before a
 * removal) cannot be shown on it and is left out.
 */
export function shownSuggestions(
  items: readonly FlowSuggestion[] | undefined,
  steps: readonly FlowStep[]
): ShownSuggestion[] {
  return (items ?? []).flatMap((suggestion): ShownSuggestion[] => {
    const step = steps.find((candidate) => candidate.id === suggestion.steps[0]);
    return step ? [{ suggestion, step }] : [];
  });
}

/** How many suggestions are about each step, by step id. */
export function suggestionCounts(shown: readonly ShownSuggestion[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const { step } of shown) {
    if (step.id) counts.set(step.id, (counts.get(step.id) ?? 0) + 1);
  }
  return counts;
}

/**
 * The request "Fråga assistenten" puts in the flow chat's composer: the
 * suggestion's code and title and its steps by order and name, asking for an
 * explanation and a proposed change. It carries nothing from a run.
 */
export function suggestionRequest(
  suggestion: FlowSuggestion,
  steps: readonly FlowStep[],
  t: Translate
): string {
  const named = suggestion.steps.flatMap((id): FlowStep[] => {
    const step = steps.find((candidate) => candidate.id === id);
    return step ? [step] : [];
  });
  const stepTexts = named.map((step) => {
    const name = stepName(step);
    return name
      ? t("flow_suggestion_ask_step", { order: step.step_order, name })
      : t("flow_suggestion_ask_step_unnamed", { order: step.step_order });
  });
  return t("flow_suggestion_ask_request", {
    title: suggestionText(suggestion, t, named[0]).title,
    code: suggestion.code,
    steps: joinParts(stepTexts, t)
  });
}
