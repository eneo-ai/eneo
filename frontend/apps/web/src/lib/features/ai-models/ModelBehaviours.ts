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

export type ReasoningLevel = "disabled" | "low" | "medium" | "high";

export type ModelKwArgs = {
  temperature?: number | null | undefined;
  top_p?: number | null | undefined;
  thinking_budget?: number | null | undefined; // Legacy support - will be deprecated
  reasoning_level?: ReasoningLevel | null | undefined; // New unified approach
};

export const behaviourList = Object.keys(behaviours) as ModelBehaviour[];

export function getKwargs(behaviour: ModelBehaviour) {
  return behaviours[behaviour];
}

/**
 * Convert thinking_budget to reasoning_level for migration and compatibility
 */
export function migrateThinkingBudgetToReasoningLevel(thinking_budget?: number | null): ReasoningLevel {
  if (!thinking_budget || thinking_budget === 0) {
    return "disabled";
  }
  if (thinking_budget <= 512) {
    return "low";
  }
  if (thinking_budget <= 1024) {
    return "medium";
  }
  return "high";
}

/**
 * Convert reasoning_level to thinking_budget for backward compatibility
 */
export function convertReasoningLevelToThinkingBudget(reasoning_level?: ReasoningLevel | null): number {
  switch (reasoning_level) {
    case "disabled":
      return 0;
    case "low":
      return 512;
    case "medium":
      return 1024;
    case "high":
      return 2048;
    default:
      return 0;
  }
}

/**
 * Get effective reasoning level, preferring reasoning_level over thinking_budget
 */
export function getEffectiveReasoningLevel(kwargs?: ModelKwArgs | null): ReasoningLevel {
  if (!kwargs) return "disabled";
  
  // New system takes precedence
  if (kwargs.reasoning_level !== undefined && kwargs.reasoning_level !== null) {
    return kwargs.reasoning_level;
  }
  
  // Fallback to thinking_budget conversion
  return migrateThinkingBudgetToReasoningLevel(kwargs.thinking_budget);
}

export function getBehaviour(
  kwargs:
    | {
        temperature?: number | null;
        top_p?: number | null;
        thinking_budget?: number | null;
        reasoning_level?: ReasoningLevel | null;
      }
    | undefined
    | null
): ModelBehaviour {
  for (const behaviour of behaviourList) {
    const behaviourKwargs = behaviours[behaviour];
    // Only compare temperature and top_p for predefined behaviors
    const compareKwargs = {
      temperature: kwargs?.temperature,
      top_p: kwargs?.top_p
    };
    if (JSON.stringify(behaviourKwargs) === JSON.stringify(compareKwargs)) {
      return behaviour;
    }
  }
  return "custom";
}