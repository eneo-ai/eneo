import type { FlowStep } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import {
  getFlowFormFieldVariableExpression,
  isFlowFormFieldNameUsableAsVariable
} from "$lib/features/flows/flowFormSchema";
import type {
  VariableCategory,
  VariableClassificationContext
} from "$lib/features/flows/flowVariableTokens";

type PromptFormSchema =
  | {
      fields: {
        name: string;
        type: string;
        required?: boolean;
        options?: string[];
        order?: number;
      }[];
    }
  | undefined;

/**
 * Build the variable-classification context the prompt editor uses to parse and
 * suggest tokens. Read-only after construction, so plain Set/Map — not reactive
 * collections.
 */
export function buildContext(
  steps: FlowStep[],
  formSchema: PromptFormSchema,
  transcriptionEnabled: boolean,
  currentStepOrder: number
): VariableClassificationContext {
  const knownFieldNames = new Set<string>();
  for (const field of formSchema?.fields ?? []) {
    const name = (field.name ?? "").trim();
    if (isFlowFormFieldNameUsableAsVariable(name)) knownFieldNames.add(name);
  }
  const knownStepNames = new Map<number, string>();
  const stepOutputTypes = new Map<number, string>();
  for (const step of steps) {
    const name = (step.user_description ?? "").trim();
    if (name) knownStepNames.set(step.step_order, name);
    stepOutputTypes.set(step.step_order, step.output_type);
  }
  return {
    knownFieldNames,
    knownStepNames,
    stepOutputTypes,
    transcriptionEnabled,
    currentStepOrder
  };
}

export type VariableSuggestion = {
  token: string;
  label: string;
  description: string;
  category: VariableCategory;
  displayToken?: boolean;
};

/**
 * The variables offered in the prompt editor's picker and chip bar, ordered
 * form-fields → system → previous-step aliases → technical step outputs.
 * Technical tokens (`föregående_steg`, `step_N.output.text`) are gated behind
 * `showTechnical` (advanced mode).
 */
export function buildAvailableVariables(
  ctx: VariableClassificationContext,
  steps: FlowStep[],
  showTechnical: boolean
): VariableSuggestion[] {
  const suggestions: VariableSuggestion[] = [];

  for (const name of ctx.knownFieldNames) {
    const token = getFlowFormFieldVariableExpression(name);
    if (!token) continue;
    suggestions.push({
      token,
      label: name,
      description: m.flow_variable_form_field(),
      category: "field",
      displayToken: true
    });
  }

  if (ctx.transcriptionEnabled) {
    suggestions.push({
      token: "transkribering",
      label: "transkribering",
      description: m.flow_variable_transcription(),
      category: "system"
    });
  }
  if (showTechnical && ctx.currentStepOrder > 1) {
    suggestions.push({
      token: "föregående_steg",
      label: "föregående_steg",
      description: m.flow_variable_previous_step(),
      category: "system"
    });
  }

  for (const [order, name] of ctx.knownStepNames) {
    if (order < ctx.currentStepOrder && name) {
      suggestions.push({
        token: name,
        label: name,
        description: m.flow_variable_step_alias({ order: String(order) }),
        category: "step"
      });
    }
  }

  if (showTechnical) {
    const previousSteps = steps.filter((s) => s.step_order < ctx.currentStepOrder);
    for (const step of previousSteps) {
      suggestions.push({
        token: `step_${step.step_order}.output.text`,
        label: `step_${step.step_order}.output.text`,
        description: m.flow_variable_text_output(),
        category: "step"
      });
    }
  }

  return suggestions;
}
