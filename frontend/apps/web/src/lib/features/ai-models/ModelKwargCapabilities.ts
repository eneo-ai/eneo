import type {
  CompletionModel,
  ModelKwargCapability,
  ModelKwargs,
  SupportedModelKwargs
} from "@eneo/eneo-js";

export type { ModelKwargCapability, SupportedModelKwargs };

export type ModelKwargName = keyof Pick<
  ModelKwargs,
  | "temperature"
  | "top_p"
  | "reasoning_effort"
  | "verbosity"
  | "presence_penalty"
  | "frequency_penalty"
  | "top_k"
>;

export type CompletionModelWithSupportedKwargs = Partial<CompletionModel> & {
  supported_model_kwargs?: SupportedModelKwargs | null;
};

export const modelSpecificKwargNames = [
  "reasoning_effort",
  "verbosity",
  "top_p",
  "presence_penalty",
  "frequency_penalty",
  "top_k"
] as const satisfies readonly ModelKwargName[];

export const configurableModelKwargNames = [
  "temperature",
  ...modelSpecificKwargNames
] as const satisfies readonly ModelKwargName[];

export function getModelKwargCapability(
  model: CompletionModelWithSupportedKwargs | null | undefined,
  kwargName: ModelKwargName
): ModelKwargCapability | null {
  return model?.supported_model_kwargs?.[kwargName] ?? null;
}

export function supportsModelKwarg(
  model: CompletionModelWithSupportedKwargs | null | undefined,
  kwargName: ModelKwargName
): boolean {
  return getModelKwargCapability(model, kwargName)?.supported === true;
}

export function supportsBehaviorPresets(
  model: CompletionModelWithSupportedKwargs | null | undefined
): boolean {
  return supportsModelKwarg(model, "temperature");
}

export function getModelSpecificKwargNames(
  model: CompletionModelWithSupportedKwargs | null | undefined
): ModelKwargName[] {
  return modelSpecificKwargNames.filter((kwargName) => supportsModelKwarg(model, kwargName));
}

export function hasModelSpecificSettings(
  model: CompletionModelWithSupportedKwargs | null | undefined
): boolean {
  return getModelSpecificKwargNames(model).length > 0;
}

export function shouldShowModelSpecificParametersInfo(
  model: CompletionModelWithSupportedKwargs | null | undefined
): boolean {
  return !supportsBehaviorPresets(model) && hasModelSpecificSettings(model);
}

export function filterSupportedModelKwargs(
  kwArgs: ModelKwargs | null | undefined,
  model: CompletionModelWithSupportedKwargs | null | undefined
): ModelKwargs {
  const filteredKwargs = { ...(kwArgs ?? {}) };

  for (const kwargName of configurableModelKwargNames) {
    if (!supportsModelKwarg(model, kwargName)) {
      delete filteredKwargs[kwargName];
    }
  }

  return filteredKwargs;
}
