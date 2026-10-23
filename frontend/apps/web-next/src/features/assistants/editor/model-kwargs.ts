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
