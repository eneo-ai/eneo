import { isJsonObject, type JsonObject } from "./step-types";
import { isVariablePathSegment } from "./step-variables";

/**
 * The output contract an example answer implies, as the reference editor
 * proposes it (`outputContractFromExample.ts` in apps/web): an object whose
 * keys are all required fields, each typed by its value. Pure and
 * unit-tested.
 */

/** Container levels an example is read to, the root object being the first. */
const EXAMPLE_LEVELS = 4;
export const EXAMPLE_MAX_CHARACTERS = 200_000;
export const EXAMPLE_MAX_FIELDS = 500;

export type ExampleProblem = "syntax" | "not_object" | "no_fields" | "inexact_number" | "too_large";

/** A part of the contract one example could not decide, for the author to check. */
export type ExampleNote = "empty_list" | "null_value" | "mixed_list";

export type ExampleShape =
  | { kind: "string" | "number" | "boolean" | "text_or_empty" }
  /** `fields` is empty for an object read only as a type. */
  | { kind: "object"; fields: string[] }
  /** `item` is null for a list whose elements are left open. */
  | { kind: "list"; item: ExampleShape | null };

export type ContractFromExample =
  | {
      ok: true;
      contract: JsonObject;
      /** `variable` is false for a name a later step cannot read as a reference. */
      fields: { name: string; shape: ExampleShape; variable: boolean }[];
      notes: ExampleNote[];
    }
  | { ok: false; problem: ExampleProblem };

type Read = { schema: JsonObject; shape: ExampleShape };
type Walk = { notes: Set<ExampleNote>; fields: number; inexact: boolean };

/** A number JSON cannot hold exactly, which would make the example a misread one. */
function inexactNumber(value: number): boolean {
  return !Number.isFinite(value) || (Number.isInteger(value) && !Number.isSafeInteger(value));
}

/**
 * Every number is typed "number" (one whole number does not show a field is
 * always whole). A list is typed by its first element; an empty list leaves
 * its elements open, a null reads as text or empty, and a list whose
 * elements differ gets its first element's type, each with a note. Only
 * `type`, `properties`, `required` and `items` are written, keywords every
 * contract dialect the core accepts reads alike.
 */
export function contractFromExample(text: string): ContractFromExample {
  if (text.length > EXAMPLE_MAX_CHARACTERS) return { ok: false, problem: "too_large" };
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return { ok: false, problem: "syntax" };
  }
  if (!isJsonObject(value)) return { ok: false, problem: "not_object" };
  if (Object.keys(value).length === 0) return { ok: false, problem: "no_fields" };
  const walk: Walk = { notes: new Set(), fields: 0, inexact: false };
  const fields = readFields(Object.entries(value), 2, walk);
  if (walk.fields > EXAMPLE_MAX_FIELDS) return { ok: false, problem: "too_large" };
  if (walk.inexact) return { ok: false, problem: "inexact_number" };
  return {
    ok: true,
    contract: objectSchema(fields),
    fields: fields.map(({ name, read }) => ({
      name,
      shape: read.shape,
      variable: isVariablePathSegment(name)
    })),
    notes: [...walk.notes]
  };
}

function readFields(entries: [string, unknown][], level: number, walk: Walk) {
  walk.fields += entries.length;
  return entries.map(([name, value]) => ({ name, read: schemaOf(value, level, walk) }));
}

function objectSchema(fields: { name: string; read: Read }[]): JsonObject {
  return {
    type: "object",
    // fromEntries defines each key, so a key such as `__proto__` stays a field.
    properties: Object.fromEntries(fields.map(({ name, read }) => [name, read.schema])),
    required: fields.map(({ name }) => name)
  };
}

/** What decides an element's schema at its own level: its kind, and an object's keys. */
function elementKind(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "list";
  if (isJsonObject(value)) return `object:${JSON.stringify(Object.keys(value).sort())}`;
  return typeof value;
}

function schemaOf(value: unknown, level: number, walk: Walk): Read {
  if (value === null) {
    walk.notes.add("null_value");
    return { schema: { type: ["string", "null"] }, shape: { kind: "text_or_empty" } };
  }
  if (typeof value === "string") return { schema: { type: "string" }, shape: { kind: "string" } };
  if (typeof value === "boolean") {
    return { schema: { type: "boolean" }, shape: { kind: "boolean" } };
  }
  if (typeof value === "number") {
    if (inexactNumber(value)) walk.inexact = true;
    return { schema: { type: "number" }, shape: { kind: "number" } };
  }
  if (Array.isArray(value)) {
    const open: Read = { schema: { type: "array" }, shape: { kind: "list", item: null } };
    if (level > EXAMPLE_LEVELS) return open;
    if (value.length === 0) {
      walk.notes.add("empty_list");
      return open;
    }
    const first = elementKind(value[0]);
    if (value.some((element) => elementKind(element) !== first)) walk.notes.add("mixed_list");
    const item = schemaOf(value[0], level + 1, walk);
    return {
      schema: { type: "array", items: item.schema },
      shape: { kind: "list", item: item.shape }
    };
  }
  const entries = isJsonObject(value) ? Object.entries(value) : [];
  if (level > EXAMPLE_LEVELS || entries.length === 0) {
    return { schema: { type: "object" }, shape: { kind: "object", fields: [] } };
  }
  const fields = readFields(entries, level + 1, walk);
  return {
    schema: objectSchema(fields),
    shape: { kind: "object", fields: fields.map(({ name }) => name) }
  };
}
