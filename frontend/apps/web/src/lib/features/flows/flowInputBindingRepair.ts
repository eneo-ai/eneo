import type { FlowStep } from "@eneo/eneo-js";
import {
  DELETED_STEP_REF_PATTERN,
  getFlowInputMaterialOptions,
  parseFlowInputBindings,
  setInputBindingQuestion,
  setInputBindingSourceRefs,
  type FlowInputMaterialOption
} from "./flowInputBindings";

import { extractTemplateTokens, replaceExactTemplateToken } from "./flowVariableTokens";

export type DanglingBindingReference = {
  location: { kind: "question" } | { kind: "source_ref"; index: number };
  token: string;
};

export function findDanglingBindingReferences(
  step: FlowStep,
  issue: { code: string; field?: string | null; reference?: string | null }
): DanglingBindingReference[] {
  const state = parseFlowInputBindings(step.input_bindings);
  if (state.status === "invalid") return [];
  if (issue.field && issue.reference) {
    if (issue.field === "input_bindings.question") {
      return [{ location: { kind: "question" }, token: issue.reference }];
    }
    const match = /^input_bindings\.source_refs\[(\d+)\]\.step_ref$/.exec(issue.field);
    if (match && state.sourceRefs[Number(match[1])]) {
      return [
        { location: { kind: "source_ref", index: Number(match[1]) }, token: issue.reference }
      ];
    }
  }
  if (issue.code !== "deleted-step-reference" || issue.field || issue.reference) return [];
  const targets: DanglingBindingReference[] = extractTemplateTokens(state.question ?? "")
    .filter((token) => DELETED_STEP_REF_PATTERN.test(token.split(".")[0]))
    .map((token) => ({ location: { kind: "question" }, token }));
  state.sourceRefs.forEach((ref, index) => {
    if (DELETED_STEP_REF_PATTERN.test(ref.stepRef)) {
      targets.push({ location: { kind: "source_ref", index }, token: ref.stepRef });
    }
  });
  return targets;
}

export function replacementToken(option: FlowInputMaterialOption): string {
  if (option.output === "text") return option.stepRef;
  return `${option.stepRef}.output.structured${option.fieldPath ? `.${option.fieldPath}` : ""}`;
}

export function replaceBindingReference(
  step: FlowStep,
  target: DanglingBindingReference,
  option: FlowInputMaterialOption
): Record<string, unknown> | null {
  const state = parseFlowInputBindings(step.input_bindings);
  if (state.status === "invalid") return null;
  if (target.location.kind === "question") {
    const question = step.input_bindings?.question;
    if (typeof question !== "string" || !extractTemplateTokens(question).includes(target.token))
      return null;
    const repairedQuestion = replaceExactTemplateToken(
      question,
      target.token,
      replacementToken(option)
    );
    const result = setInputBindingQuestion(step.input_bindings, repairedQuestion);
    if (result.status === "blocked" || !result.inputBindings) return null;
    return { ...step.input_bindings, question: repairedQuestion };
  }
  const index = target.location.index;
  const ref = state.sourceRefs[index];
  if (!ref || ref.stepRef !== target.token) return null;
  const sourceRefs = [...state.sourceRefs];
  sourceRefs[index] = {
    stepRef: option.stepRef,
    output: option.output,
    fieldPath: option.fieldPath,
    label: ref.label,
    // Array fields are never offered for a source ref (they need an item
    // template the picker cannot author), so no template survives a repair.
    itemTemplate: null
  };
  const result = setInputBindingSourceRefs(step.input_bindings, sourceRefs);
  if (result.status === "blocked" || !result.inputBindings) return null;
  const repairedRefs = result.inputBindings.source_refs as unknown[];
  const originalRefs = step.input_bindings?.source_refs as unknown[];
  return {
    ...step.input_bindings,
    source_refs: originalRefs.map((original, refIndex) =>
      refIndex === index ? repairedRefs[index] : original
    )
  };
}

export function repairOptionsFor(
  step: FlowStep,
  steps: FlowStep[],
  target: DanglingBindingReference
): FlowInputMaterialOption[] {
  const state = parseFlowInputBindings(step.input_bindings);
  if (state.status === "invalid") return [];
  const options = getFlowInputMaterialOptions(step.step_order, steps).filter(
    (option) => option.output === "text" || option.fieldPath !== null
  );
  if (target.location.kind !== "source_ref") return options;
  const ref = state.sourceRefs[target.location.index];
  if (!ref || ref.itemTemplate !== null || step.input_contract != null) return [];
  // A structured array as a source ref needs an item template the picker
  // cannot author; the backend refuses it without one. A field whose type
  // the options owner could not name (absent, or a JSON Schema type list
  // such as ["array", "null"]) may be one, so only fields with a known
  // non-array scalar type are offered.
  return options.filter(
    (option) =>
      option.output === "text" || (option.schemaType !== null && option.schemaType !== "array")
  );
}
