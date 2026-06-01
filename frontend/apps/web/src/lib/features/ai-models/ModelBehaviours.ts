/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

const behaviours = Object.freeze({
  creative: {
    temperature: 1.25
  },
  default: { temperature: null },
  deterministic: { temperature: 0.25 },
  custom: null
});

export type ModelBehaviour = keyof typeof behaviours;

export type ModelKwArgs = {
  temperature?: number | null | undefined;
  top_p?: number | null | undefined;
  reasoning_effort?: string | null | undefined;
  verbosity?: string | null | undefined;
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

  for (const behaviour of behaviourList) {
    const behaviourKwargs = behaviours[behaviour];
    if (behaviourKwargs?.temperature === kwargs.temperature) {
      return behaviour;
    }
  }
  return "custom";
}
