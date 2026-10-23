import { queryOptions } from "@tanstack/react-query";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import type { FlowStep } from "./flows-api";
import { stepMention, valueReference } from "./chat/references";

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

/**
 * "som indata (föregående steg)", "i prompten ({{step_1.output.text}})", ...
 * A value read is written as the chat writes it, so it shows as its pill.
 */
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
    return t("flow_suggestion_read_prompt", { token: valueReference(expression.trim()) });
  }
  return t("flow_suggestion_read_other", { site: read.site });
}

/** "a och b", "a, b och c". */
function joinReads(parts: string[], t: Translate): string {
  if (parts.length <= 1) return parts[0] ?? "";
  const head = parts.slice(0, -1).join(", ");
  return t("flow_suggestion_reads_pair", { first: head, second: parts[parts.length - 1]! });
}

/** A step a suggestion names, as the chat writes it (a pill), or "steg 2" when the draft lacks it. */
function stepText(order: unknown, id: unknown, steps: readonly FlowStep[], t: Translate): string {
  const step = steps.find((candidate) =>
    typeof id === "string" ? candidate.id === id : candidate.step_order === order
  );
  return step?.id
    ? stepMention({ id: step.id, user_description: step.user_description })
    : t("flow_suggestion_producer_order", { order: typeof order === "number" ? order : 0 });
}

function strings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

/**
 * The title and explanation of a suggestion, from its code and params. The
 * step it is shown on, when known, says how its input reads the earlier step.
 * Steps and values are written as the flow chat writes them, so
 * `ReferenceText` shows them as the chat's pills (`referencePlainText` gives
 * the words for an accessible name). A code this version does not know gets
 * a generic text, never the API's English message.
 */
export function suggestionText(
  suggestion: FlowSuggestion,
  t: Translate,
  step?: Pick<FlowStep, "input_source" | "step_order">,
  steps: readonly FlowStep[] = []
): SuggestionText {
  const code: string = suggestion.code;
  const params = suggestion.params;
  const ref = (order: unknown, id: unknown) => stepText(order, id, steps, t);
  const runInput = t("flow_suggestion_run_input");
  switch (code) {
    case "duplicate_read": {
      const producer = ref(params.producer_step_order, params.producer_step_id);
      const contained = params.contained === true;
      const reads = joinReads(
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
    case "broad_all_previous_steps": {
      const count = typeof params.earlier_step_count === "number" ? params.earlier_step_count : 0;
      const derived = records(params.derived)[0];
      return {
        title: t("flow_suggestion_broad_all_previous_steps_title", { count }),
        explanation: derived
          ? t("flow_suggestion_broad_all_previous_steps_explanation_derived", {
              later: ref(derived.step_order, undefined),
              source: ref(derived.from_step_order, undefined)
            })
          : t("flow_suggestion_broad_all_previous_steps_explanation")
      };
    }
    case "whole_structured_read": {
      const producer = ref(params.producer_step_order, params.producer_step_id);
      const fields = strings(params.fields);
      return {
        title: t("flow_suggestion_whole_structured_read_title", { producer, count: fields.length }),
        explanation: t("flow_suggestion_whole_structured_read_explanation", {
          producer,
          fields: joinReads(fields, t)
        })
      };
    }
    case "unread_contract_fields": {
      // The fields as values of the step's result, so each is a pill.
      const order = step?.step_order;
      const fields = strings(params.fields).map((field) =>
        order ? valueReference(`step_${order}.output.structured.${field}`) : field
      );
      return {
        title: t("flow_suggestion_unread_contract_fields_title", {
          count: fields.length,
          fields: joinReads(fields, t)
        }),
        explanation: t("flow_suggestion_unread_contract_fields_explanation", {
          count: fields.length
        })
      };
    }
    case "unread_result":
      return {
        title: t("flow_suggestion_unread_result_title"),
        explanation: t("flow_suggestion_unread_result_explanation")
      };
    case "relay_step": {
      const source =
        params.source_step_order == null
          ? runInput
          : ref(params.source_step_order, params.source_step_id);
      const readers = joinReads(
        records(params.readers).map((reader) => ref(reader.step_order, reader.step_id)),
        t
      );
      return {
        title: t("flow_suggestion_relay_step_title", { source }),
        explanation: t("flow_suggestion_relay_step_explanation", { source, readers })
      };
    }
    case "per_item_prompt_read": {
      const producer = ref(params.producer_step_order, params.producer_step_id);
      return {
        title: t("flow_suggestion_per_item_prompt_read_title", { producer }),
        explanation: t("flow_suggestion_per_item_prompt_read_explanation", { producer })
      };
    }
    case "repeated_long_material": {
      const earlier = ref(params.earlier_step_order, params.earlier_step_id);
      const shared = Array.isArray(params.shared_step_orders)
        ? params.shared_step_orders.map((order) => ref(order, undefined))
        : [];
      const material = joinReads(
        [...(params.shares_run_input === true ? [runInput] : []), ...shared],
        t
      );
      return {
        title: t("flow_suggestion_repeated_long_material_title", { earlier }),
        explanation: t("flow_suggestion_repeated_long_material_explanation", {
          earlier,
          material: material || runInput
        })
      };
    }
    case "unused_form_field": {
      const field = typeof params.field === "string" ? params.field : "";
      return {
        title: t("flow_suggestion_unused_form_field_title", { field }),
        explanation: t("flow_suggestion_unused_form_field_explanation")
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

/** The suggestions about each step, by step id, in the core's order. */
export function suggestionsByStep(
  shown: readonly ShownSuggestion[]
): Map<string, ShownSuggestion[]> {
  const byStep = new Map<string, ShownSuggestion[]>();
  for (const item of shown) {
    if (!item.step.id) continue;
    byStep.set(item.step.id, [...(byStep.get(item.step.id) ?? []), item]);
  }
  return byStep;
}

/** The suggestions about the flow rather than a step (an unused run form field). */
export function flowSuggestions(items: readonly FlowSuggestion[] | undefined): FlowSuggestion[] {
  return (items ?? []).filter((suggestion) => suggestion.steps.length === 0);
}

/** Whether "Åtgärda" can make the suggestion's fix in one step. */
export function isPatchable(suggestion: FlowSuggestion): boolean {
  return suggestion.fix.kind === "patch";
}

/**
 * The request "Fråga assistenten" puts in the flow chat's composer: the
 * suggestion's code and title and its steps as mentions (pills in the
 * composer, ids for the chat's tools), asking for an explanation and a
 * proposed change. It carries nothing from a run.
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
  const mentions = named.flatMap((step) =>
    step.id ? [stepMention({ id: step.id, user_description: step.user_description })] : []
  );
  const title = suggestionText(suggestion, t, named[0], steps).title;
  // A suggestion about the run form names no step.
  if (mentions.length === 0) {
    return t("flow_suggestion_ask_request_flow", { title, code: suggestion.code });
  }
  return t("flow_suggestion_ask_request", {
    title,
    code: suggestion.code,
    // Pills in the composer, side by side; a pill brings its own space.
    steps: mentions.join(" ")
  });
}
