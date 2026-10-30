import {
  keepPreviousData,
  queryOptions,
  type QueryClient,
  type QueryKey
} from "@tanstack/react-query";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { reasoningEffortLabel } from "@/features/chat/reasoning-effort";
import type { FlowStep } from "./flows-api";
import { stepMention, valueReference } from "./chat/references";

/**
 * The core's suggestions for a draft (`GET /flows/{id}/suggestions/`): where
 * the flow moves the same data twice, and what the runs measured. The text a
 * person reads is rendered from each suggestion's `code` and `params`, never
 * from its English `message` (that one is for the API and the chat model).
 */

export type FlowSuggestion = Schema<"FlowSuggestionPublic">;
export type FlowSuggestions = Schema<"FlowSuggestionsPublic">;
export type FlowSuggestionCode = Schema<"FlowSuggestionCode">;
export type FlowSuggestionImpact = Schema<"FlowSuggestionImpactPublic">;
export type FlowSuggestionRuns = Schema<"FlowSuggestionRunsPublic">;
/** Who dismissed a suggestion of the flow, and when. */
export type FlowSuggestionDismissed = Schema<"FlowSuggestionDismissedPublic">;

type Translate = (key: string, values?: Record<string, string | number>) => string;

export type FlowSuggestionsApplied = Schema<"FlowSuggestionsAppliedPublic">;

/** How many of the latest runs "Räkna med de senaste körningarna" measures. */
export const MEASURED_RUNS = 10;

export const flowSuggestionKeys = {
  /** Every revision's suggestions of a flow, plain and measured. */
  all: (flowId: string) => ["flows", flowId, "suggestions"] as const,
  /**
   * Keyed by the draft revision, so a save or a chat tool call refetches,
   * and by the runs measured (0 for the definition alone), so a plain and a
   * measured answer never mix.
   */
  list: (flowId: string, revision: number, runs = 0) =>
    ["flows", flowId, "suggestions", revision, runs] as const
};

/** The runs a suggestions query key measures; 0 for the definition alone. */
function keyRuns(queryKey: QueryKey): number {
  const runs = queryKey[4];
  return typeof runs === "number" ? runs : 0;
}

/**
 * Reads the flow's plain answers again. Measured answers are left as they
 * are: each measured read writes an audit entry on the flow, so one is made
 * only when the person asks or the draft revision changes.
 */
export function invalidateDefinitionSuggestions(queryClient: QueryClient, flowId: string) {
  return queryClient.invalidateQueries({
    queryKey: flowSuggestionKeys.all(flowId),
    predicate: (query) => keyRuns(query.queryKey) === 0
  });
}

/**
 * Drops the flow's measured answers: before a press of "Räkna med de
 * senaste körningarna", so the press reads anew, and when the page closes.
 */
export function forgetMeasuredSuggestions(queryClient: QueryClient, flowId: string) {
  queryClient.removeQueries({
    queryKey: flowSuggestionKeys.all(flowId),
    predicate: (query) => keyRuns(query.queryKey) > 0
  });
}

/**
 * Reads the suggestions on screen again after a change that keeps the draft
 * revision (a dismissal, or taking one back): the plain answer on screen is
 * read again and the others are marked stale, and while the page measures,
 * its measured answer is read once more (one audit entry). No other measured
 * answer is read.
 */
export async function refetchSuggestionsOnScreen(
  queryClient: QueryClient,
  flowId: string,
  revision: number,
  runs: number
): Promise<void> {
  await Promise.all([
    invalidateDefinitionSuggestions(queryClient, flowId),
    runs > 0
      ? queryClient.refetchQueries({
          queryKey: flowSuggestionKeys.list(flowId, revision, runs),
          exact: true
        })
      : null
  ]);
}

/** The suggestion is gone from the draft (a change since it was read). */
export const SUGGESTION_STALE = "flow_suggestion_stale";

/**
 * Dismisses a suggestion for the flow, for every editor of it (`POST
 * .../dismissal/` with the suggestion's code). Retrying answers with the
 * dismissal as first made. The draft revision stays as it is.
 */
export function dismissFlowSuggestion(
  flowId: string,
  suggestion: Pick<FlowSuggestion, "fingerprint" | "code">
): Promise<Schema<"FlowSuggestionDismissalPublic">> {
  return unwrap(
    browserApi.POST("/api/v1/flows/{id}/suggestions/{fingerprint}/dismissal/", {
      params: { path: { id: flowId, fingerprint: suggestion.fingerprint } },
      body: { code: suggestion.code }
    })
  );
}

/**
 * Takes a dismissal back (`DELETE .../dismissal/`), so the suggestion is
 * listed again while the draft has it. A dismissal that is already gone
 * (someone else took it back) leaves the flow as asked: that is no refusal.
 */
export async function restoreFlowSuggestion(flowId: string, fingerprint: string): Promise<void> {
  try {
    await unwrap(
      browserApi.DELETE("/api/v1/flows/{id}/suggestions/{fingerprint}/dismissal/", {
        params: { path: { id: flowId, fingerprint } }
      })
    );
  } catch (error) {
    if (error instanceof EneoApiError && error.status === 404) return;
    throw error;
  }
}

/**
 * Makes the fixes of the suggestions named by fingerprint on the draft at
 * `expectedRevision`, all of them or none (`POST .../suggestions/apply/`):
 * the core applies them in its own order and skips one an earlier fix made
 * unnecessary.
 */
export function applyFlowSuggestions(
  flowId: string,
  expectedRevision: number,
  fingerprints: string[]
): Promise<FlowSuggestionsApplied> {
  return unwrap(
    browserApi.POST("/api/v1/flows/{id}/suggestions/apply/", {
      params: { path: { id: flowId } },
      body: { expected_revision: expectedRevision, fingerprints }
    })
  );
}

/**
 * The draft revision's suggestions, judged from the definition alone or,
 * with `runs`, measured over that many of the latest runs. A measured read
 * writes an audit entry on the flow, so it is made once per revision while
 * the page asks for it: never again on a remount, a window focus, a
 * reconnect or a retry, and it stays in the cache for the visit (the page
 * forgets it when it closes).
 *
 * The answer lists the dismissed suggestions too, marked (`dismissed`): the
 * page leaves them out of its lists and counts (`suggestionsOnPage`) and
 * shows them under "Visa ignorerade". One answer per revision serves both,
 * so showing them never reads again, and never measures again.
 */
export function flowSuggestionsQueryOptions(flowId: string, revision: number, runs = 0) {
  const measured = runs > 0;
  return queryOptions({
    queryKey: flowSuggestionKeys.list(flowId, revision, runs),
    queryFn: (): Promise<FlowSuggestions> =>
      unwrap(
        browserApi.GET("/api/v1/flows/{id}/suggestions/", {
          params: {
            path: { id: flowId },
            query: measured ? { runs, include_dismissed: true } : { include_dismissed: true }
          }
        })
      ),
    // While a new revision's suggestions load, the last ones stay on the
    // cards: nothing collapses or jumps, and a fixed one leaves when the
    // answer comes.
    placeholderData: keepPreviousData,
    ...(measured
      ? {
          staleTime: Infinity,
          gcTime: Infinity,
          refetchOnMount: false,
          refetchOnWindowFocus: false,
          refetchOnReconnect: false,
          retry: false
        }
      : {})
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
  read: Pick<DuplicateRead, "site">,
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

function numberOr(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

/** "I 4 av de 5 senaste körningarna": the runs a forwarding finding held in, of those that measured it. */
function heldRuns(params: Record<string, unknown>): { runs: number; held: number } {
  const runs = numberOr(params.run_count, 0);
  return { runs, held: numberOr(params.held_runs, runs) };
}

/**
 * `context_headroom`: how close the step's model came to the most text it
 * takes in, how often the step failed on too much material, and how much
 * of it the step got twice. The share and the failures are each said only
 * when the runs measured them.
 */
function headroomText(params: Record<string, unknown>, t: Translate): SuggestionText {
  const failures = numberOr(params.inline_cap_failures, 0);
  const share = typeof params.limit_share === "number" ? params.limit_share : null;
  const duplicated = typeof params.duplicated_share === "number" ? params.duplicated_share : null;
  const sentences = [
    share !== null ? t("flow_suggestion_context_headroom_share", { share }) : null,
    failures > 0 ? t("flow_suggestion_context_headroom_failures", { count: failures }) : null,
    duplicated !== null
      ? t("flow_suggestion_context_headroom_duplicated", { share: duplicated })
      : null,
    t("flow_suggestion_context_headroom_advice")
  ];
  return {
    title:
      failures > 0
        ? t("flow_suggestion_context_headroom_title_failed")
        : t("flow_suggestion_context_headroom_title"),
    explanation: sentences.filter((sentence) => sentence !== null).join(" ")
  };
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
    // Measured from recent runs, only with `runs`.
    case "identical_inputs": {
      const ids = strings(params.producer_step_ids);
      const orders = Array.isArray(params.producer_step_orders) ? params.producer_step_orders : [];
      const reads = joinReads(
        strings(params.sites).map((site) => readText({ site }, t, step)),
        t
      );
      const runs = numberOr(params.step_runs, 0);
      return {
        title: t("flow_suggestion_identical_inputs_title", {
          first: ref(orders[0], ids[0]),
          second: ref(orders[1], ids[1])
        }),
        explanation: t("flow_suggestion_identical_inputs_explanation", {
          runs,
          observed: numberOr(params.observed_runs, runs),
          reads
        })
      };
    }
    case "context_headroom":
      return headroomText(params, t);
    case "format_fallback": {
      const runs = numberOr(params.step_runs, 0);
      return {
        title: t("flow_suggestion_format_fallback_title"),
        explanation: t("flow_suggestion_format_fallback_explanation", {
          runs,
          fallbacks: numberOr(params.fallback_runs, runs)
        })
      };
    }
    // Measured from what the runs forwarded, only with `runs`.
    case "model_relay": {
      const producer = ref(params.producer_step_order, params.producer_step_id);
      const readers = joinReads(
        records(params.readers).map((reader) => ref(reader.step_order, reader.step_id)),
        t
      );
      return {
        title: t("flow_suggestion_model_relay_title", { producer }),
        explanation: t("flow_suggestion_model_relay_explanation", {
          ...heldRuns(params),
          share: numberOr(params.copied_share, 0),
          producer,
          readers
        })
      };
    }
    case "overlapping_inputs": {
      const inputs = records(params.inputs);
      const reads = joinReads(
        inputs.map((input) =>
          t("flow_suggestion_overlapping_inputs_read", {
            step: ref(input.step_order, input.step_id),
            reads: joinReads(
              strings(input.sites).map((site) => readText({ site }, t, step)),
              t
            )
          })
        ),
        t
      );
      return {
        title: t("flow_suggestion_overlapping_inputs_title", {
          first: ref(inputs[0]?.step_order, inputs[0]?.step_id),
          second: ref(inputs[1]?.step_order, inputs[1]?.step_id)
        }),
        explanation: t("flow_suggestion_overlapping_inputs_explanation", {
          ...heldRuns(params),
          share: numberOr(params.shared_share, 0),
          reads
        })
      };
    }
    case "deterministic_candidate":
      return {
        title: t("flow_suggestion_deterministic_candidate_title"),
        explanation: t("flow_suggestion_deterministic_candidate_explanation", {
          ...heldRuns(params),
          share: numberOr(params.output_verbatim_ratio, 0),
          kind: t("flow_step_editor_kind_compose")
        })
      };
    // Measured against what the model catalogue knows, only with `runs`.
    case "oversized_reasoning": {
      const share = numberOr(params.limit_share, 0);
      return {
        title: t("flow_suggestion_oversized_reasoning_title", {
          effort: reasoningEffortLabel(
            typeof params.reasoning_effort === "string" ? params.reasoning_effort : "high",
            t
          )
        }),
        explanation: t("flow_suggestion_oversized_reasoning_explanation", {
          ...heldRuns(params),
          share,
          // A share that rounds to 0 % is said as "under 1 %".
          small: share < 0.005 ? "yes" : "no",
          output: numberOr(params.peak_output_tokens, 0)
        })
      };
    }
    default:
      return {
        title: t("flow_suggestion_unknown_title"),
        explanation: t("flow_suggestion_unknown_explanation")
      };
  }
}

/** A count as a person reads it: two significant digits from 100 up (1 840 is about 1 800). */
function readableCount(value: number): number {
  const rounded = Math.round(value);
  return rounded < 100 ? rounded : Number(rounded.toPrecision(2));
}

/**
 * What a measured suggestion's numbers say, as one line under its title:
 * about how many tokens per run it costs, over how many runs of which
 * version, and whether the step has changed since. A finding without a
 * token cost of its own says its run count only. Null for an impact judged
 * from the definition.
 */
export function measuredImpactText(impact: FlowSuggestionImpact, t: Translate): string | null {
  if (impact.basis !== "runs" || impact.run_count == null) return null;
  const count = impact.run_count;
  const measured =
    impact.tokens_per_run == null
      ? t("flow_suggestion_measured_runs", { count })
      : impact.version == null
        ? t("flow_suggestion_measured_tokens", {
            tokens: readableCount(impact.tokens_per_run),
            count
          })
        : t("flow_suggestion_measured_tokens_version", {
            tokens: readableCount(impact.tokens_per_run),
            count,
            version: impact.version
          });
  return impact.step_changed_since === true
    ? `${measured} ${t("flow_suggestion_measured_step_changed")}`
    : measured;
}

/**
 * The measured line of a suggestion's row: its numbers
 * (`measuredImpactText`) and, for a duplicate whose two reads the runs found
 * sharing text (`params.measured_overlaps`), how much they shared, the
 * largest share only. Null when nothing was measured.
 */
export function measuredSuggestionText(suggestion: FlowSuggestion, t: Translate): string | null {
  const overlaps = records(suggestion.params.measured_overlaps);
  const overlap =
    overlaps.length > 0
      ? overlaps.reduce((largest, item) =>
          numberOr(item.shared_share, 0) > numberOr(largest.shared_share, 0) ? item : largest
        )
      : null;
  const lines = [
    measuredImpactText(suggestion.impact, t),
    overlap
      ? t("flow_suggestion_measured_overlap", {
          ...heldRuns(overlap),
          share: numberOr(overlap.shared_share, 0)
        })
      : null
  ];
  const text = lines.filter((line) => line !== null).join(" ");
  return text || null;
}

/**
 * What a measured answer is based on: "Baserat på 8 körningar.", that runs
 * the person may not see were left out, or that there are no finished runs
 * to count yet. `found` is how many suggestions it gave; with none it says
 * so first.
 */
export function measuredBasisText(runs: FlowSuggestionRuns, found: number, t: Translate): string {
  const sentences = [
    found === 0 ? t("flow_suggestions_runs_nothing_found") : null,
    runs.counted > 0
      ? t("flow_suggestions_runs_counted", { count: runs.counted })
      : runs.left_out === 0
        ? t("flow_suggestions_runs_none")
        : null,
    runs.left_out > 0 ? t("flow_suggestions_runs_left_out", { count: runs.left_out }) : null
  ];
  return sentences.filter((sentence) => sentence !== null).join(" ");
}

const LEVEL_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2 };

/**
 * The order suggestions are listed in, as the core orders them: a known
 * cost in tokens per run first, the highest first; then by level (high,
 * medium, low); then as the core listed them.
 */
export function inSuggestionOrder<T extends { suggestion: FlowSuggestion }>(
  items: readonly T[]
): T[] {
  const tokens = (item: T) => item.suggestion.impact.tokens_per_run ?? null;
  return items
    .map((item, index) => ({ item, index }))
    .sort((left, right) => {
      const [a, b] = [tokens(left.item), tokens(right.item)];
      const byTokens =
        a === null || b === null ? (a === null ? 1 : 0) - (b === null ? 1 : 0) : b - a;
      return (
        byTokens ||
        (LEVEL_ORDER[left.item.suggestion.impact.level] ?? 3) -
          (LEVEL_ORDER[right.item.suggestion.impact.level] ?? 3) ||
        left.index - right.index
      );
    })
    .map(({ item }) => item);
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

/** A dismissed suggestion, with the step it is about (null for one about the run form). */
export type DismissedSuggestion = { suggestion: FlowSuggestion; step: FlowStep | null };

/** What the page shows of an answer, the dismissed suggestions apart. */
export type SuggestionsOnPage = {
  /** On the step cards; none of them dismissed. */
  shown: ShownSuggestion[];
  /** About the run form; none of them dismissed. */
  form: FlowSuggestion[];
  /** Dismissed by an editor of the flow, for "Visa ignorerade", in the core's order. */
  dismissed: DismissedSuggestion[];
};

/**
 * Splits an answer into what the step list shows: the suggestions on the
 * step cards and about the run form, and apart from them the dismissed ones.
 * A dismissed suggestion never counts among the others. One whose step the
 * draft no longer has is left out of all three.
 */
export function suggestionsOnPage(
  items: readonly FlowSuggestion[] | undefined,
  steps: readonly FlowStep[]
): SuggestionsOnPage {
  const active = (items ?? []).filter((suggestion) => !suggestion.dismissed);
  const dismissed = (items ?? []).filter((suggestion) => suggestion.dismissed);
  return {
    shown: shownSuggestions(active, steps),
    form: flowSuggestions(active),
    dismissed: dismissed.flatMap((suggestion): DismissedSuggestion[] => {
      if (suggestion.steps.length === 0) return [{ suggestion, step: null }];
      const step = steps.find((candidate) => candidate.id === suggestion.steps[0]);
      return step ? [{ suggestion, step }] : [];
    })
  };
}

/** How many suggestions the draft shows, the dismissed ones not counted. */
export function suggestionCount(page: SuggestionsOnPage): number {
  return page.shown.length + page.form.length;
}

/** "Ignorerat av dig": who dismissed a suggestion, as the signed-in person reads it. */
export function dismissedByText(
  dismissed: Pick<FlowSuggestionDismissed, "dismissed_by">,
  userId: string,
  t: Translate
): string {
  if (dismissed.dismissed_by === null) return t("flow_suggestion_dismissed_by_removed");
  // The API names no other person, and a piece of an id names nobody.
  return dismissed.dismissed_by === userId
    ? t("flow_suggestion_dismissed_by_you")
    : t("flow_suggestion_dismissed_by_other");
}

/** Whether "Åtgärda" can make the suggestion's fix in one step: a patch, and not dismissed. */
export function isPatchable(suggestion: FlowSuggestion): boolean {
  return suggestion.fix.kind === "patch" && !suggestion.dismissed;
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
