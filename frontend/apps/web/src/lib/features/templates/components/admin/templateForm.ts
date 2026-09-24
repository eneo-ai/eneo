import type { components } from "@eneo/eneo-js";

type TemplateWizardConfig = components["schemas"]["TemplateWizard"];

export type WizardStepKind = "attachments" | "collections";

export type WizardStep = {
  enabled: boolean;
  required: boolean;
  title: string;
  description: string;
};

/**
 * Stored wizards come as `{ attachments, collections }` or, from older templates, as a
 * `wizard_config` array of `{ type: "attachments" | "collections", ... }`.
 */
export function readWizardSteps(template?: {
  wizard?: unknown;
  wizard_config?: unknown;
}): Record<WizardStepKind, WizardStep> {
  const wizard: unknown = template?.wizard_config ?? template?.wizard ?? {};
  const find = (kind: WizardStepKind): unknown =>
    Array.isArray(wizard)
      ? wizard.find((config) => config?.type === kind)
      : (wizard as Record<string, unknown>)[kind];
  return { attachments: toStep(find("attachments")), collections: toStep(find("collections")) };
}

function toStep(value: unknown): WizardStep {
  const config = value as Partial<TemplateWizardConfig> | null | undefined;
  return {
    enabled: !!config,
    required: Boolean(config?.required),
    title: String(config?.title || ""),
    description: String(config?.description || "")
  };
}

export function toWizardPayload(step: WizardStep): TemplateWizardConfig | null {
  return step.enabled
    ? {
        required: step.required,
        title: step.title || undefined,
        description: step.description || undefined
      }
    : null;
}

export function findTemplateModel<T extends { id: string; name: string }>(
  models: T[],
  template?: { completion_model_id?: string | null; completion_model_name?: string | null }
): T | null {
  const match =
    template &&
    models.find(
      (model) =>
        model.id === template.completion_model_id || model.name === template.completion_model_name
    );
  return match || models[0] || null;
}
