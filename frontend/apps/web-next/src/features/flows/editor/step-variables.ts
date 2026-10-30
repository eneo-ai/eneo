import { readRuntimeInput } from "./step-configs";
import { transcriptionEnabled } from "./step-draft";
import { isJsonObject, objectOf, type FlowPublic, type FlowStep } from "./step-types";

/**
 * What a step can read from the run: the run form's fields, values the run
 * provides, and what earlier steps answered. References are written the way
 * the core resolves them (`{{step_2.output.text}}`); the core renumbers
 * `step_N` references when steps move, so the editor offers them rather than
 * step names.
 */

export type FormField = { name: string; label: string; type: string };

const FORM_FIELD_NAMESPACE_HEADS = new Set(["flow", "flow_input", "step_input"]);
const RESERVED_FORM_FIELD_KEYS = new Set([
  "expected_flow_version",
  "file_ids",
  "json",
  "max_speakers",
  "speaker_labels",
  "step_inputs",
  "structured",
  "text",
  "transcribed_text",
  "transcript",
  "transcript_regeneration",
  "transcription",
  "transkribering"
]);

/** The run form's fields (`metadata_json.form_schema.fields`), in their order. */
export function formFieldsOf(flow: Pick<FlowPublic, "metadata_json">): FormField[] {
  const fields = objectOf(objectOf(flow.metadata_json).form_schema).fields;
  if (!Array.isArray(fields)) return [];
  return fields.flatMap((field) => {
    if (!isJsonObject(field) || typeof field.name !== "string" || !field.name.trim()) return [];
    const name = field.name.trim();
    const label = typeof field.label === "string" && field.label.trim() ? field.label.trim() : name;
    return [{ name, label, type: typeof field.type === "string" ? field.type : "text" }];
  });
}

/** Whether a form field's name can be read as `{{flow_input.<name>}}`. */
export function formFieldIsReadable(name: string): boolean {
  const key = name.trim().toLowerCase();
  return (
    key.length > 0 &&
    !FORM_FIELD_NAMESPACE_HEADS.has(key) &&
    !RESERVED_FORM_FIELD_KEYS.has(key) &&
    !/^step_\d+($|[._])/i.test(name.trim()) &&
    !name.includes(".")
  );
}

/** A property name one segment of a reference path can reach (`step_2.output.structured.<name>`). */
export function isVariablePathSegment(name: string): boolean {
  return name.length > 0 && name.trim() === name && !/[.{}]/.test(name);
}

export function contractFields(contract: unknown): { name: string; type: string | null }[] {
  const properties = objectOf(objectOf(contract).properties);
  return Object.entries(properties)
    .filter(([name]) => isVariablePathSegment(name))
    .map(([name, schema]) => {
      const { type } = objectOf(schema);
      const first = Array.isArray(type) ? type.find((item) => item !== "null") : type;
      return { name, type: typeof first === "string" ? first : null };
    });
}

export type VariableEntry = {
  token: string;
  /** What the entry is: a form field's label, or a kind of value. */
  kind:
    | { type: "field"; label: string }
    | { type: "upload" }
    | { type: "transcription" }
    | { type: "date" }
    | { type: "section_index" }
    | { type: "previous_step" }
    | { type: "step_text" }
    | { type: "step_structured" }
    | { type: "step_field"; field: string };
};

export type VariableGroup =
  | { type: "fields"; entries: VariableEntry[] }
  | { type: "run"; entries: VariableEntry[] }
  | { type: "step"; stepOrder: number; stepName: string; entries: VariableEntry[] };

export function stepsBefore(flow: Pick<FlowPublic, "steps">, stepOrder: number): FlowStep[] {
  return [...flow.steps]
    .filter((step) => step.step_order < stepOrder)
    .sort((left, right) => left.step_order - right.step_order);
}

/**
 * The references a step at `stepOrder` can insert. `wholeValue` is for a tool
 * argument, which takes one whole value: a whole structured answer only when
 * the earlier step declares its fields.
 */
export function variableGroups(params: {
  flow: Pick<FlowPublic, "steps" | "metadata_json">;
  stepOrder: number;
  inputConfig?: unknown;
  wholeValue?: boolean;
  /** The text is an AI instruction run once per section: it can read the section's number. */
  sectionVariables?: boolean;
}): VariableGroup[] {
  const { flow, stepOrder, inputConfig, wholeValue = false, sectionVariables = false } = params;
  const groups: VariableGroup[] = [];

  const fields = formFieldsOf(flow)
    .filter((field) => formFieldIsReadable(field.name))
    .map((field): VariableEntry => ({
      token: `flow_input.${field.name}`,
      kind: { type: "field", label: field.label }
    }));
  if (fields.length > 0) groups.push({ type: "fields", entries: fields });

  const run: VariableEntry[] = [];
  if (readRuntimeInput(inputConfig).enabled) {
    run.push({ token: "step_input.text", kind: { type: "upload" } });
  }
  const audio = flow.steps.some(
    (step) =>
      (step.input_source === "flow_input" && step.input_type === "audio") ||
      (readRuntimeInput(step.input_config).enabled &&
        readRuntimeInput(step.input_config).inputFormat === "audio")
  );
  if (audio && transcriptionEnabled(flow.metadata_json)) {
    run.push({ token: "transkribering", kind: { type: "transcription" } });
  }
  if (!wholeValue) run.push({ token: "datum", kind: { type: "date" } });
  if (sectionVariables) run.push({ token: "section_index", kind: { type: "section_index" } });
  if (stepOrder > 1 && !wholeValue) {
    run.push({ token: "föregående_steg", kind: { type: "previous_step" } });
  }
  if (run.length > 0) groups.push({ type: "run", entries: run });

  for (const step of stepsBefore(flow, stepOrder)) {
    const order = step.step_order;
    const entries: VariableEntry[] = [
      { token: `step_${order}.output.text`, kind: { type: "step_text" } }
    ];
    if (step.output_type === "json") {
      const declared = contractFields(step.output_contract);
      if (!wholeValue || isJsonObject(step.output_contract)) {
        entries.push({
          token: `step_${order}.output.structured`,
          kind: { type: "step_structured" }
        });
      }
      for (const field of declared) {
        entries.push({
          token: `step_${order}.output.structured.${field.name}`,
          kind: { type: "step_field", field: field.name }
        });
      }
    }
    groups.push({
      type: "step",
      stepOrder: order,
      stepName: step.user_description?.trim() ?? "",
      entries
    });
  }
  return groups;
}

export type MaterialOption = {
  key: string;
  stepOrder: number;
  stepName: string;
  output: "text" | "structured";
  fieldPath: string | null;
  /** A declared field's JSON Schema type, when it names one. */
  fieldType: string | null;
};

/**
 * The earlier results a step can choose as its underlag (`source_refs`): each
 * earlier step's answer, and each declared field of a structured answer. A
 * structured answer without declared fields has nothing to choose.
 */
export function materialOptions(
  flow: Pick<FlowPublic, "steps">,
  stepOrder: number
): MaterialOption[] {
  const options: MaterialOption[] = [];
  for (const step of stepsBefore(flow, stepOrder)) {
    const order = step.step_order;
    const stepName = step.user_description?.trim() ?? "";
    const output = step.output_type === "json" ? "structured" : "text";
    if (output === "structured" && !isJsonObject(step.output_contract)) continue;
    options.push({
      key: `step_${order}:${output}:*`,
      stepOrder: order,
      stepName,
      output,
      fieldPath: null,
      fieldType: null
    });
    if (output === "structured") {
      for (const field of contractFields(step.output_contract)) {
        options.push({
          key: `step_${order}:structured:${field.name}`,
          stepOrder: order,
          stepName,
          output: "structured",
          fieldPath: field.name,
          fieldType: field.type
        });
      }
    }
  }
  return options;
}

/** Inserts `{{token}}` at the selection of `value`; returns the text and the caret after it. */
export function insertToken(
  value: string,
  token: string,
  selection: { start: number; end: number } | null
): { text: string; caret: number } {
  const reference = `{{${token}}}`;
  const start = selection ? Math.min(selection.start, value.length) : value.length;
  const end = selection ? Math.min(Math.max(selection.end, start), value.length) : value.length;
  const text = value.slice(0, start) + reference + value.slice(end);
  return { text, caret: start + reference.length };
}
