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
  verbosity?: string | null | undefined;
  max_completion_tokens?: number | null | undefined;
  // Additional fields returned by server (for compatibility)
  max_reasoning_tokens?: number | null | undefined;
  max_thinking_tokens?: number | null | undefined;
  max_tokens?: number | null | undefined;
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
        reasoning_effort?: string | null;
        verbosity?: string | null;
        max_completion_tokens?: number | null;
        max_reasoning_tokens?: number | null;
        max_thinking_tokens?: number | null;
        max_tokens?: number | null;
      }
    | undefined
    | null
): ModelBehaviour {
  for (const behaviour of behaviourList) {
    const behaviourKwargs = behaviours[behaviour];
    if (JSON.stringify(behaviourKwargs) === JSON.stringify(kwargs)) {
      return behaviour;
    }
  }
  return "custom";
}
