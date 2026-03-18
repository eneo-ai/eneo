import type { FlowStep } from "@intric/intric-js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type AdvancedJsonField =
  | "input_contract"
  | "output_contract"
  | "input_config"
  | "output_config";

export const ADVANCED_JSON_FIELDS: AdvancedJsonField[] = [
  "input_contract",
  "output_contract",
  "input_config",
  "output_config"
];

export type AdvancedJsonDrafts = Record<AdvancedJsonField, string>;
export type AdvancedJsonErrors = Partial<Record<AdvancedJsonField, string>>;

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

export function formatAdvancedJson(value: unknown): string {
  return value == null ? "" : JSON.stringify(value, null, 2);
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
  if (step && (step.input_source === "http_get" || step.input_source === "http_post")) {
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
// These return new state objects so Svelte 3 reactivity works via assignment.
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

export function parseAdvancedJsonField(
  currentDrafts: AdvancedJsonDrafts,
  currentErrors: AdvancedJsonErrors,
  field: AdvancedJsonField,
  rawValue: string
): {
  drafts: AdvancedJsonDrafts;
  errors: AdvancedJsonErrors;
  parsed: unknown | null;
  parseError: string | null;
} {
  const drafts = { ...currentDrafts, [field]: rawValue };
  const trimmed = rawValue.trim();

  if (trimmed.length === 0) {
    const errors = { ...currentErrors };
    delete errors[field];
    return { drafts, errors, parsed: null, parseError: null };
  }

  try {
    const parsed = JSON.parse(rawValue);
    const errors = { ...currentErrors };
    delete errors[field];
    return { drafts, errors, parsed, parseError: null };
  } catch (error) {
    const detail =
      error instanceof Error && error.message.trim().length > 0
        ? error.message
        : "Invalid JSON syntax";
    const parseError = detail;
    const errors = { ...currentErrors, [field]: parseError };
    return { drafts, errors, parsed: null, parseError };
  }
}

export function getErrorFields(errors: AdvancedJsonErrors): string[] {
  return ADVANCED_JSON_FIELDS.filter((field) => Boolean(errors[field]));
}
