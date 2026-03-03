const TEMPLATE_TOKEN_PATTERN = /\{\{\s*([^{}]+)\s*\}\}/g;
const STEP_ORDER_TOKEN_PATTERN = /^step_(\d+)(\..+)?$/;
const TECHNICAL_TOKEN_PATTERNS = [
  /^flow_input\./,
  /^flow\.input\./,
  /^step_\d+(\..+)?$/,
];

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

export function replaceExactTemplateToken(
  text: string,
  fromToken: string,
  toToken: string,
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
  deletedOrders: Set<number>,
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
    rewrittenDeletedReferences: [...rewrittenDeletedReferences],
  };
}

export function collectUnresolvedTemplateTokens(
  text: string,
  availableFriendlyTokens: Set<string>,
): string[] {
  const unresolved = new Set<string>();
  for (const token of extractTemplateTokens(text)) {
    if (availableFriendlyTokens.has(token)) continue;
    if (TECHNICAL_TOKEN_PATTERNS.some((pattern) => pattern.test(token))) continue;
    unresolved.add(token);
  }
  return [...unresolved];
}

// --- Unified Variable Color System ---

export type VariableCategory = "field" | "system" | "step" | "structured" | "technical" | "unknown";

export const VARIABLE_CATEGORY_CLASSES: Record<VariableCategory, { chip: string; text: string }> = {
  field:      { chip: "bg-blue-100 text-blue-700",     text: "text-blue-700" },
  system:     { chip: "bg-indigo-100 text-indigo-700",  text: "text-indigo-700" },
  step:       { chip: "bg-emerald-100 text-emerald-700", text: "text-emerald-700" },
  structured: { chip: "bg-purple-100 text-purple-700",  text: "text-purple-700" },
  technical:  { chip: "bg-sky-100 text-sky-700",        text: "text-sky-700" },
  unknown:    { chip: "bg-rose-100 text-rose-700",       text: "text-rose-700" },
};

export function getChipClasses(category: VariableCategory): string {
  return `rounded-md px-1.5 py-0.5 text-xs font-medium font-mono ${VARIABLE_CATEGORY_CLASSES[category].chip}`;
}

export type VariableClassificationContext = {
  knownFieldNames: Set<string>;
  knownStepNames: Map<number, string>;  // stepOrder -> user_description
  transcriptionEnabled: boolean;
  currentStepOrder: number;
};

export function classifyVariable(
  token: string,
  context: VariableClassificationContext,
): VariableCategory {
  // 1. Form field name match
  if (context.knownFieldNames.has(token)) return "field";

  // 2. System variables
  if (token === "transkribering" || token.startsWith("indata_")) return "system";
  if (token === "föregående_steg") return "system";

  // 3. Step name alias (matches a previous step's user_description)
  for (const [order, name] of context.knownStepNames) {
    if (order < context.currentStepOrder && name === token) return "step";
  }

  // 4. Structured step output (step_N.output.structured.*)
  const structuredMatch = /^step_(\d+)\.output\.structured\./.exec(token);
  if (structuredMatch) return "structured";

  // 5. Step output reference (step_N.output.* or step_N.*)
  const stepMatch = /^step_(\d+)(\.|$)/.exec(token);
  if (stepMatch) return "step";

  // 6. Technical flow_input references
  if (token.startsWith("flow_input.") || token.startsWith("flow.input.")) return "technical";

  // 7. Unknown
  return "unknown";
}

export type PromptSegment =
  | { type: "text"; value: string }
  | { type: "variable"; value: string; token: string; category: VariableCategory };

export function parsePromptSegments(
  text: string,
  context: VariableClassificationContext,
): PromptSegment[] {
  const segments: PromptSegment[] = [];
  const regex = /\{\{\s*([^{}]+?)\s*\}\}/g;
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
      category: classifyVariable(token, context),
    });

    lastIndex = regex.lastIndex;
  }

  if (lastIndex < text.length) {
    segments.push({ type: "text", value: text.slice(lastIndex) });
  }

  return segments;
}

