import { readMeaning, readTone, type ReadMeaning } from "../editor/request-preview";
import { contractFields } from "../editor/step-variables";
import type { FlowPublic, FlowStep } from "../editor/step-types";
import { templateParts } from "../flow-steps";

/**
 * References in the flow chat: what a message can point at, how a reference
 * travels in the text, and what a pill says about it. A value a step
 * produces travels as the reference the flow resolves (`{{step_2.output.text}}`),
 * which the core renumbers when steps move; a step itself travels as a
 * mention that carries its id (`@[Bedömning](step:<id>)`), so the chat's
 * tools can change it without a lookup. Pure and unit-tested.
 */

/** A step mention in a message: `@[<name>](step:<id>)`. */
export const STEP_MENTION = /@\[([^\]\n]+)\]\(step:([^)\s]+)\)/g;

export function stepMention(step: Pick<FlowStep, "id" | "user_description">): string {
  const name = (step.user_description?.trim() || "").replace(/[[\]]/g, "") || "?";
  return `@[${name}](step:${step.id})`;
}

export function valueReference(token: string): string {
  return `{{${token}}}`;
}

export type Reference =
  /** A step, by id; `step` is null when the flow no longer has it. */
  | { kind: "step"; raw: string; stepId: string; name: string; step: FlowStep | null }
  /** A value, by the reference the flow resolves. */
  | { kind: "value"; raw: string; token: string; meaning: ReadMeaning };

export type ReferencePart = { kind: "text"; text: string } | Reference;

type Flow = Pick<FlowPublic, "steps" | "metadata_json">;

/** The place from which every step is earlier, so each one can be read. */
function afterEveryStep(flow: Pick<FlowPublic, "steps">): number {
  return Math.max(0, ...flow.steps.map((step) => step.step_order)) + 1;
}

export function stepReference(stepId: string, name: string, flow: Pick<FlowPublic, "steps">) {
  const step = flow.steps.find((candidate) => candidate.id === stepId) ?? null;
  return {
    kind: "step" as const,
    raw: `@[${name}](step:${stepId})`,
    stepId,
    name: step?.user_description?.trim() || name,
    step
  };
}

export function valueOf(token: string, flow: Flow): Reference {
  return {
    kind: "value",
    raw: valueReference(token),
    token,
    meaning: readMeaning(token, afterEveryStep(flow), flow)
  };
}

function mentionParts(text: string, flow: Flow): ReferencePart[] {
  const parts: ReferencePart[] = [];
  let cursor = 0;
  for (const match of text.matchAll(STEP_MENTION)) {
    const start = match.index ?? 0;
    if (start > cursor) parts.push({ kind: "text", text: text.slice(cursor, start) });
    parts.push({ ...stepReference(match[2]!, match[1]!, flow), raw: match[0] });
    cursor = start + match[0].length;
  }
  if (cursor < text.length) parts.push({ kind: "text", text: text.slice(cursor) });
  return parts;
}

/** The text split into plain text, value references and step mentions. */
export function referenceParts(text: string, flow: Flow): ReferencePart[] {
  return templateParts(text).flatMap((part): ReferencePart[] =>
    part.kind === "text" ? mentionParts(part.text, flow) : [valueOf(part.token, flow)]
  );
}

/** The reference a text is, as written, or null for anything else. */
export function parseReference(raw: string, flow: Flow): Reference | null {
  const parts = referenceParts(raw, flow);
  const part = parts[0];
  return parts.length === 1 && part && part.kind !== "text" ? part : null;
}

/** The references a text holds, each once, in order of first appearance. */
export function referencesIn(text: string, flow: Flow): Reference[] {
  const seen = new Set<string>();
  return referenceParts(text, flow).flatMap((part) => {
    if (part.kind === "text" || seen.has(part.raw)) return [];
    seen.add(part.raw);
    return [part];
  });
}

/** How a reference fares: it reads, it reads nothing useful, or its step is gone. */
export function referenceTone(reference: Reference): "reads" | "warning" | "missing" {
  if (reference.kind === "step") return reference.step ? "reads" : "missing";
  return readTone(reference.meaning);
}

/** The step a reference belongs to, when it names one the flow has. */
export function referenceStep(reference: Reference, flow: Pick<FlowPublic, "steps">) {
  if (reference.kind === "step") return reference.step;
  const meaning = reference.meaning;
  if (!("order" in meaning)) return null;
  return flow.steps.find((step) => step.step_order === meaning.order) ?? null;
}

/** What a pill of a value says after the step: a field's name, "text" or "fast format". */
export type ValueWhat =
  { type: "field"; field: string } | { type: "text" } | { type: "structured" };

export function valueWhat(meaning: ReadMeaning): ValueWhat | null {
  switch (meaning.kind) {
    case "step_field":
      return { type: "field", field: meaning.field };
    case "step_answer":
      return { type: "text" };
    case "step_structured":
      return { type: "structured" };
    case "fields_of_text":
      return { type: "structured" };
    default:
      return null;
  }
}

/** One row of the reference menu: a step, a value the step produces, or a value of the run. */
export type ReferenceChoice =
  | { kind: "step"; step: FlowStep; raw: string }
  | { kind: "value"; step: FlowStep; token: string; raw: string; what: ValueWhat }
  | { kind: "run"; token: "flow_input" | "datum"; raw: string };

/**
 * What a reference that reads nothing useful could have meant: the values of
 * the step it names (`{{step_1...}}`, `{{step_1.output}}`, a field of a step
 * that answers in text). Null when it names no step the flow has.
 */
export function referenceHint(
  reference: Reference,
  flow: Pick<FlowPublic, "steps">
): { step: FlowStep; choices: Extract<ReferenceChoice, { kind: "value" }>[] } | null {
  if (reference.kind !== "value") return null;
  const tone = referenceTone(reference);
  if (tone === "reads") return null;
  const order =
    "order" in reference.meaning
      ? reference.meaning.order
      : Number(/^step_(\d+)/.exec(reference.token)?.[1] ?? NaN);
  const step = flow.steps.find((candidate) => candidate.step_order === order);
  if (!step) return null;
  const choices = referenceChoices(flow).filter(
    (choice): choice is Extract<ReferenceChoice, { kind: "value" }> =>
      choice.kind === "value" && choice.step === step
  );
  return choices.length > 0 ? { step, choices } : null;
}

/** The run's own values, after the steps: what is sent in, and the date. */
export const RUN_CHOICES: ReferenceChoice[] = [
  { kind: "run", token: "flow_input", raw: valueReference("flow_input") },
  { kind: "run", token: "datum", raw: valueReference("datum") }
];

/** What the menu offers, step by step: the step itself, then its values. */
export function referenceChoices(flow: Pick<FlowPublic, "steps">): ReferenceChoice[] {
  const steps = [...flow.steps].sort((left, right) => left.step_order - right.step_order);
  return steps.flatMap((step): ReferenceChoice[] => {
    if (!step.id) return [];
    const order = step.step_order;
    const choices: ReferenceChoice[] = [
      {
        kind: "step",
        step,
        raw: stepMention({ id: step.id, user_description: step.user_description })
      }
    ];
    const text = `step_${order}.output.text`;
    choices.push({
      kind: "value",
      step,
      token: text,
      raw: valueReference(text),
      what: { type: "text" }
    });
    if (step.output_type === "json") {
      const structured = `step_${order}.output.structured`;
      choices.push({
        kind: "value",
        step,
        token: structured,
        raw: valueReference(structured),
        what: { type: "structured" }
      });
      for (const field of contractFields(step.output_contract)) {
        const token = `${structured}.${field.name}`;
        choices.push({
          kind: "value",
          step,
          token,
          raw: valueReference(token),
          what: { type: "field", field: field.name }
        });
      }
    }
    return choices;
  });
}
