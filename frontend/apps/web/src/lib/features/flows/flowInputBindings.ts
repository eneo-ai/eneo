import type { FlowStep } from "@eneo/eneo-js";

const SOURCE_REFS_BINDING_KEY = "source_refs";
const STEP_REF_PATTERN = /^step_(\d+)$/;
const DELETED_STEP_REF_PATTERN = /^step_(\d+)_deleted$/;

export type FlowInputBindingSourceRef = {
  stepRef: string;
  output: "text" | "structured";
  fieldPath: string | null;
  label: string | null;
};

export type FlowStepEffectiveInputSource =
  | {
      kind: "source_ref";
      stepRef: string;
      sourceStepOrder: number | null;
      sourceStepName: string | null;
      output: "text" | "structured";
      fieldPath: string | null;
      label: string | null;
    }
  | {
      kind: "deleted_source";
      stepRef: string;
      deletedStepOrder: number;
      output: "text" | "structured";
      fieldPath: string | null;
      label: string | null;
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
  const bindings = inputBindingRecord(inputBindings);
  const question = bindings?.question;
  return typeof question === "string" ? question : "";
}

export function getInputBindingSourceRefs(inputBindings: unknown): FlowInputBindingSourceRef[] {
  const bindings = inputBindingRecord(inputBindings);
  const rawRefs = bindings?.[SOURCE_REFS_BINDING_KEY];
  if (!Array.isArray(rawRefs)) return [];

  const refs: FlowInputBindingSourceRef[] = [];
  for (const rawRef of rawRefs) {
    if (!isRecord(rawRef)) continue;
    const stepRef = stringValue(rawRef.step_ref);
    const output = rawRef.output;
    if (!stepRef || (output !== "text" && output !== "structured")) continue;
    refs.push({
      stepRef,
      output,
      fieldPath: stringValue(rawRef.field_path),
      label: stringValue(rawRef.label)
    });
  }
  return refs;
}

export function hasInputBindingSourceRefs(inputBindings: unknown): boolean {
  return getInputBindingSourceRefs(inputBindings).length > 0;
}

export function hasDeletedInputBindingSourceRefs(inputBindings: unknown): boolean {
  const bindings = inputBindingRecord(inputBindings);
  const rawRefs = bindings?.[SOURCE_REFS_BINDING_KEY];
  if (!Array.isArray(rawRefs)) return false;
  return rawRefs.some(
    (rawRef) =>
      isRecord(rawRef) &&
      typeof rawRef.step_ref === "string" &&
      getDeletedStepOrderFromStepRef(rawRef.step_ref) !== null
  );
}

export function getFlowStepEffectiveInputSources(
  step: FlowStep,
  steps: FlowStep[]
): FlowStepEffectiveInputSource[] {
  const sourceRefs = getInputBindingSourceRefs(step.input_bindings);
  if (sourceRefs.length > 0) {
    return sourceRefs.map((ref) => {
      const deletedStepOrder = getDeletedStepOrderFromStepRef(ref.stepRef);
      if (deletedStepOrder !== null) {
        return {
          kind: "deleted_source",
          stepRef: ref.stepRef,
          deletedStepOrder,
          output: ref.output,
          fieldPath: ref.fieldPath,
          label: ref.label
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
        label: ref.label
      };
    });
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
  const bindings = inputBindingRecord(inputBindings);
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

function inputBindingRecord(inputBindings: unknown): Record<string, unknown> | null {
  return isRecord(inputBindings) ? inputBindings : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : null;
}
