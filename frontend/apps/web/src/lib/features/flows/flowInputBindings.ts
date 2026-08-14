import type { FlowStep } from "@eneo/eneo-js";

const SOURCE_REFS_BINDING_KEY = "source_refs";
const SUPPORTED_INPUT_BINDING_KEYS = new Set(["question", SOURCE_REFS_BINDING_KEY]);
const SUPPORTED_SOURCE_REF_KEYS = new Set([
  "step_ref",
  "output",
  "field_path",
  "label",
  "item_template"
]);
const STEP_REF_PATTERN = /^step_(\d+)$/;
const DELETED_STEP_REF_PATTERN = /^step_(\d+)_deleted$/;

export type FlowInputBindingSourceRef = {
  stepRef: string;
  output: "text" | "structured";
  fieldPath: string | null;
  label: string | null;
  itemTemplate: string | null;
};

export type FlowInputBindingsState =
  | {
      status: "valid";
      question: string | null;
      sourceRefs: FlowInputBindingSourceRef[];
      hasAdvancedSourceRefs: boolean;
    }
  | {
      status: "invalid";
      question: null;
      sourceRefs: [];
      hasAdvancedSourceRefs: false;
    };

export type InputBindingsUpdateResult =
  { status: "updated"; inputBindings: Record<string, unknown> | null } | { status: "blocked" };

export type FlowInputMaterialOption = {
  key: string;
  stepRef: string;
  sourceStepOrder: number;
  sourceStepName: string | null;
  output: "text" | "structured";
  fieldPath: string | null;
  schemaType: string | null;
  description: string | null;
};

export type FlowStepEffectiveInputSource =
  | {
      kind: "custom_question";
    }
  | {
      kind: "source_ref";
      stepRef: string;
      sourceStepOrder: number | null;
      sourceStepName: string | null;
      output: "text" | "structured";
      fieldPath: string | null;
      label: string | null;
      itemTemplate: string | null;
    }
  | {
      kind: "deleted_source";
      stepRef: string;
      deletedStepOrder: number;
      output: "text" | "structured";
      fieldPath: string | null;
      label: string | null;
      itemTemplate: string | null;
    }
  | {
      kind: "implicit_previous_step";
      sourceStepOrder: number;
      sourceStepName: string | null;
    }
  | {
      kind: "implicit_all_previous_steps";
      sourceSteps: Array<{ stepOrder: number; stepName: string | null }>;
    };

export type InputBindingSourceRefRemapResult = {
  inputBindings: Record<string, unknown> | null;
  changed: boolean;
  rewrittenDeletedReferences: number[];
};

export function getInputBindingQuestion(inputBindings: unknown): string {
  const state = parseFlowInputBindings(inputBindings);
  return state.status === "valid" ? (state.question ?? "") : "";
}

export function getInputBindingSourceRefs(inputBindings: unknown): FlowInputBindingSourceRef[] {
  const state = parseFlowInputBindings(inputBindings);
  return state.status === "valid" ? state.sourceRefs : [];
}

export function parseFlowInputBindings(inputBindings: unknown): FlowInputBindingsState {
  if (inputBindings === null || inputBindings === undefined) {
    return validInputBindings(null, []);
  }
  if (!isRecord(inputBindings)) return invalidInputBindings();
  if (Object.keys(inputBindings).some((key) => !SUPPORTED_INPUT_BINDING_KEYS.has(key))) {
    return invalidInputBindings();
  }

  const rawQuestion = inputBindings.question;
  if (rawQuestion !== undefined && rawQuestion !== null && typeof rawQuestion !== "string") {
    return invalidInputBindings();
  }
  const question = typeof rawQuestion === "string" ? stringValue(rawQuestion) : null;

  const rawRefs = inputBindings[SOURCE_REFS_BINDING_KEY];
  if (rawRefs === undefined) return validInputBindings(question, []);
  if (!Array.isArray(rawRefs)) return invalidInputBindings();

  const sourceRefs: FlowInputBindingSourceRef[] = [];
  for (const rawRef of rawRefs) {
    const parsedRef = parseSourceRef(rawRef);
    if (!parsedRef) return invalidInputBindings();
    sourceRefs.push(parsedRef);
  }
  return validInputBindings(question, sourceRefs);
}

export function setInputBindingSourceRefs(
  inputBindings: unknown,
  sourceRefs: FlowInputBindingSourceRef[]
): InputBindingsUpdateResult {
  const state = parseFlowInputBindings(inputBindings);
  if (state.status === "invalid") return { status: "blocked" };

  return updatedInputBindings(state.question, sourceRefs);
}

export function setInputBindingQuestion(
  inputBindings: unknown,
  question: string
): InputBindingsUpdateResult {
  const state = parseFlowInputBindings(inputBindings);
  if (state.status === "invalid") return { status: "blocked" };

  return updatedInputBindings(stringValue(question), state.sourceRefs);
}

export function hasInputBindingSourceRefs(inputBindings: unknown): boolean {
  return getInputBindingSourceRefs(inputBindings).length > 0;
}

export function hasDeletedInputBindingSourceRefs(inputBindings: unknown): boolean {
  const bindings = rawInputBindingRecord(inputBindings);
  const rawRefs = bindings?.[SOURCE_REFS_BINDING_KEY];
  if (!Array.isArray(rawRefs)) return false;
  return rawRefs.some(
    (rawRef) =>
      isRecord(rawRef) &&
      typeof rawRef.step_ref === "string" &&
      getDeletedStepOrderFromStepRef(rawRef.step_ref) !== null
  );
}

export function canClearInputBindingSourceRefs(step: FlowStep): boolean {
  const state = parseFlowInputBindings(step.input_bindings);
  return (
    state.status === "valid" &&
    step.input_type === "text" &&
    step.input_contract == null &&
    !state.hasAdvancedSourceRefs
  );
}

export function getFlowInputMaterialOptions(
  currentStepOrder: number,
  steps: FlowStep[]
): FlowInputMaterialOption[] {
  const options: FlowInputMaterialOption[] = [];
  const previousSteps = [...steps]
    .filter((step) => step.step_order < currentStepOrder)
    .sort((left, right) => left.step_order - right.step_order);

  for (const step of previousSteps) {
    const stepRef = `step_${step.step_order}`;
    const sourceStepName = stringValue(step.user_description);
    const output = step.output_type === "json" ? "structured" : "text";
    if (output === "structured" && !isRecord(step.output_contract)) continue;
    options.push({
      key: `${stepRef}:${output}:*`,
      stepRef,
      sourceStepOrder: step.step_order,
      sourceStepName,
      output,
      fieldPath: null,
      schemaType: null,
      description: null
    });
    if (output !== "structured") continue;

    for (const [fieldPath, schema] of outputContractProperties(step.output_contract)) {
      options.push({
        key: `${stepRef}:structured:${fieldPath}`,
        stepRef,
        sourceStepOrder: step.step_order,
        sourceStepName,
        output: "structured",
        fieldPath,
        schemaType: isRecord(schema) ? stringValue(schema.type) : null,
        description: isRecord(schema) ? stringValue(schema.description) : null
      });
    }
  }
  return options;
}

export function getFlowStepEffectiveInputSources(
  step: FlowStep,
  steps: FlowStep[]
): FlowStepEffectiveInputSource[] {
  const inputBindingsState = parseFlowInputBindings(step.input_bindings);
  if (inputBindingsState.status === "invalid") return [];

  const explicitSources: FlowStepEffectiveInputSource[] = [];
  if (inputBindingsState.question?.trim()) {
    explicitSources.push({ kind: "custom_question" });
  }

  const sourceRefs = inputBindingsState.sourceRefs;
  if (sourceRefs.length > 0) {
    explicitSources.push(
      ...sourceRefs.map((ref): FlowStepEffectiveInputSource => {
        const deletedStepOrder = getDeletedStepOrderFromStepRef(ref.stepRef);
        if (deletedStepOrder !== null) {
          return {
            kind: "deleted_source",
            stepRef: ref.stepRef,
            deletedStepOrder,
            output: ref.output,
            fieldPath: ref.fieldPath,
            label: ref.label,
            itemTemplate: ref.itemTemplate
          };
        }
        const sourceStepOrder = getStepOrderFromStepRef(ref.stepRef);
        const sourceStep =
          sourceStepOrder === null
            ? null
            : steps.find((candidate) => candidate.step_order === sourceStepOrder);
        return {
          kind: "source_ref",
          stepRef: ref.stepRef,
          sourceStepOrder,
          sourceStepName: sourceStep?.user_description ?? null,
          output: ref.output,
          fieldPath: ref.fieldPath,
          label: ref.label,
          itemTemplate: ref.itemTemplate
        };
      })
    );
  }

  if (explicitSources.length > 0) {
    return explicitSources;
  }

  if (step.input_source === "previous_step" && step.step_order > 1) {
    const previousStep = steps.find((candidate) => candidate.step_order === step.step_order - 1);
    if (previousStep) {
      return [
        {
          kind: "implicit_previous_step",
          sourceStepOrder: previousStep.step_order,
          sourceStepName: previousStep.user_description ?? null
        }
      ];
    }
  }

  if (step.input_source === "all_previous_steps" && step.step_order > 1) {
    const previousSteps = [...steps]
      .filter((candidate) => candidate.step_order < step.step_order)
      .sort((left, right) => left.step_order - right.step_order)
      .map((candidate) => ({
        stepOrder: candidate.step_order,
        stepName: candidate.user_description ?? null
      }));
    if (previousSteps.length > 0) {
      return [{ kind: "implicit_all_previous_steps", sourceSteps: previousSteps }];
    }
  }

  return [];
}

export function remapInputBindingSourceRefs(
  inputBindings: unknown,
  remapByOldOrder: Map<number, number>,
  deletedOrders: Set<number>
): InputBindingSourceRefRemapResult {
  const bindings = rawInputBindingRecord(inputBindings);
  const rawRefs = bindings?.[SOURCE_REFS_BINDING_KEY];
  if (!bindings || !Array.isArray(rawRefs)) {
    return { inputBindings: bindings, changed: false, rewrittenDeletedReferences: [] };
  }

  let changed = false;
  const rewrittenDeletedReferences = new Set<number>();
  const rewrittenRefs = rawRefs.map((rawRef) => {
    if (!isRecord(rawRef) || typeof rawRef.step_ref !== "string") return rawRef;
    const oldOrder = getStepOrderFromStepRef(rawRef.step_ref);
    if (oldOrder === null) return rawRef;

    if (deletedOrders.has(oldOrder)) {
      changed = true;
      rewrittenDeletedReferences.add(oldOrder);
      return { ...rawRef, step_ref: `step_${oldOrder}_deleted` };
    }

    const newOrder = remapByOldOrder.get(oldOrder);
    if (newOrder === undefined || newOrder === oldOrder) return rawRef;

    changed = true;
    return { ...rawRef, step_ref: `step_${newOrder}` };
  });

  if (!changed) {
    return { inputBindings: bindings, changed: false, rewrittenDeletedReferences: [] };
  }

  return {
    inputBindings: { ...bindings, [SOURCE_REFS_BINDING_KEY]: rewrittenRefs },
    changed: true,
    rewrittenDeletedReferences: [...rewrittenDeletedReferences]
  };
}

function getStepOrderFromStepRef(stepRef: string): number | null {
  const match = STEP_REF_PATTERN.exec(stepRef);
  if (!match) return null;
  return Number(match[1]);
}

function getDeletedStepOrderFromStepRef(stepRef: string): number | null {
  const match = DELETED_STEP_REF_PATTERN.exec(stepRef);
  if (!match) return null;
  return Number(match[1]);
}

function rawInputBindingRecord(inputBindings: unknown): Record<string, unknown> | null {
  return isRecord(inputBindings) ? inputBindings : null;
}

function validInputBindings(
  question: string | null,
  sourceRefs: FlowInputBindingSourceRef[]
): FlowInputBindingsState {
  return {
    status: "valid",
    question,
    sourceRefs,
    hasAdvancedSourceRefs: sourceRefs.some((ref) => ref.itemTemplate !== null)
  };
}

function invalidInputBindings(): FlowInputBindingsState {
  return {
    status: "invalid",
    question: null,
    sourceRefs: [],
    hasAdvancedSourceRefs: false
  };
}

function parseSourceRef(value: unknown): FlowInputBindingSourceRef | null {
  if (!isRecord(value)) return null;
  if (Object.keys(value).some((key) => !SUPPORTED_SOURCE_REF_KEYS.has(key))) return null;

  const stepRef = stringValue(value.step_ref);
  const output = value.output;
  if (!stepRef || (output !== "text" && output !== "structured")) return null;

  const fieldPath = optionalStringValue(value.field_path);
  const label = optionalStringValue(value.label);
  const itemTemplate = optionalStringValue(value.item_template);
  if (fieldPath === undefined || label === undefined || itemTemplate === undefined) return null;
  if (output === "text" && fieldPath !== null) return null;
  if (
    fieldPath !== null &&
    (fieldPath.includes("{{") ||
      fieldPath.includes("}}") ||
      fieldPath.split(".").some((part) => part.trim().length === 0))
  ) {
    return null;
  }
  if (label?.includes("{{") || label?.includes("}}")) return null;

  return { stepRef, output, fieldPath, label, itemTemplate };
}

function serializeSourceRef(ref: FlowInputBindingSourceRef): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    step_ref: ref.stepRef,
    output: ref.output
  };
  if (ref.fieldPath) payload.field_path = ref.fieldPath;
  if (ref.label) payload.label = ref.label;
  if (ref.itemTemplate) payload.item_template = ref.itemTemplate;
  return payload;
}

function updatedInputBindings(
  question: string | null,
  sourceRefs: FlowInputBindingSourceRef[]
): InputBindingsUpdateResult {
  const nextBindings: Record<string, unknown> = {};
  if (question) nextBindings.question = question;
  if (sourceRefs.length > 0) {
    nextBindings[SOURCE_REFS_BINDING_KEY] = sourceRefs.map(serializeSourceRef);
  }
  return {
    status: "updated",
    inputBindings: Object.keys(nextBindings).length > 0 ? nextBindings : null
  };
}

function outputContractProperties(contract: unknown): [string, unknown][] {
  if (!isRecord(contract) || !isRecord(contract.properties)) return [];
  return Object.entries(contract.properties);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : null;
}

function optionalStringValue(value: unknown): string | null | undefined {
  if (value === undefined || value === null) return null;
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : undefined;
}
