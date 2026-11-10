import { stepName, templateParts } from "../flow-steps";
import { isJsonObject, objectOf, type FlowPublic, type StepConfig } from "./step-types";
import { formFieldsOf } from "./step-variables";

/**
 * What a step would send, as the reference editor's request preview reads it
 * (`flowStepRequestPreview.ts` in apps/web): its texts with every reference
 * named for what it reads, and what the answer must hold. Each reference is
 * judged as publish judges it, so the editor and the check agree with the
 * core. Pure and unit-tested.
 */

export type ReadMeaning =
  | { kind: "form_field"; label: string }
  | { kind: "flow_input" }
  | { kind: "upload" }
  | { kind: "transcription" }
  | { kind: "date" }
  /** The number of the section an instruction run once per section is on. */
  | { kind: "section_index" }
  /** The section's number in a text that is not an instruction run once per section: it is empty. */
  | { kind: "section_index_unavailable" }
  | { kind: "step_answer"; order: number }
  | { kind: "step_structured"; order: number }
  | { kind: "step_field"; order: number; field: string }
  /** The fields of an earlier step that answers in text or a document: it has none to read. */
  | { kind: "fields_of_text"; order: number }
  /** A value the run provides that the editor has no name for (`step_1.status`): shown as written. */
  | { kind: "run_value" }
  /** A step the flow has that has no result yet where it is read: this step (`self`) or a later one. */
  | { kind: "later"; order: number; self?: true }
  /** A step order the flow does not have; 0 for the step before the first. */
  | { kind: "no_step"; order: number }
  /** A step a change removed (`step_2_deleted`). */
  | { kind: "removed" }
  /** A name the flow does not declare, or a path its value does not have. */
  | { kind: "other"; token: string };

/** Where the text is: an AI instruction run once per section reads the section's number. */
export type TextPlace = { sectionIndex?: boolean };

/** `runtime_step_alias_order` in the core: `step_<n>`, no leading zero, ASCII digits. */
const STEP_ALIAS = /^step_(0|[1-9][0-9]*)$/;
const REMOVED_ALIAS = /^step_\d+_deleted$/;
/** A step result's own keys (`_STEP_RESULT_TAILS`) beside its text and fixed-format answer. */
const RESULT_VALUES = new Set(["output", "status", "error_message"]);
/** The run input's own keys (`PRIMARY_FLOW_INPUT_KEYS`). */
const FLOW_INPUT_KEYS = new Set([
  "file_ids",
  "json",
  "structured",
  "text",
  "transcribed_text",
  "transcription",
  "transcript",
  "transkribering"
]);
/** The keys of `step_input` and whether a path below them is an index (`STEP_INPUT_KEY_SHAPES`). */
const STEP_INPUT_KEYS: Record<string, "scalar" | "sequence"> = {
  text: "scalar",
  file_ids: "sequence",
  extracted_text_length: "scalar",
  input_format: "scalar"
};

/**
 * What one reference of the step at `stepOrder` reads, judged as publish
 * judges it: the core's `_analyze_expression` (a step by name, a runtime
 * variable, a step by `step_<n>`, a form field by its bare name, in that
 * order) and `_template_read_problem` (a path the value does not have, a step
 * without a result yet). `stepOrder` is where the text is read: the steps
 * before it have a result.
 */
export function readMeaning(
  token: string,
  stepOrder: number,
  flow: Pick<FlowPublic, "steps" | "metadata_json">,
  place: TextPlace = {}
): ReadMeaning {
  const dot = token.indexOf(".");
  const head = (dot < 0 ? token : token.slice(0, dot)).trim();
  const tail = dot < 0 ? "" : token.slice(dot + 1).trim();
  const other: ReadMeaning = { kind: "other", token };
  const steps = [...flow.steps].sort((a, b) => a.step_order - b.step_order);
  const fieldLabel = (name: string) =>
    formFieldsOf(flow).find((field) => field.name === name)?.label;
  const stepAt = (order: number): ReadMeaning | null => {
    if (!steps.some((step) => step.step_order === order)) return { kind: "no_step", order };
    if (order >= stepOrder) {
      return order === stepOrder ? { kind: "later", order, self: true } : { kind: "later", order };
    }
    return null;
  };

  const named = steps.find((step) => stepName(step) === head);
  if (named)
    return (
      stepAt(named.step_order) ?? (tail ? other : { kind: "step_answer", order: named.step_order })
    );

  switch (head) {
    case "datum":
      return tail ? other : { kind: "date" };
    case "transkribering":
      return tail ? other : { kind: "transcription" };
    case "indata_text":
      return tail ? other : { kind: "flow_input" };
    case "indata_json":
      return tail ? { kind: "run_value" } : { kind: "flow_input" };
    case "föregående_steg": {
      if (tail) return other;
      const order = stepOrder - 1;
      return order < 1
        ? { kind: "no_step", order: 0 }
        : (stepAt(order) ?? { kind: "step_answer", order });
    }
    case "section_index":
      if (tail) return other;
      return place.sectionIndex ? { kind: "section_index" } : { kind: "section_index_unavailable" };
    case "step_input": {
      const [key = "", ...rest] = tail ? tail.split(".") : [];
      const shape = STEP_INPUT_KEYS[key];
      if (!shape) return other;
      if (rest.length === 0) return key === "text" ? { kind: "upload" } : { kind: "run_value" };
      return shape === "sequence" && rest.length === 1 && /^[0-9]+$/.test(rest[0]!)
        ? { kind: "run_value" }
        : other;
    }
    case "flow_input":
    case "flow": {
      const input = head === "flow_input" ? tail : tail.startsWith("input.") ? tail.slice(6) : null;
      if (input === null) return tail === "input" ? { kind: "flow_input" } : { kind: "run_value" };
      if (!input) return { kind: "flow_input" };
      const key = input.split(".")[0]!.trim();
      const label = fieldLabel(key);
      if (label !== undefined) return { kind: "form_field", label };
      if (!FLOW_INPUT_KEYS.has(key)) return other;
      return key === "text" && input === "text" ? { kind: "flow_input" } : { kind: "run_value" };
    }
  }

  if (REMOVED_ALIAS.test(head)) return { kind: "removed" };
  const alias = STEP_ALIAS.exec(head);
  if (alias) {
    const order = Number(alias[1]);
    const unread = stepAt(order);
    if (unread) return unread;
    if (!tail || tail === "output.text") return { kind: "step_answer", order };
    if (RESULT_VALUES.has(tail)) return { kind: "run_value" };
    if (tail !== "output.structured" && !tail.startsWith("output.structured.")) return other;
    const path = tail === "output.structured" ? null : tail.slice("output.structured.".length);
    if (path !== null && path.split(".").some((segment) => !segment)) return other;
    const read = steps.find((candidate) => candidate.step_order === order);
    if (read && read.output_type !== "json") return { kind: "fields_of_text", order };
    return path ? { kind: "step_field", order, field: path } : { kind: "step_structured", order };
  }
  if (head.startsWith("step_")) return other;
  const label = fieldLabel(head);
  if (label !== undefined) return tail ? other : { kind: "form_field", label };
  return other;
}

export type PreviewPart =
  | { kind: "text"; text: string }
  | { kind: "read"; token: string; raw: string; meaning: ReadMeaning };

export function previewParts(
  text: string,
  stepOrder: number,
  flow: Pick<FlowPublic, "steps" | "metadata_json">,
  place: TextPlace = {}
): PreviewPart[] {
  return templateParts(text).map((part) =>
    part.kind === "text"
      ? part
      : { ...part, meaning: readMeaning(part.token, stepOrder, flow, place) }
  );
}

/**
 * How a reference fares: it reads what it names, it reads nothing useful
 * there (a warning: the run gives it an empty or unnamed value), or it names
 * a step the run cannot read.
 */
export function readTone(meaning: ReadMeaning): "reads" | "warning" | "missing" {
  switch (meaning.kind) {
    case "later":
    case "no_step":
    case "removed":
      return "missing";
    case "other":
    case "fields_of_text":
    case "section_index_unavailable":
      return "warning";
    default:
      return "reads";
  }
}

export type AnswerShape =
  | { kind: "free_text" }
  | { kind: "document"; format: "pdf" | "docx" }
  | { kind: "fields"; fields: { name: string; description: string | null }[] };

/** What the answer must hold: free text, a document, or the output contract's fields. */
export function answerShape(
  step: Pick<StepConfig, "output_type" | "output_contract">
): AnswerShape {
  if (step.output_type === "pdf" || step.output_type === "docx") {
    return { kind: "document", format: step.output_type };
  }
  if (step.output_type !== "json") return { kind: "free_text" };
  const properties = objectOf(objectOf(step.output_contract).properties);
  return {
    kind: "fields",
    fields: Object.entries(properties).map(([name, schema]) => {
      const description = isJsonObject(schema) ? schema.description : undefined;
      return {
        name,
        description:
          typeof description === "string" && description.trim() ? description.trim() : null
      };
    })
  };
}

/** The model settings the step sends, as stored: name and value, nothing unset. */
export function modelParameters(kwargs: Record<string, unknown> | null | undefined) {
  return Object.entries(kwargs ?? {})
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([name, value]) => ({
      name,
      value: typeof value === "string" ? value : JSON.stringify(value)
    }));
}
