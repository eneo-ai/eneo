import { holdsInexactNumber, readJson } from "./components/tool/toolInputConfig";
import { isVariablePathSegment } from "./flowVariableTokens";
import { isJsonObject, type JsonObject } from "./jsonObject";

/**
 * Container levels an example is read to, the root object being the first.
 * A deeper object or list keeps only its type, so a large nested answer does
 * not become a contract nobody reads.
 */
const EXAMPLE_LEVELS = 4;

/**
 * The largest example read, in characters and in fields written to the
 * contract. A pasted answer beyond them is refused rather than turned into a
 * contract no author checks field by field and that publishing is slow to check.
 */
export const EXAMPLE_MAX_CHARACTERS = 200_000;
export const EXAMPLE_MAX_FIELDS = 500;

/** Why an example gives no contract. */
export type ExampleProblem = "syntax" | "not_object" | "no_fields" | "inexact_number" | "too_large";

/** A part of the contract the example could not decide, which the author should check. */
export type ExampleNote = "empty_list" | "null_value" | "mixed_list";

/** What a field of the contract holds, as the preview names it. */
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
      /** `variable` is false for a name a later step cannot reach as a variable. */
      fields: { name: string; shape: ExampleShape; variable: boolean }[];
      notes: ExampleNote[];
    }
  | { ok: false; problem: ExampleProblem };

type Read = { schema: JsonObject; shape: ExampleShape };
type Walk = { notes: Set<ExampleNote>; fields: number; inexact: boolean };

/**
 * The output contract an example value implies: an object whose keys are all
 * required fields, each typed by its value (every number as "number"). A list
 * is typed by its first element. An empty list leaves its elements open, a null
 * is read as text or empty, and a list whose elements differ in kind or keys
 * gets its first element's type, since one value cannot say more; each is
 * reported as a note. Only `type`, `properties`, `required` and `items` are
 * written, all of them keywords every contract dialect the server accepts
 * reads alike. `variable` is decided for the top-level fields only, the ones
 * the preview lists.
 */
export function contractFromExample(text: string): ContractFromExample {
  if (text.length > EXAMPLE_MAX_CHARACTERS) return { ok: false, problem: "too_large" };
  const read = readJson(text);
  if (!read.ok) return { ok: false, problem: "syntax" };
  if (!isJsonObject(read.value)) return { ok: false, problem: "not_object" };
  if (Object.keys(read.value).length === 0) return { ok: false, problem: "no_fields" };
  const walk: Walk = { notes: new Set(), fields: 0, inexact: false };
  const fields = readFields(Object.entries(read.value), 2, walk);
  if (walk.fields > EXAMPLE_MAX_FIELDS) return { ok: false, problem: "too_large" };
  // The type is all that is kept, but a rounded number would be a misread example.
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
  // A whole number in one example does not show the field is always whole.
  if (typeof value === "number") {
    if (holdsInexactNumber(value)) walk.inexact = true;
    return { schema: { type: "number" }, shape: { kind: "number" } };
  }
  if (Array.isArray(value)) {
    const open = { schema: { type: "array" }, shape: { kind: "list", item: null } } as const;
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
