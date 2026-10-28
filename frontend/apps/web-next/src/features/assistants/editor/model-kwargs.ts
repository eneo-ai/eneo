import type { Schema } from "@/lib/api/models";

/**
 * Pure model-kwargs logic (unit-tested), ported from the Svelte
 * ModelBehaviours + ModelKwargCapabilities modules.
 */

export type ModelKwargs = Schema<"ModelKwargs">;
export type ModelKwargCapability = Schema<"ModelKwargCapability">;
export type SupportedModelKwargs = Schema<"SupportedModelKwargs">;

export type ModelWithKwargs = {
  supported_model_kwargs?: SupportedModelKwargs | null;
};

export type ModelKwargName =
  | "temperature"
  | "top_p"
  | "reasoning_effort"
  | "verbosity"
  | "presence_penalty"
  | "frequency_penalty"
  | "top_k";

export const MODEL_SPECIFIC_KWARGS = [
  "reasoning_effort",
  "verbosity",
  "top_p",
  "presence_penalty",
  "frequency_penalty",
  "top_k"
] as const satisfies readonly ModelKwargName[];

export const SELECT_KWARGS = ["reasoning_effort", "verbosity"] as const;
export type SelectKwargName = (typeof SELECT_KWARGS)[number];
export type NumericKwargName = Exclude<(typeof MODEL_SPECIFIC_KWARGS)[number], SelectKwargName>;

export function isSelectKwarg(name: ModelKwargName): name is SelectKwargName {
  return (SELECT_KWARGS as readonly string[]).includes(name);
}

export function modelKwargLabel(name: ModelKwargName, t: (key: string) => string): string {
  switch (name) {
    case "reasoning_effort":
      return t("reasoning_effort");
    case "verbosity":
      return t("verbosity");
    case "top_p":
      return t("top_p");
    case "presence_penalty":
      return t("presence_penalty");
    case "frequency_penalty":
      return t("frequency_penalty");
    case "top_k":
      return t("top_k");
    case "temperature":
      return t("temperature");
  }
}

export function modelKwargOptionLabel(option: string, t: (key: string) => string): string {
  switch (option) {
    case "none":
      return t("none");
    case "low":
      return t("parameter_option_low");
    case "medium":
      return t("parameter_option_medium");
    case "high":
      return t("parameter_option_high");
    default:
      return option;
  }
}

export function kwargCapability(
  model: ModelWithKwargs | null | undefined,
  name: ModelKwargName
): ModelKwargCapability | null {
  return model?.supported_model_kwargs?.[name] ?? null;
}

export function supportsKwarg(model: ModelWithKwargs | null | undefined, name: ModelKwargName) {
  return kwargCapability(model, name)?.supported === true;
}

/** Behaviour presets are temperature-based, so they need temperature support. */
export function supportsBehaviorPresets(model: ModelWithKwargs | null | undefined): boolean {
  return supportsKwarg(model, "temperature");
}

export function modelSpecificKwargs(model: ModelWithKwargs | null | undefined): ModelKwargName[] {
  return MODEL_SPECIFIC_KWARGS.filter((name) => supportsKwarg(model, name));
}

// --- Number settings ---

/** The settings typed as numbers: the custom temperature and the numeric model settings. */
export type NumericSettingName = NumericKwargName | "temperature";

const NUMERIC_SETTINGS = [
  "temperature",
  "top_p",
  "presence_penalty",
  "frequency_penalty",
  "top_k"
] as const satisfies readonly NumericSettingName[];

const DEFAULT_NUMERIC_MAX: Record<NumericSettingName, number> = {
  temperature: 2,
  top_p: 1,
  presence_penalty: 2,
  frequency_penalty: 2,
  top_k: 100
};

/** The backend stores these as whole numbers (ModelKwargs.top_k is an int). */
const WHOLE_NUMBER_SETTINGS: readonly NumericSettingName[] = ["top_k"];

/** The range a number setting takes: the model's own, else the editor's defaults. */
export function numericKwargRange(
  model: ModelWithKwargs | null | undefined,
  name: NumericSettingName
): { min: number; max: number; step: number; wholeNumber: boolean } {
  const capability = kwargCapability(model, name);
  const wholeNumber = WHOLE_NUMBER_SETTINGS.includes(name);
  return {
    min: capability?.minimum ?? 0,
    max: capability?.maximum ?? DEFAULT_NUMERIC_MAX[name],
    step: capability?.step ?? (wholeNumber ? 1 : 0.05),
    wholeNumber
  };
}

/** Whether a typed number can be saved for the setting: in its range, and whole where it must be. */
export function isValidNumericKwarg(
  model: ModelWithKwargs | null | undefined,
  name: NumericSettingName,
  value: number | null | undefined
): boolean {
  if (value == null) return true;
  const { min, max, wholeNumber } = numericKwargRange(model, name);
  return (
    Number.isFinite(value) &&
    value >= min &&
    value <= max &&
    (!wholeNumber || Number.isInteger(value))
  );
}

/**
 * The first typed number setting, in the editor's order, that the model takes
 * and that cannot be saved. Presets set the temperature themselves, so it is
 * checked only for a custom behaviour.
 */
export function firstInvalidNumericKwarg(
  model: ModelWithKwargs | null | undefined,
  kwargs: ModelKwargs
): NumericSettingName | null {
  const sent = filterSupportedKwargs(kwargs, model);
  const custom = behaviourFromKwargs(kwargs) === "custom";
  return (
    NUMERIC_SETTINGS.find(
      (name) =>
        (name !== "temperature" || custom) &&
        !isValidNumericKwarg(model, name, sent[name] as number | null | undefined)
    ) ?? null
  );
}

/** Strips kwargs the selected model does not support before saving. */
export function filterSupportedKwargs(
  kwargs: ModelKwargs | null | undefined,
  model: ModelWithKwargs | null | undefined
): ModelKwargs {
  const filtered: ModelKwargs = { ...(kwargs ?? {}) };
  for (const name of ["temperature", ...MODEL_SPECIFIC_KWARGS] as const) {
    if (!supportsKwarg(model, name)) delete filtered[name];
  }
  return filtered;
}

// --- Behaviour presets ---

const BEHAVIOURS = {
  creative: { temperature: 1.25 },
  default: { temperature: null },
  deterministic: { temperature: 0.25 },
  custom: null
} as const;

export type ModelBehaviour = keyof typeof BEHAVIOURS;
export const BEHAVIOUR_LIST = Object.keys(BEHAVIOURS) as ModelBehaviour[];

export function behaviourFromKwargs(
  kwargs: Pick<ModelKwargs, "temperature"> | null | undefined
): ModelBehaviour {
  if (!kwargs) return "custom";
  for (const behaviour of BEHAVIOUR_LIST) {
    const preset = BEHAVIOURS[behaviour];
    if (preset && preset.temperature === (kwargs.temperature ?? null)) return behaviour;
  }
  return "custom";
}

/** Temperature for a preset; null means "apply no preset" (custom). */
export function kwargsForBehaviour(
  behaviour: ModelBehaviour
): { temperature: number | null } | null {
  return BEHAVIOURS[behaviour];
}
