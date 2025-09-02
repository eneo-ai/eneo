/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

const behaviours = Object.freeze({
  creative: {
    temperature: 1.25,
    top_p: null
  },
  default: { temperature: null, top_p: null },
  deterministic: { temperature: 0.25, top_p: null },
  custom: null
});

export type ModelBehaviour = keyof typeof behaviours;

export type ModelKwArgs = {
  temperature?: number | null | undefined;
  top_p?: number | null | undefined;
  reasoning_effort?: string | null | undefined;
  max_completion_tokens?: number | null | undefined;
  response_format?: object | null | undefined;
  presence_penalty?: number | null | undefined;
  frequency_penalty?: number | null | undefined;
  top_k?: number | null | undefined;
};

export const behaviourList = Object.keys(behaviours) as ModelBehaviour[];

export function getKwargs(behaviour: ModelBehaviour) {
  return behaviours[behaviour];
}

export function getBehaviour(
  kwargs:
    | {
        temperature?: number | null;
        top_p?: number | null;
      }
    | undefined
    | null
): ModelBehaviour {
  if (!kwargs) {
    return "custom";
  }

  // Extract only the fields that are relevant for behavior detection
  const relevantKwargs = {
    temperature: kwargs.temperature,
    top_p: kwargs.top_p
  };

  for (const behaviour of behaviourList) {
    const behaviourKwargs = behaviours[behaviour];
    if (JSON.stringify(behaviourKwargs) === JSON.stringify(relevantKwargs)) {
      return behaviour;
    }
  }
  return "custom";
}
