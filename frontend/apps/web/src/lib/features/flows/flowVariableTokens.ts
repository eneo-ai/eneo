import {
  isFlowFormFieldBareAliasSafe,
  PRIMARY_FLOW_INPUT_KEYS,
  RESERVED_RUNTIME_VARIABLES
} from "./flowFormSchema";

const TEMPLATE_TOKEN_PATTERN_SOURCE = String.raw`\{\{\s*([^{}]+)\s*\}\}`;
const TEMPLATE_TOKEN_PATTERN = new RegExp(TEMPLATE_TOKEN_PATTERN_SOURCE, "g");
const STEP_ORDER_TOKEN_PATTERN = /^step_(\d+)(\..+)?$/;
const STEP_REFERENCE_TOKEN_PATTERN = /^step_(\d+)(\.|$)/;
const STRUCTURED_OUTPUT_TOKEN_PATTERN = /^step_(\d+)\.output\.structured(?:\.|$)/;
const DELETED_STEP_TOKEN_PATTERN = /^step_(\d+)_deleted(?:\.|$)/;
const TEMPLATE_NAMESPACE_VARIABLES = new Set(["flow", "flow_input", "step_input"]);
const SYSTEM_VARIABLE_NAMES = new Set(
  [...RESERVED_RUNTIME_VARIABLES].filter((name) => !TEMPLATE_NAMESPACE_VARIABLES.has(name))
);
const REMOVED_FLOW_INPUT_TEMPLATE_KEYS = new Set(["file_ids"]);
export type StepOrderRemapResult = {
  text: string;
  changed: boolean;
  rewrittenDeletedReferences: number[];
};

export function extractTemplateTokens(text: string): string[] {
  const tokens = new Set<string>();
  for (const match of text.matchAll(TEMPLATE_TOKEN_PATTERN)) {
    const token = match[1]?.trim();
    if (token) tokens.add(token);
  }
  return [...tokens];
}

export function collectTemplateStepReferenceOrders(text: string): number[] {
  const orders = new Set<number>();
  for (const token of extractTemplateTokens(text)) {
    const stepMatch = STEP_ORDER_TOKEN_PATTERN.exec(token);
    if (!stepMatch) continue;
    orders.add(Number(stepMatch[1]));
  }
  return [...orders].sort((a, b) => a - b);
}

export function getInputTemplateSourceConflictStepOrders({
  inputSource,
  stepOrder,
  templateStepRefs
}: {
  inputSource: string | null | undefined;
  stepOrder: number;
  templateStepRefs: number[];
}): number[] | null {
  if (templateStepRefs.length === 0) return null;

  const unavailableRefs = templateStepRefs.filter((order) => order >= stepOrder);
  if (unavailableRefs.length > 0) return unavailableRefs;

  if (inputSource === "previous_step" || inputSource === "all_previous_steps") {
    return null;
  }

  return templateStepRefs;
}

export function replaceExactTemplateToken(
  text: string,
  fromToken: string,
  toToken: string
): string {
  const fromNormalized = fromToken.trim();
  const toNormalized = toToken.trim();
  if (!fromNormalized || !toNormalized || fromNormalized === toNormalized) return text;

  return text.replace(TEMPLATE_TOKEN_PATTERN, (full, rawToken: string) => {
    const normalized = rawToken.trim();
    if (normalized !== fromNormalized) return full;
    return `{{${toNormalized}}}`;
  });
}

export function remapStepOrderTemplateTokens(
  text: string,
  remapByOldOrder: Map<number, number>,
  deletedOrders: Set<number>
): StepOrderRemapResult {
  const rewrittenDeletedReferences = new Set<number>();
  let changed = false;
  const rewritten = text.replace(TEMPLATE_TOKEN_PATTERN, (full, rawToken: string) => {
    const token = rawToken.trim();
    const stepMatch = STEP_ORDER_TOKEN_PATTERN.exec(token);
    if (!stepMatch) return full;

    const oldOrder = Number(stepMatch[1]);
    const suffix = stepMatch[2] ?? "";

    if (deletedOrders.has(oldOrder)) {
      rewrittenDeletedReferences.add(oldOrder);
      changed = true;
      return `{{step_${oldOrder}_deleted${suffix}}}`;
    }

    const newOrder = remapByOldOrder.get(oldOrder);
    if (newOrder === undefined || newOrder === oldOrder) return full;

    changed = true;
    return `{{step_${newOrder}${suffix}}}`;
  });

  return {
    text: rewritten,
    changed,
    rewrittenDeletedReferences: [...rewrittenDeletedReferences]
  };
}

// --- Unified Variable Color System ---

export type VariableCategory = "field" | "system" | "step" | "structured" | "technical" | "unknown";

type VariableCategoryClasses = {
  chip: string;
  text: string;
  scopeClass: string;
};

export const VARIABLE_CATEGORY_CLASSES: Record<VariableCategory, VariableCategoryClasses> = {
  field: {
    chip: "label-blue bg-label-dimmer text-label-stronger",
    text: "text-label-stronger",
    scopeClass: "label-blue"
  },
  system: {
    chip: "label-amethyst bg-label-dimmer text-label-stronger",
    text: "text-label-stronger",
    scopeClass: "label-amethyst"
  },
  step: {
    chip: "label-green bg-label-dimmer text-label-stronger",
    text: "text-label-stronger",
    scopeClass: "label-green"
  },
  structured: {
    chip: "label-amethyst bg-label-dimmer text-label-stronger",
    text: "text-label-stronger",
    scopeClass: "label-amethyst"
  },
  technical: {
    chip: "label-blue bg-label-dimmer text-label-stronger",
    text: "text-label-stronger",
    scopeClass: "label-blue"
  },
  unknown: {
    chip: "label-red bg-label-dimmer text-label-stronger",
    text: "text-label-stronger",
    scopeClass: "label-red"
  }
};

export function getChipClasses(category: VariableCategory): string {
  return `rounded-md px-1.5 py-0.5 text-xs font-medium font-mono ${VARIABLE_CATEGORY_CLASSES[category].chip}`;
}

export type VariableClassificationContext = {
  knownFieldNames: Set<string>;
  knownStepNames: Map<number, string>; // stepOrder -> user_description
  stepOutputTypes: Map<number, string>;
  transcriptionEnabled: boolean;
  currentStepOrder: number;
};

export function classifyVariable(
  token: string,
  context: VariableClassificationContext
): VariableCategory {
  const analysis = analyzeTemplateToken(token, context);
  return analysis.kind === "valid" ? analysis.category : "unknown";
}

function analyzeTemplateToken(
  token: string,
  context: VariableClassificationContext
): TemplateTokenAnalysis {
  const deletedStepMatch = DELETED_STEP_TOKEN_PATTERN.exec(token);
  if (deletedStepMatch) {
    return {
      token,
      kind: "invalid",
      category: "unknown",
      reason: "deleted_step",
      stepOrder: Number(deletedStepMatch[1])
    };
  }

  const structuredMatch = STRUCTURED_OUTPUT_TOKEN_PATTERN.exec(token);
  if (structuredMatch) {
    const stepOrder = Number(structuredMatch[1]);
    const outputType = context.stepOutputTypes.get(stepOrder);
    if (stepOrder >= context.currentStepOrder || outputType === undefined) {
      return {
        token,
        kind: "invalid",
        category: "unknown",
        reason: "unavailable_step",
        stepOrder
      };
    }
    if (outputType !== "json") {
      return {
        token,
        kind: "invalid",
        category: "unknown",
        reason: "non_json_output",
        stepOrder
      };
    }
    return { token, kind: "valid", category: "structured" };
  }

  const stepReferenceMatch = STEP_REFERENCE_TOKEN_PATTERN.exec(token);
  if (stepReferenceMatch) {
    const stepOrder = Number(stepReferenceMatch[1]);
    if (stepOrder >= context.currentStepOrder || !context.stepOutputTypes.has(stepOrder)) {
      return {
        token,
        kind: "invalid",
        category: "unknown",
        reason: "unavailable_step",
        stepOrder
      };
    }
    return { token, kind: "valid", category: "step" };
  }

  const flowInputFieldName = token.startsWith("flow_input.")
    ? token.slice("flow_input.".length)
    : null;
  if (flowInputFieldName !== null) {
    if (context.knownFieldNames.has(flowInputFieldName)) {
      return { token, kind: "valid", category: "field" };
    }
    const flowInputRoot = flowInputFieldName.split(".", 1)[0]?.toLowerCase();
    if (flowInputRoot && REMOVED_FLOW_INPUT_TEMPLATE_KEYS.has(flowInputRoot)) {
      return { token, kind: "invalid", category: "unknown", reason: "unknown_variable" };
    }
    if (PRIMARY_FLOW_INPUT_KEYS.has(flowInputFieldName.toLowerCase())) {
      return { token, kind: "valid", category: "technical" };
    }
    // Multi-segment paths are JSON-shaped at runtime; the editor cannot lint them without a schema.
    if (flowInputFieldName.includes(".")) return { token, kind: "valid", category: "technical" };
    if (context.knownFieldNames.size > 0) {
      return { token, kind: "invalid", category: "unknown", reason: "unknown_variable" };
    }
    return { token, kind: "valid", category: "technical" };
  }

  if (SYSTEM_VARIABLE_NAMES.has(token)) return { token, kind: "valid", category: "system" };

  if (context.knownFieldNames.has(token) && isFlowFormFieldBareAliasSafe(token)) {
    return { token, kind: "valid", category: "field" };
  }

  for (const [order, name] of context.knownStepNames) {
    if (order < context.currentStepOrder && name === token) {
      return { token, kind: "valid", category: "step" };
    }
  }

  if (token.startsWith("flow.input.") || token.startsWith("step_input.")) {
    return { token, kind: "valid", category: "technical" };
  }

  return { token, kind: "invalid", category: "unknown", reason: "unknown_variable" };
}

export type PromptSegment =
  | { type: "text"; value: string }
  | { type: "variable"; value: string; token: string; category: VariableCategory };

export function parsePromptSegments(
  text: string,
  context: VariableClassificationContext
): PromptSegment[] {
  const segments: PromptSegment[] = [];
  const regex = new RegExp(TEMPLATE_TOKEN_PATTERN_SOURCE, "g");
  let lastIndex = 0;
  let match: RegExpExecArray | null = null;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ type: "text", value: text.slice(lastIndex, match.index) });
    }

    const token = match[1].trim();
    segments.push({
      type: "variable",
      value: `{{${token}}}`,
      token,
      category: classifyVariable(token, context)
    });

    lastIndex = regex.lastIndex;
  }

  if (lastIndex < text.length) {
    segments.push({ type: "text", value: text.slice(lastIndex) });
  }

  return segments;
}

export type TemplateValidationIssue = {
  token: string;
  reason: "unknown_variable" | "unavailable_step" | "deleted_step" | "non_json_output";
  stepOrder?: number;
};

export type TemplateTokenAnalysis =
  | {
      token: string;
      kind: "valid";
      category: Exclude<VariableCategory, "unknown">;
    }
  | {
      token: string;
      kind: "invalid";
      category: "unknown";
      reason: TemplateValidationIssue["reason"];
      stepOrder?: number;
    };

export function collectTemplateValidationIssues(
  text: string,
  context: VariableClassificationContext
): TemplateValidationIssue[] {
  return analyzeTemplateTokens(text, context)
    .filter(
      (analysis): analysis is Extract<TemplateTokenAnalysis, { kind: "invalid" }> =>
        analysis.kind === "invalid"
    )
    .map(({ token, reason, stepOrder }) => ({ token, reason, stepOrder }));
}

export function analyzeTemplateTokens(
  text: string,
  context: VariableClassificationContext
): TemplateTokenAnalysis[] {
  return extractTemplateTokens(text).map((token) => analyzeTemplateToken(token, context));
}
