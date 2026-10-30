import { readTarget, templateParts, tokensOf } from "../flow-steps";
import { readInputBindings, writeInputBindings, type SourceRef } from "./step-configs";
import type { FlowPublic, FlowStep, JsonObject } from "./step-types";
import { materialOptions, type MaterialOption } from "./step-variables";

/**
 * The one-click repair of a step's underlag that still reads a step a change
 * removed (the core marks such a read `step_2_deleted`): what can replace it
 * and the bindings with the replacement in place. The reference editor's
 * repair (`flowInputBindingRepair.ts` in apps/web) is the spec; reads are
 * recognised with the step list's grammar (`readTarget`). Pure and
 * unit-tested.
 */

/** A read of a removed step: in the underlag's text, or one of its chosen results. */
export type RemovedRead =
  | { location: "question"; token: string }
  | { location: "source_ref"; index: number; token: string };

export function removedReads(step: FlowStep, steps: readonly FlowStep[]): RemovedRead[] {
  const bindings = readInputBindings(step.input_bindings);
  if (bindings.status !== "valid") return [];
  const removed = (token: string) => readTarget(token, step, steps).kind === "deleted";
  const reads: RemovedRead[] = [...new Set(tokensOf(bindings.question))]
    .filter(removed)
    .map((token) => ({ location: "question", token }));
  bindings.sourceRefs.forEach((ref, index) => {
    if (removed(ref.stepRef)) reads.push({ location: "source_ref", index, token: ref.stepRef });
  });
  return reads;
}

function sourceRefAt(step: FlowStep, read: RemovedRead): SourceRef | null {
  const bindings = readInputBindings(step.input_bindings);
  if (bindings.status !== "valid" || read.location !== "source_ref") return null;
  const ref = bindings.sourceRefs[read.index];
  return ref && ref.stepRef === read.token ? ref : null;
}

/**
 * What can take the removed read's place: an earlier step's answer or one of
 * its declared fields. A chosen result takes no array field (it would need an
 * item template, which the repair cannot write), and a result with an item
 * template, or a step with an input contract, is left to the step editor.
 */
export function repairOptions(
  flow: Pick<FlowPublic, "steps">,
  step: FlowStep,
  read: RemovedRead
): MaterialOption[] {
  const options = materialOptions(flow, step.step_order).filter(
    (option) => option.output === "text" || option.fieldPath !== null
  );
  if (read.location === "question") return options;
  const ref = sourceRefAt(step, read);
  if (!ref || (ref.raw.item_template ?? null) !== null || step.input_contract != null) return [];
  return options.filter(
    (option) =>
      option.output === "text" || (option.fieldType !== null && option.fieldType !== "array")
  );
}

/** The reference the option is read by (`step_2.output.text`, `step_2.output.structured.x`). */
export function optionToken(option: MaterialOption): string {
  const base = `step_${option.stepOrder}.output`;
  if (option.output === "text") return `${base}.text`;
  return option.fieldPath ? `${base}.structured.${option.fieldPath}` : `${base}.structured`;
}

/** The step's bindings with the removed read replaced by the option, or null when it is gone. */
export function repairedBindings(
  step: FlowStep,
  read: RemovedRead,
  option: MaterialOption
): JsonObject | null {
  const bindings = readInputBindings(step.input_bindings);
  if (bindings.status !== "valid") return null;
  if (read.location === "question") {
    const parts = templateParts(bindings.question);
    if (!parts.some((part) => part.kind === "read" && part.token === read.token)) return null;
    const question = parts
      .map((part) =>
        part.kind === "text"
          ? part.text
          : part.token === read.token
            ? `{{${optionToken(option)}}}`
            : part.raw
      )
      .join("");
    return writeInputBindings(question, bindings.sourceRefs);
  }
  const ref = sourceRefAt(step, read);
  if (!ref) return null;
  const raw: JsonObject = {
    ...ref.raw,
    step_ref: `step_${option.stepOrder}`,
    output: option.output
  };
  delete raw.item_template;
  if (option.fieldPath) raw.field_path = option.fieldPath;
  else delete raw.field_path;
  const sourceRefs = bindings.sourceRefs.map((candidate, index) =>
    index === read.index
      ? {
          stepRef: `step_${option.stepOrder}`,
          output: option.output,
          fieldPath: option.fieldPath,
          raw
        }
      : candidate
  );
  return writeInputBindings(bindings.question, sourceRefs);
}
