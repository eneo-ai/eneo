/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

const behaviours = Object.freeze({
  creative: {
    temperature: 1.25,
    top_p: null,
    verbosity: "high",        // GPT-5: More detailed, expansive responses
    reasoning_effort: "medium" // Balanced reasoning depth
  },
  default: { 
    temperature: null, 
    top_p: null,
    verbosity: null,          // Use model defaults
    reasoning_effort: null
  },
  deterministic: { 
    temperature: 0.25, 
    top_p: null,
    verbosity: "low",         // GPT-5: Concise, focused responses
    reasoning_effort: "high"  // Maximum reasoning for accuracy
  },
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

export function getKwargs(behaviour: ModelBehaviour, model?: any) {
  const basePreset = behaviours[behaviour];
  if (!basePreset || !model) return basePreset;
  
  // Filter out fields the model doesn't support
  const filtered = Object.entries(basePreset).reduce((acc: any, [key, value]) => {
    // Always include basic parameters
    if (key === 'temperature' || key === 'top_p') {
      acc[key] = value;
      return acc;
    }
    
    // Only include reasoning_effort for models with reasoning=true
    if (key === 'reasoning_effort' && !model.reasoning) return acc;
    
    // Only include verbosity for GPT-5 models (checked by supports_verbosity flag)
    if (key === 'verbosity' && !model.supports_verbosity) return acc;
    
    acc[key] = value;
    return acc;
  }, {});
  
  return filtered;
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
    | null,
  model?: any
): ModelBehaviour {
  if (!kwargs) {
    return "default";
  }

  for (const behaviour of behaviourList) {
    if (behaviour === "custom") continue; // Skip custom since it has null kwargs
    
    // Get the model-aware preset for this behavior
    const behaviourKwargs = getKwargs(behaviour, model);
    if (!behaviourKwargs) continue;
    
    // Compare only the fields that are defined in the model-aware preset
    const matches = Object.entries(behaviourKwargs).every(([key, value]) => 
      kwargs[key as keyof typeof kwargs] === value
    );
    
    if (matches) {
      return behaviour;
    }
  }
  return "custom";
}
