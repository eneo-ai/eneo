/**
 * What a step reads, what it produces and who reads it: the facts the
 * overview cards, the step view and the navigator show, derived from the
 * definition alone (pure, unit-tested). The backend's validator is the
 * authority on references; this mirrors its reading of templates
 * (`eneo.flows.definition._templates_of`) for display.
 */
import { splitTemplate } from "./flow-template";
import {
  formFieldsOf,
  stepsOf,
  type FlowDefinition,
  type FlowStep,
  type FormField,
  type StepKind
} from "./types";

/** One source a step reads: a run input, an earlier step or a knowledge source. */
export type StepRead =
  | { kind: "form"; key: string; field: FormField | null; file: boolean }
  | {
      kind: "step";
      key: string;
      step: FlowStep | null;
      /** 0-based position of the step read, or null for an unknown key. */
      index: number | null;
      /** Read as `{{previous}}` (the step before), not by its key. */
      previous: boolean;
    }
  | { kind: "knowledge"; id: string; source: "collection" | "website" };

/** Every string in a value, depth first (a function step's arguments). */
function stringLeaves(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(stringLeaves);
  if (value && typeof value === "object") return Object.values(value).flatMap(stringLeaves);
  return [];
}

/** The templates a step renders at run time, in the order it reads them. */
export function templatesOf(step: FlowStep): string[] {
  switch (step.kind) {
    case "llm":
      return [step.input ?? "{{previous}}", step.prompt, step.processing?.summary_prompt ?? ""];
    case "compose":
      return [step.template];
    case "document":
      return [
        step.content ?? "",
        step.title ?? "",
        step.filename ?? "",
        ...Object.values(step.values ?? {})
      ];
    case "function":
      return stringLeaves(step.arguments ?? {});
    case "review":
    case "transcribe":
      return [];
  }
}

/**
 * What a step reads, each source once, in the order it is first named:
 * the references in its templates, then the files and knowledge it is
 * given. A review reads the step it reviews; a transcription its audio.
 */
export function stepReads(step: FlowStep, definition: FlowDefinition): StepRead[] {
  const steps = stepsOf(definition);
  const fields = formFieldsOf(definition);
  const index = steps.findIndex((candidate) => candidate.key === step.key);
  const reads: StepRead[] = [];
  const seen = new Set<string>();
  const add = (read: StepRead) => {
    const id = read.kind === "knowledge" ? `knowledge:${read.id}` : `${read.kind}:${read.key}`;
    if (seen.has(id)) return;
    seen.add(id);
    reads.push(read);
  };
  const form = (key: string, file: boolean) =>
    add({ kind: "form", key, field: fields.find((field) => field.key === key) ?? null, file });
  const stepByKey = (key: string, previous: boolean) => {
    const at = steps.findIndex((candidate) => candidate.key === key);
    add({
      kind: "step",
      key,
      step: at >= 0 ? steps[at]! : null,
      index: at >= 0 ? at : null,
      previous
    });
  };
  const previous = () => {
    if (index > 0) stepByKey(steps[index - 1]!.key, true);
  };

  for (const template of templatesOf(step)) {
    for (const part of splitTemplate(template, definition)) {
      if (part.kind !== "ref") continue;
      const ref = part.ref;
      if (ref.kind === "previous") previous();
      else if (ref.kind === "form") form(ref.key, ref.file);
      else if (ref.kind === "step") stepByKey(ref.key, false);
    }
  }
  if (step.kind === "llm" || step.kind === "function") {
    for (const key of step.files_from ?? []) form(key, true);
  }
  if (step.kind === "llm") {
    for (const id of step.knowledge?.collection_ids ?? []) {
      add({ kind: "knowledge", id, source: "collection" });
    }
    for (const id of step.knowledge?.website_ids ?? []) {
      add({ kind: "knowledge", id, source: "website" });
    }
  }
  if (step.kind === "transcribe") form(step.source, true);
  if (step.kind === "review") {
    if (step.of) stepByKey(step.of, false);
    else previous();
  }
  return reads;
}

/** A later step that reads this one, and how. */
export type StepUse = {
  step: FlowStep;
  /** 0-based position of the reading step. */
  index: number;
  /** As the step before it, by its key, or as the step it reviews. */
  via: "previous" | "key" | "review";
};

/** The later steps that read a step's output, in run order. */
export function stepUsedBy(key: string, definition: FlowDefinition): StepUse[] {
  const steps = stepsOf(definition);
  const from = steps.findIndex((candidate) => candidate.key === key);
  const uses: StepUse[] = [];
  steps.forEach((later, index) => {
    if (index <= from) return;
    const read = stepReads(later, definition).find(
      (candidate) => candidate.kind === "step" && candidate.key === key
    );
    if (!read || read.kind !== "step") return;
    uses.push({
      step: later,
      index,
      via: later.kind === "review" ? "review" : read.previous ? "previous" : "key"
    });
  });
  return uses;
}

/** What a step produces, as the overview and the step view describe it. */
export type StepProduces =
  | { kind: "text" }
  | { kind: "json"; fields: string[] }
  | {
      kind: "file";
      /** The format of a content document; a template file keeps its own. */
      format: "docx" | "pdf" | "template";
      filename: string | null;
    }
  | { kind: "function"; purpose: string; tool: string }
  | { kind: "transcript" }
  | { kind: "review" };

export function stepProduces(step: FlowStep): StepProduces {
  switch (step.kind) {
    case "llm":
      return step.output?.type === "json"
        ? { kind: "json", fields: schemaFieldNames(step.output.schema) }
        : { kind: "text" };
    case "compose":
      return { kind: "text" };
    case "document":
      return {
        kind: "file",
        format: step.template_file_id ? "template" : (step.format ?? "docx"),
        filename: step.filename ?? null
      };
    case "function":
      return { kind: "function", purpose: step.purpose, tool: step.tool };
    case "transcribe":
      return { kind: "transcript" };
    case "review":
      return { kind: "review" };
  }
}

/** The property names a JSON schema asks for at its top level, in order. */
export function schemaFieldNames(schema: Record<string, unknown>): string[] {
  const properties = schema.properties;
  if (!properties || typeof properties !== "object") return [];
  return Object.keys(properties as Record<string, unknown>);
}

/** One top-level field of a JSON schema, as a person reads it. */
export type SchemaFieldRow = {
  name: string;
  /** The field's shape: a key the view translates ("text", "number", "list", …). */
  shape: "text" | "number" | "boolean" | "list" | "object" | "one_of" | "any";
  /** For a list: the shape of its items; for one_of: the allowed values. */
  detail: string[];
  required: boolean;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

function shapeOf(schema: unknown): { shape: SchemaFieldRow["shape"]; detail: string[] } {
  if (!isRecord(schema)) return { shape: "any", detail: [] };
  if (Array.isArray(schema.enum)) {
    return { shape: "one_of", detail: (schema.enum as unknown[]).map((value) => String(value)) };
  }
  const type = Array.isArray(schema.type) ? schema.type[0] : schema.type;
  switch (type) {
    case "string":
      return { shape: "text", detail: [] };
    case "number":
    case "integer":
      return { shape: "number", detail: [] };
    case "boolean":
      return { shape: "boolean", detail: [] };
    case "array": {
      const items = shapeOf(schema.items);
      return { shape: "list", detail: [items.shape, ...items.detail] };
    }
    case "object":
      return { shape: "object", detail: schemaFieldNames(schema) };
    default:
      return { shape: "any", detail: [] };
  }
}

/** The top-level fields of a JSON schema with their shapes and whether each is required. */
export function schemaFieldRows(schema: Record<string, unknown>): SchemaFieldRow[] {
  const properties = isRecord(schema.properties) ? schema.properties : {};
  const required = new Set(
    Array.isArray(schema.required) ? (schema.required as unknown[]).map(String) : []
  );
  return Object.entries(properties).map(([name, property]) => ({
    name,
    ...shapeOf(property),
    required: required.has(name)
  }));
}

/** How the flow is overseen: how many steps of each kind, and where a person decides. */
export type FlowOversight = {
  counts: Partial<Record<StepKind, number>>;
  /** The first review step: its position, the step it reviews, the steps after it (1-based). */
  gate: { index: number; targetIndex: number | null; afterFrom: number; afterTo: number } | null;
};

export function flowOversight(definition: FlowDefinition): FlowOversight {
  const steps = stepsOf(definition);
  const counts: Partial<Record<StepKind, number>> = {};
  for (const step of steps) counts[step.kind] = (counts[step.kind] ?? 0) + 1;
  const index = steps.findIndex((step) => step.kind === "review");
  if (index < 0) return { counts, gate: null };
  const review = steps[index]!;
  const target =
    review.kind === "review" && review.of
      ? steps.findIndex((step) => step.key === review.of)
      : index - 1;
  return {
    counts,
    gate: {
      index,
      targetIndex: target >= 0 ? target : null,
      afterFrom: index + 2,
      afterTo: steps.length
    }
  };
}
