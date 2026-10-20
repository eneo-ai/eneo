import type { Schema } from "@/lib/api/models";

type Translate = (key: string) => string;

type ModelWithKwargs = {
  supported_model_kwargs?: Schema<"SupportedModelKwargs"> | null;
} | null;

/**
 * The reasoning-effort levels a model offers as a choice (its
 * `supported_model_kwargs.reasoning_effort` capability with a select
 * control); empty when the model has no reasoning or takes no level.
 */
export function reasoningEffortOptions(model: ModelWithKwargs | undefined): string[] {
  const capability = model?.supported_model_kwargs?.reasoning_effort;
  return capability?.supported && capability.control === "select" ? (capability.options ?? []) : [];
}

/**
 * The level in force: the user's stored pick when the model offers it, else
 * the organisation policy's default when the model offers that, else null
 * (the model's own default behaviour).
 */
export function effectiveReasoningEffort({
  stored,
  policyDefault,
  options
}: {
  stored: string | null | undefined;
  policyDefault: string | null | undefined;
  options: string[];
}): string | null {
  if (stored && options.includes(stored)) return stored;
  if (policyDefault && options.includes(policyDefault)) return policyDefault;
  return null;
}

const OPTION_KEY: Record<string, string> = {
  none: "none",
  minimal: "parameter_option_minimal",
  low: "parameter_option_low",
  medium: "parameter_option_medium",
  high: "parameter_option_high",
  xhigh: "parameter_option_extra_high",
  max: "parameter_option_maximum"
};

/** The translated name of a level ("Hög"); an unknown level is shown as it is written. */
export function reasoningEffortLabel(option: string, t: Translate): string {
  const key = OPTION_KEY[option];
  return key ? t(key) : option.replaceAll("_", " ");
}
