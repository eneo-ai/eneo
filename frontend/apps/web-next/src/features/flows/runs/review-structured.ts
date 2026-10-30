/**
 * A form for a paused JSON step's output, built from the step's output
 * contract (a JSON Schema snapshot on the checkpoint): objects as their
 * properties, lists as rows a reviewer can add and remove, and scalars as
 * text, number, choice or yes/no controls. Pure; the structured review
 * editor renders it. The core validates the whole contract on save, so
 * nothing here resolves references or guesses a branch: a part the form
 * cannot express stays visible and unchanged.
 */

export type ReviewValue =
  string | number | boolean | null | ReviewValue[] | { [key: string]: ReviewValue };

export type ReviewSchema = Record<string, unknown>;

export type FieldKind =
  "object" | "array" | "string" | "number" | "boolean" | "enum" | "readonly" | "unsupported";

const MAX_DEPTH = 20;

export function schemaOf(value: unknown): ReviewSchema {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as ReviewSchema)
    : {};
}

export function isReviewObject(
  value: ReviewValue | undefined
): value is { [key: string]: ReviewValue } {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** Whether the value is plain JSON data (no functions, no non-finite numbers). */
export function isReviewValue(value: unknown, depth = 0): value is ReviewValue {
  if (depth > 100) return false;
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) return value.every((item) => isReviewValue(item, depth + 1));
  return (
    typeof value === "object" &&
    Object.values(value as object).every((item) => isReviewValue(item, depth + 1))
  );
}

function stringChoices(schema: ReviewSchema): string[] | null {
  return Array.isArray(schema.enum) && schema.enum.every((choice) => typeof choice === "string")
    ? (schema.enum as string[])
    : null;
}

/**
 * How a part of the contract is edited. A stored value of another kind
 * than the contract says stays visible as it is ("unsupported") instead of
 * being replaced by an empty control; an empty number or yes/no (a new
 * row's) is still the contract's kind.
 */
export function fieldKind(schema: ReviewSchema, value?: ReviewValue, depth = 0): FieldKind {
  if (depth > MAX_DEPTH) return "unsupported";
  if (["$ref", "allOf", "anyOf", "oneOf", "if", "not"].some((key) => key in schema)) {
    return "unsupported";
  }
  if ("const" in schema || schema.readOnly === true) return "readonly";
  const type = schema.type;
  if (value !== undefined) {
    const fits =
      type === "object"
        ? isReviewObject(value)
        : type === "array"
          ? Array.isArray(value)
          : type === "string"
            ? typeof value === "string"
            : type === "number" || type === "integer"
              ? typeof value === "number" || value === null
              : type === "boolean"
                ? typeof value === "boolean" || value === ""
                : true;
    if (!fits) return "unsupported";
  }
  if (type === "string" && stringChoices(schema)) return "enum";
  switch (type) {
    case "object":
      return Object.keys(schemaOf(schema.properties)).length > 0 ? "object" : "unsupported";
    case "array":
      return Object.keys(schemaOf(schema.items)).length > 0 ? "array" : "unsupported";
    case "string":
      return "string";
    case "number":
    case "integer":
      return "number";
    case "boolean":
      return "boolean";
    default:
      return "unsupported";
  }
}

/** The contract's title for a property, else its key in words ("due_date" → "Due date"). */
export function fieldLabel(schema: ReviewSchema, key: string): string {
  if (typeof schema.title === "string" && schema.title.trim()) return schema.title.trim();
  return key.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

/** The contract's description of a part, when it has one. */
export function fieldDescription(schema: ReviewSchema): string | undefined {
  return typeof schema.description === "string" && schema.description.trim()
    ? schema.description.trim()
    : undefined;
}

/** The choices a string field offers. */
export function fieldChoices(schema: ReviewSchema): string[] {
  return stringChoices(schema) ?? [];
}

/**
 * An object's properties in the contract's order, then any the value
 * carries that the contract does not name (kept, shown as they are).
 */
export function objectFields(
  schema: ReviewSchema,
  value: ReviewValue | undefined
): { key: string; schema: ReviewSchema }[] {
  const properties = schemaOf(schema.properties);
  const keys = new Set([
    ...Object.keys(properties),
    ...Object.keys(isReviewObject(value) ? value : {})
  ]);
  return [...keys].map((key) => ({ key, schema: schemaOf(properties[key]) }));
}

/** The object with one property replaced; properties the contract does not name are kept. */
export function withProperty(
  value: ReviewValue | undefined,
  key: string,
  next: ReviewValue
): ReviewValue {
  return { ...(isReviewObject(value) ? value : {}), [key]: next };
}

/**
 * A new row for a list: its required properties, each empty. Nothing is
 * chosen for the reviewer: no enum choice, number or yes/no is inferred.
 */
export function emptyValue(schema: ReviewSchema, depth = 0): ReviewValue {
  if (depth > MAX_DEPTH) return null;
  if ("const" in schema && isReviewValue(schema.const)) return schema.const;
  if (schema.type === "object") {
    const required = Array.isArray(schema.required) ? schema.required : [];
    return Object.fromEntries(
      Object.entries(schemaOf(schema.properties))
        .filter(([key]) => required.includes(key))
        .map(([key, child]) => [key, emptyValue(schemaOf(child), depth + 1)])
    );
  }
  if (schema.type === "array") return [];
  if (schema.type === "number" || schema.type === "integer") return null;
  return "";
}

/** A row's first two text fields, to tell rows apart while they are closed. */
export function itemPreview(schema: ReviewSchema, value: ReviewValue): string {
  if (!isReviewObject(value)) return "";
  const preview = objectFields(schema, value)
    .filter((field) => fieldKind(field.schema) === "string")
    .map((field) => value[field.key])
    .filter((entry): entry is string => typeof entry === "string" && entry.trim().length > 0)
    .slice(0, 2)
    .join(": ");
  return preview.length > 80 ? `${preview.slice(0, 80)}…` : preview;
}

/**
 * Whether the output can be reviewed as a form: the contract describes an
 * object or a list the form can edit, and the stored value is of that kind.
 */
export function formFits(contract: unknown, value: unknown): value is ReviewValue {
  if (!isReviewValue(value)) return false;
  const kind = fieldKind(schemaOf(contract), value);
  return kind === "object" || kind === "array";
}

/** Whether two values are the same JSON (object key order aside). */
export function valuesEqual(
  left: ReviewValue | undefined,
  right: ReviewValue | undefined
): boolean {
  if (left === right) return true;
  if (Array.isArray(left) && Array.isArray(right)) {
    return (
      left.length === right.length && left.every((item, index) => valuesEqual(item, right[index]))
    );
  }
  if (isReviewObject(left) && isReviewObject(right)) {
    const keys = new Set([...Object.keys(left), ...Object.keys(right)]);
    return [...keys].every((key) => valuesEqual(left[key], right[key]));
  }
  return false;
}

/** The path of an object's property, as `changedPaths` names it. */
export function propertyPath(path: string, key: string): string {
  return `${path}/${key.replaceAll("~", "~0").replaceAll("/", "~1")}`;
}

/**
 * Where a value differs from what it was: the path of each property that
 * changed and of every object around it ("" is the whole value). A list
 * changes as a whole: its rows have no identity to match them by, so a
 * row-by-row comparison would mark false matches.
 */
export function changedPaths(before: ReviewValue, after: ReviewValue): ReadonlySet<string> {
  const changed = new Set<string>();
  function visit(left: ReviewValue | undefined, right: ReviewValue | undefined, path: string) {
    let differs: boolean;
    if (isReviewObject(left) && isReviewObject(right)) {
      differs = false;
      for (const key of new Set([...Object.keys(left), ...Object.keys(right)])) {
        if (visit(left[key], right[key], propertyPath(path, key))) differs = true;
      }
    } else {
      differs = !valuesEqual(left, right);
    }
    if (differs) changed.add(path);
    return differs;
  }
  visit(before, after, "");
  return changed;
}

/** A description long enough to sit behind a help button rather than under the field. */
export const LONG_DESCRIPTION_CHARS = 140;
