import { readTarget, templateParts } from "../flow-steps";
import { isJsonObject, objectOf, type FlowPublic, type StepConfig } from "./step-types";
import { formFieldsOf } from "./step-variables";

/**
 * What a step would send, as the reference editor's request preview reads it
 * (`flowStepRequestPreview.ts` in apps/web): its texts with every reference
 * named for what it reads, and what the answer must hold. References are
 * read with the step list's grammar (`readTarget` in `flow-steps.ts`). Pure
 * and unit-tested.
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
  /** A step the reference names that is removed, or not earlier: the run cannot read it. */
  | { kind: "missing"; order: number }
  /** A value the run provides that the editor has no name for. */
  | { kind: "other" };

/** Where the text is: an AI instruction run once per section reads the section's number. */
export type TextPlace = { sectionIndex?: boolean };

const STRUCTURED = /^step_\d+\.output\.structured(?:\.(.+))?$/;
const ANSWER = /^step_\d+\.output\.text$/;

export function readMeaning(
  token: string,
  stepOrder: number,
  flow: Pick<FlowPublic, "steps" | "metadata_json">,
  place: TextPlace = {}
): ReadMeaning {
  if (token === "step_input.text") return { kind: "upload" };
  if (token === "transkribering") return { kind: "transcription" };
  if (token === "datum") return { kind: "date" };
  if (token === "section_index") {
    return place.sectionIndex ? { kind: "section_index" } : { kind: "section_index_unavailable" };
  }
  // `indata_text` and `indata_json` are the run input's older names.
  if (["flow_input", "flow_input.text", "indata_text", "indata_json"].includes(token)) {
    return { kind: "flow_input" };
  }
  if (token.startsWith("flow_input.")) {
    const name = token.slice("flow_input.".length);
    const field = formFieldsOf(flow).find((candidate) => candidate.name === name);
    return field ? { kind: "form_field", label: field.label } : { kind: "other" };
  }
  const target = readTarget(token, { step_order: stepOrder }, flow.steps);
  switch (target.kind) {
    case "deleted":
    case "not_earlier":
      return { kind: "missing", order: target.order };
    case "flow_input":
      return { kind: "other" };
    case "step": {
      if (target.via !== "alias") return { kind: "step_answer", order: target.order };
      const structured = STRUCTURED.exec(token);
      if (structured) {
        const read = flow.steps.find((candidate) => candidate.step_order === target.order);
        if (read && read.output_type !== "json") {
          return { kind: "fields_of_text", order: target.order };
        }
        return structured[1]
          ? { kind: "step_field", order: target.order, field: structured[1] }
          : { kind: "step_structured", order: target.order };
      }
      return ANSWER.test(token) || /^step_\d+$/.test(token)
        ? { kind: "step_answer", order: target.order }
        : { kind: "other" };
    }
  }
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
    case "missing":
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
