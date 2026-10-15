import type { FlowStep } from "@eneo/eneo-js";
import { isJsonObject, type JsonObject } from "../jsonObject";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type AdvancedJsonField =
  "input_contract" | "output_contract" | "input_config" | "output_config";

export const ADVANCED_JSON_FIELDS: AdvancedJsonField[] = [
  "input_contract",
  "output_contract",
  "input_config",
  "output_config"
];

/** Why a draft cannot be stored: it is not JSON, or it is JSON other than an object. */
export type AdvancedJsonProblem = "syntax" | "not_object";

export type AdvancedJsonDrafts = Record<AdvancedJsonField, string>;
export type AdvancedJsonErrors = Partial<Record<AdvancedJsonField, AdvancedJsonProblem>>;

// A refused draft carries no value, so nothing can be stored from one.
type AdvancedJsonReading =
  { parsed: JsonObject | null; problem: null } | { problem: AdvancedJsonProblem };

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

export function formatAdvancedJson(value: unknown): string {
  return value == null ? "" : JSON.stringify(value, null, 2);
}

/** True when a draft holds more than nothing or an empty object. */
export function hasCustomJson(value: string): boolean {
  const trimmed = value.trim();
  return trimmed.length > 0 && trimmed !== "{}";
}

/**
 * True when the step's output mode and type let the author set an output
 * contract; the publish check (_validate_output_contract_compatibility)
 * refuses one on a text answer, a fixed Word template, a verbatim document
 * and a speaker mapping, whose contract is fixed.
 */
export function acceptsOutputContract(step: Pick<FlowStep, "output_mode" | "output_type">) {
  return (
    step.output_type !== "text" &&
    step.output_mode !== "template_fill" &&
    step.output_mode !== "render_verbatim" &&
    step.output_mode !== "speaker_mapping"
  );
}

export function getStepKeyForAdvancedJson(step: FlowStep | null): string | null {
  if (!step) return null;
  return `${step.id ?? "new"}:${step.step_order}`;
}

export function getStepAdvancedJsonValue(step: FlowStep, field: AdvancedJsonField): unknown {
  switch (field) {
    case "input_contract":
      return step.input_contract;
    case "output_contract":
      return step.output_contract;
    case "input_config":
      return step.input_config;
    case "output_config":
      return step.output_config;
    default:
      return null;
  }
}

export function getVisibleAdvancedJsonFields(step: FlowStep | null): Set<AdvancedJsonField> {
  if (!step || step.output_mode === "template_fill") {
    return new Set<AdvancedJsonField>();
  }
  const visible = new Set<AdvancedJsonField>(["input_contract", "output_contract"]);
  if (step.input_source === "http_get") {
    visible.add("input_config");
  }
  if (step?.output_mode === "http_post") {
    visible.add("output_config");
  }
  return visible;
}

// ---------------------------------------------------------------------------
// Reducer-style state functions
//
// These return new state objects so callers can update draft state by assignment.
// ---------------------------------------------------------------------------

export function syncDraftsFromStep(step: FlowStep | null): {
  drafts: AdvancedJsonDrafts;
  errors: AdvancedJsonErrors;
} {
  return {
    drafts: {
      input_contract: formatAdvancedJson(step?.input_contract ?? null),
      output_contract: formatAdvancedJson(step?.output_contract ?? null),
      input_config: formatAdvancedJson(step?.input_config ?? null),
      output_config: formatAdvancedJson(step?.output_config ?? null)
    },
    errors: {}
  };
}

export function syncDraftsFromStepValues(
  currentDrafts: AdvancedJsonDrafts,
  currentErrors: AdvancedJsonErrors,
  step: FlowStep
): AdvancedJsonDrafts | null {
  const nextDrafts = { ...currentDrafts };
  let changed = false;
  for (const field of ADVANCED_JSON_FIELDS) {
    if (currentErrors[field]) continue;
    const nextValue = formatAdvancedJson(getStepAdvancedJsonValue(step, field));
    if (nextDrafts[field] !== nextValue) {
      nextDrafts[field] = nextValue;
      changed = true;
    }
  }
  return changed ? nextDrafts : null;
}

export function clearHiddenFieldErrors(
  currentErrors: AdvancedJsonErrors,
  step: FlowStep | null
): AdvancedJsonErrors | null {
  const visibleFields = getVisibleAdvancedJsonFields(step);
  const nextErrors = { ...currentErrors };
  let changed = false;
  for (const field of ADVANCED_JSON_FIELDS) {
    if (!visibleFields.has(field) && nextErrors[field]) {
      delete nextErrors[field];
      changed = true;
    }
  }
  return changed ? nextErrors : null;
}

function readAdvancedJsonDraft(rawValue: string): AdvancedJsonReading {
  if (rawValue.trim().length === 0) {
    return { parsed: null, problem: null };
  }
  let value: unknown;
  try {
    value = JSON.parse(rawValue);
  } catch {
    return { problem: "syntax" };
  }
  if (value === null) {
    return { parsed: null, problem: null };
  }
  // The server keeps an object or nothing in these fields. A list, a number or
  // a text is valid JSON it refuses at save, far from the box it was typed in.
  return isJsonObject(value) ? { parsed: value, problem: null } : { problem: "not_object" };
}

export function parseAdvancedJsonField(
  currentDrafts: AdvancedJsonDrafts,
  currentErrors: AdvancedJsonErrors,
  field: AdvancedJsonField,
  rawValue: string
): AdvancedJsonReading & { drafts: AdvancedJsonDrafts; errors: AdvancedJsonErrors } {
  const drafts = { ...currentDrafts, [field]: rawValue };
  const reading = readAdvancedJsonDraft(rawValue);
  const errors = { ...currentErrors };
  if (reading.problem === null) {
    delete errors[field];
  } else {
    errors[field] = reading.problem;
  }
  return { ...reading, drafts, errors };
}

export function formatAdvancedJsonDraftField(
  currentDrafts: AdvancedJsonDrafts,
  currentErrors: AdvancedJsonErrors,
  field: AdvancedJsonField
): AdvancedJsonReading & {
  drafts: AdvancedJsonDrafts;
  errors: AdvancedJsonErrors;
  formatted: boolean;
} {
  const result = parseAdvancedJsonField(currentDrafts, currentErrors, field, currentDrafts[field]);
  if (result.problem !== null || result.parsed === null) {
    return { ...result, formatted: false };
  }

  return {
    ...result,
    drafts: { ...result.drafts, [field]: formatAdvancedJson(result.parsed) },
    formatted: true
  };
}

export function getErrorFields(errors: AdvancedJsonErrors): string[] {
  return ADVANCED_JSON_FIELDS.filter((field) => Boolean(errors[field]));
}
