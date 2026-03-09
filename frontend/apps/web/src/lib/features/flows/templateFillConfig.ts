import type { FlowStep } from "@intric/intric-js";

export type FlowTemplatePlaceholder = {
  name: string;
  location: string;
  preview?: string | null;
};

export type FlowTemplateInspection = {
  asset_id?: string | null;
  file_id: string;
  file_name: string;
  placeholders: FlowTemplatePlaceholder[];
  extracted_text_preview?: string | null;
};

export type TemplateBindingSuggestion = {
  value: string;
  label: string;
  group: "form" | "step" | "system";
  outputType?: "text" | "json" | null;
};

export type TemplateBindingSuggestionLabels = {
  formField: string;
  aiSection: string;
  systemVariable: string;
  formFieldItem: (name: string) => string;
  stepTextItem: (stepLabel: string) => string;
  stepJsonItem: (stepLabel: string) => string;
  todayDate: string;
  leaveEmpty: string;
  emptyValue: string;
};

export type TemplateBindingSuggestionGroup = {
  key: "form" | "step" | "system";
  label: string;
  icon: string;
  options: TemplateBindingSuggestion[];
};

export type TemplateBindingStatus = "matched" | "missing" | "invalid" | "orphaned";

export type TemplateBindingRow = {
  key: string;
  placeholderName: string;
  binding?: string;
  location: string;
  preview?: string | null;
  sourceLabel: string | null;
  status: TemplateBindingStatus;
  autoSuggested: boolean;
  isExplicitEmpty: boolean;
  sourceOutputType?: "text" | "json" | null;
};

export type TemplateFillReadiness = {
  total: number;
  matched: number;
  incomplete: boolean;
};

export type TemplateFillOutputConfig = {
  template_asset_id?: string;
  template_file_id?: string;
  template_name?: string;
  template_checksum?: string;
  placeholders?: string[];
  bindings?: Record<string, string>;
};

export type FlowTemplateAssetOption = {
  id: string;
  file_id: string;
  name: string;
  status?: string | null;
  last_updated_by_name?: string | null;
  can_edit?: boolean;
  can_download?: boolean;
};

export function isTemplateFillStep(
  step: Pick<FlowStep, "output_mode"> | null | undefined
): boolean {
  return step?.output_mode === "template_fill";
}

export function getTemplateFillOutputConfig(
  step: Pick<FlowStep, "output_config"> | null | undefined
): TemplateFillOutputConfig {
  if (
    !step?.output_config ||
    typeof step.output_config !== "object" ||
    Array.isArray(step.output_config)
  ) {
    return {};
  }
  return step.output_config as TemplateFillOutputConfig;
}

export function resolveTemplateAssetSelection(
  config: TemplateFillOutputConfig,
  assets: FlowTemplateAssetOption[]
): { asset: FlowTemplateAssetOption | null; assetId: string | null } {
  const directMatch =
    (config.template_asset_id
      ? assets.find((asset) => asset.id === config.template_asset_id)
      : undefined) ?? null;
  if (directMatch) {
    return { asset: directMatch, assetId: directMatch.id };
  }

  const legacyMatch =
    !config.template_asset_id && config.template_file_id
      ? assets.find((asset) => asset.file_id === config.template_file_id) ?? null
      : null;
  if (legacyMatch) {
    return { asset: legacyMatch, assetId: legacyMatch.id };
  }

  return {
    asset: null,
    assetId: config.template_asset_id ?? null
  };
}

export function createTemplateFillDraftConfig(
  currentConfig: TemplateFillOutputConfig
): TemplateFillOutputConfig {
  return {
    ...currentConfig,
    bindings: { ...(currentConfig.bindings ?? {}) },
    placeholders: [...(currentConfig.placeholders ?? [])]
  };
}

export function applyTemplateInspection(
  currentConfig: TemplateFillOutputConfig,
  inspection: FlowTemplateInspection,
  suggestedBindings: Record<string, string> = {}
): TemplateFillOutputConfig {
  const nextBindings = { ...(currentConfig.bindings ?? {}) };
  for (const placeholder of inspection.placeholders) {
    if (!(placeholder.name in nextBindings)) {
      if (suggestedBindings[placeholder.name]) {
        nextBindings[placeholder.name] = suggestedBindings[placeholder.name];
      }
    } else if (!nextBindings[placeholder.name]?.trim() && suggestedBindings[placeholder.name]) {
      nextBindings[placeholder.name] = suggestedBindings[placeholder.name];
    }
  }
  return {
    ...currentConfig,
    template_asset_id: inspection.asset_id ?? undefined,
    template_file_id: inspection.file_id,
    template_name: inspection.file_name,
    placeholders: inspection.placeholders.map((item) => item.name),
    bindings: nextBindings
  };
}

export function updateTemplateBinding(
  currentConfig: TemplateFillOutputConfig,
  placeholder: string,
  expression: string
): TemplateFillOutputConfig {
  return {
    ...currentConfig,
    bindings: {
      ...(currentConfig.bindings ?? {}),
      [placeholder]: expression
    }
  };
}

export function listTemplatePlaceholders(
  inspection: FlowTemplateInspection | null,
  currentConfig: TemplateFillOutputConfig
): FlowTemplatePlaceholder[] {
  if (inspection?.placeholders?.length) {
    return inspection.placeholders;
  }
  return (currentConfig.placeholders ?? []).map((name) => ({
    name,
    location: "template",
    preview: null
  }));
}

export function buildTemplateBindingSuggestions(params: {
  steps: Pick<FlowStep, "step_order" | "user_description" | "output_type">[];
  currentStepOrder: number;
  labels: TemplateBindingSuggestionLabels;
  formSchema:
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
}): TemplateBindingSuggestion[] {
  const suggestions: TemplateBindingSuggestion[] = [];
  const seen = new Set<string>();

  const addSuggestion = (
    value: string,
    label: string,
    group: TemplateBindingSuggestion["group"],
    outputType: TemplateBindingSuggestion["outputType"] = null
  ) => {
    if (seen.has(value)) return;
    seen.add(value);
    suggestions.push({ value, label, group, outputType });
  };

  for (const field of params.formSchema?.fields ?? []) {
    addSuggestion(`{{${field.name}}}`, params.labels.formFieldItem(field.name), "form", "text");
  }

  for (const step of params.steps) {
    if (step.step_order >= params.currentStepOrder) continue;
    const stepLabel = step.user_description?.trim() || `Steg ${step.step_order}`;
    addSuggestion(
      `{{step_${step.step_order}.output.text}}`,
      params.labels.stepTextItem(stepLabel),
      "step",
      "text"
    );
    if (step.output_type === "json") {
      addSuggestion(
        `{{step_${step.step_order}.output.structured}}`,
        params.labels.stepJsonItem(stepLabel),
        "step",
        "json"
      );
    }
  }

  addSuggestion("{{datum}}", params.labels.todayDate, "system", "text");

  return suggestions;
}

export function groupTemplateBindingSuggestions(
  suggestions: TemplateBindingSuggestion[],
  labels: Pick<TemplateBindingSuggestionLabels, "formField" | "aiSection" | "systemVariable">
): TemplateBindingSuggestionGroup[] {
  const grouped: TemplateBindingSuggestionGroup[] = [
    { key: "form", label: labels.formField, icon: "", options: [] },
    { key: "step", label: labels.aiSection, icon: "", options: [] },
    { key: "system", label: labels.systemVariable, icon: "", options: [] }
  ];
  for (const suggestion of suggestions) {
    const targetGroup = grouped.find((group) => group.key === suggestion.group);
    targetGroup?.options.push(suggestion);
  }
  return grouped.filter((group) => group.options.length > 0);
}

function normalizeTemplateToken(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "");
}

export function buildTemplateBindingAutoSuggestions(params: {
  placeholders: string[];
  steps: Pick<FlowStep, "step_order" | "user_description" | "output_type">[];
  currentStepOrder: number;
  formSchema:
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
}): Record<string, string> {
  const fieldMatches = new Map<string, string>();
  for (const field of params.formSchema?.fields ?? []) {
    fieldMatches.set(normalizeTemplateToken(field.name), `{{${field.name}}}`);
  }

  const stepMatches = new Map<string, string>();
  for (const step of params.steps) {
    if (step.step_order >= params.currentStepOrder) continue;
    const expression =
      step.output_type === "json"
        ? `{{step_${step.step_order}.output.structured}}`
        : `{{step_${step.step_order}.output.text}}`;
    const label = step.user_description?.trim();
    if (label) {
      stepMatches.set(normalizeTemplateToken(label), expression);
    }
  }

  const suggestions: Record<string, string> = {};
  for (const placeholder of params.placeholders) {
    const normalized = normalizeTemplateToken(placeholder);
    if (!normalized) continue;
    if (fieldMatches.has(normalized)) {
      suggestions[placeholder] = fieldMatches.get(normalized)!;
      continue;
    }
    if (stepMatches.has(normalized)) {
      suggestions[placeholder] = stepMatches.get(normalized)!;
    }
  }

  return suggestions;
}

export function applyAutoTemplateBindings(params: {
  currentConfig: TemplateFillOutputConfig;
  autoSuggestions: Record<string, string>;
  placeholders: string[];
}): TemplateFillOutputConfig {
  const nextBindings = { ...(params.currentConfig.bindings ?? {}) };
  for (const placeholder of params.placeholders) {
    const currentValue = nextBindings[placeholder];
    if (typeof currentValue === "string") continue;
    const suggestion = params.autoSuggestions[placeholder];
    if (suggestion) {
      nextBindings[placeholder] = suggestion;
    }
  }
  return {
    ...params.currentConfig,
    bindings: nextBindings
  };
}

export function getTemplateFillReadiness(config: TemplateFillOutputConfig): TemplateFillReadiness {
  const placeholders = [...(config.placeholders ?? [])];
  const bindings = config.bindings ?? {};
  const matched = placeholders.filter((placeholder) =>
    Object.prototype.hasOwnProperty.call(bindings, placeholder)
  ).length;
  return {
    total: placeholders.length,
    matched,
    incomplete: placeholders.length > 0 && matched < placeholders.length
  };
}

export function getTemplateFillTemplateName(
  step: Pick<FlowStep, "output_config"> | null | undefined
): string | null {
  const config = getTemplateFillOutputConfig(step);
  return typeof config.template_name === "string" && config.template_name.trim()
    ? config.template_name
    : null;
}

export function getTemplateFillDryRunIssues(params: {
  step: Pick<FlowStep, "step_order" | "output_mode" | "output_type" | "output_config">;
}): string[] {
  if (!isTemplateFillStep(params.step)) return [];

  const config = getTemplateFillOutputConfig(params.step);
  const placeholders = config.placeholders ?? [];
  const bindings = config.bindings ?? {};
  const issues: string[] = [];

  if (params.step.output_type !== "docx") {
    issues.push("Template fill requires Word output.");
  }

  if (!config.template_file_id?.trim()) {
    issues.push("Missing DOCX template.");
  }

  if (placeholders.length === 0) {
    issues.push("No placeholders found in the selected DOCX template.");
  }

  for (const placeholder of placeholders) {
    if (!Object.prototype.hasOwnProperty.call(bindings, placeholder)) {
      issues.push(`Missing mapping for template placeholder '${placeholder}'.`);
      continue;
    }

    const expression = bindings[placeholder];
    if (typeof expression !== "string") {
      issues.push(`Template placeholder '${placeholder}' has an invalid mapping value.`);
      continue;
    }

    const matches = [...expression.matchAll(/step_(\d+)/g)];
    for (const match of matches) {
      const referencedStepOrder = Number.parseInt(match[1] ?? "", 10);
      if (Number.isNaN(referencedStepOrder)) continue;
      if (referencedStepOrder >= params.step.step_order) {
        issues.push(
          `Template placeholder '${placeholder}' references step ${referencedStepOrder}, which is not available before step ${params.step.step_order}.`
        );
      }
    }
  }

  const placeholderSet = new Set(placeholders);
  for (const placeholderName of Object.keys(bindings)) {
    if (!placeholderSet.has(placeholderName)) {
      issues.push(
        `Template mapping '${placeholderName}' no longer exists in the selected DOCX template.`
      );
    }
  }

  return issues;
}

export function listTemplateBindingRows(params: {
  inspection: FlowTemplateInspection | null;
  currentConfig: TemplateFillOutputConfig;
  suggestions: TemplateBindingSuggestion[];
  autoSuggestions?: Record<string, string>;
  labels: Pick<TemplateBindingSuggestionLabels, "emptyValue" | "leaveEmpty">;
}): TemplateBindingRow[] {
  const templatePlaceholders = listTemplatePlaceholders(params.inspection, params.currentConfig);
  const currentBindings = params.currentConfig.bindings ?? {};
  const currentPlaceholderNames = new Set(templatePlaceholders.map((item) => item.name));
  const suggestionByValue = new Map(params.suggestions.map((item) => [item.value, item]));
  const rows: TemplateBindingRow[] = [];

  for (const placeholder of templatePlaceholders) {
    const hasBinding = Object.prototype.hasOwnProperty.call(currentBindings, placeholder.name);
    const binding = hasBinding ? currentBindings[placeholder.name] : undefined;
    const suggestion = typeof binding === "string" ? suggestionByValue.get(binding) : undefined;
    rows.push({
      key: placeholder.name,
      placeholderName: placeholder.name,
      binding,
      location: placeholder.location,
      preview: placeholder.preview,
      sourceLabel:
        binding === params.labels.emptyValue
          ? params.labels.leaveEmpty
          : (suggestion?.label ?? (binding?.trim() ? binding : null)),
      status: !hasBinding ? "missing" : "matched",
      autoSuggested:
        Boolean(params.autoSuggestions?.[placeholder.name]) &&
        params.autoSuggestions?.[placeholder.name] === binding,
      isExplicitEmpty: hasBinding && binding === params.labels.emptyValue,
      sourceOutputType: suggestion?.outputType ?? null
    });
  }

  for (const [placeholderName, binding] of Object.entries(currentBindings)) {
    if (currentPlaceholderNames.has(placeholderName)) continue;
    const suggestion = suggestionByValue.get(binding);
    rows.push({
      key: `orphaned:${placeholderName}`,
      placeholderName,
      binding,
      location: "template",
      preview: null,
      sourceLabel:
        binding === params.labels.emptyValue
          ? params.labels.leaveEmpty
          : (suggestion?.label ?? binding),
      status: "orphaned",
      autoSuggested: false,
      isExplicitEmpty: binding === params.labels.emptyValue,
      sourceOutputType: suggestion?.outputType ?? null
    });
  }

  return rows;
}
