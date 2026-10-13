import { isJsonObject, type JsonObject } from "$lib/features/flows/jsonObject";
import { readArgument } from "./toolInputConfig";

type ToolChoiceValue = string | number | boolean;

/** The control a fixed value is entered with, by what the schema says the argument is. */
export type ToolArgumentControl =
  | { kind: "text" }
  | { kind: "number"; integer: boolean }
  | { kind: "boolean" }
  | { kind: "choice"; options: ToolChoiceValue[] }
  | { kind: "json" };

export type ToolArgumentField = {
  name: string;
  description: string | null;
  required: boolean;
  control: ToolArgumentControl;
};

/**
 * How the editor asks for a tool's arguments: not at all, one row per named
 * argument (`closed` when the tool takes no others), or as one JSON object
 * when it cannot tell the arguments apart.
 */
type ToolArgumentForm =
  | { kind: "none" }
  | { kind: "fields"; fields: ToolArgumentField[]; closed: boolean }
  | { kind: "json" };

const SCALAR_CONTROLS: Record<string, ToolArgumentControl> = {
  string: { kind: "text" },
  integer: { kind: "number", integer: true },
  number: { kind: "number", integer: false },
  boolean: { kind: "boolean" }
};

function scalarControl(type: unknown): ToolArgumentControl | null {
  return typeof type === "string" && Object.hasOwn(SCALAR_CONTROLS, type)
    ? SCALAR_CONTROLS[type]
    : null;
}

function isChoiceValue(value: unknown): value is ToolChoiceValue {
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean";
}

function controlFor(property: unknown): ToolArgumentControl {
  if (!isJsonObject(property)) return { kind: "json" };
  if (Array.isArray(property.enum)) {
    const options = property.enum.filter(isChoiceValue);
    return options.length > 0 && options.length === property.enum.length
      ? { kind: "choice", options }
      : { kind: "json" };
  }
  // Any other description (a list of types, `anyOf`, a nullable scalar) is
  // JSON, the one control that can write every value it allows, null too.
  return scalarControl(property.type) ?? { kind: "json" };
}

// The top-level keywords the editor reads, and those that say nothing about
// which arguments there are. A schema with any other keyword (a reference, a
// combination) is not shown as rows.
const FORM_KEYWORDS = [
  "type",
  "properties",
  "required",
  "additionalProperties",
  "title",
  "description",
  "$schema",
  "$defs",
  "definitions"
];

/**
 * The form for a tool's approved input schema. Rows are built from
 * `properties`, `required`, and each property's `type`, `enum` and
 * `description`; an argument described in any other way is one row that
 * takes JSON. A tool without a schema takes any arguments, so it gets the
 * JSON field.
 */
export function readToolArgumentForm(inputSchema: unknown): ToolArgumentForm {
  if (!isJsonObject(inputSchema)) return { kind: "json" };
  const { type = "object", properties = {}, required = [] } = inputSchema;
  if (
    type !== "object" ||
    !isJsonObject(properties) ||
    !Array.isArray(required) ||
    Object.keys(inputSchema).some((keyword) => !FORM_KEYWORDS.includes(keyword)) ||
    required.some((name: unknown) => typeof name !== "string" || !Object.hasOwn(properties, name))
  ) {
    return { kind: "json" };
  }
  const fields = Object.entries(properties).map(([name, property]) => ({
    name,
    description:
      isJsonObject(property) &&
      typeof property.description === "string" &&
      property.description.trim()
        ? property.description
        : null,
    required: required.includes(name),
    control: controlFor(property)
  }));
  // JSON Schema allows arguments beyond the named ones unless
  // `additionalProperties` is false.
  const closed = inputSchema.additionalProperties === false;
  if (fields.length > 0) return { kind: "fields", fields, closed };
  // "No arguments" only when the schema says so; an open one takes arguments
  // of any name, which the JSON field can write.
  return closed && inputSchema.type === "object" ? { kind: "none" } : { kind: "json" };
}

/** True when the tool cannot be called as configured: the argument is required and has no value. */
export function isRequiredArgumentMissing(field: ToolArgumentField, value: unknown): boolean {
  return field.required && value === undefined;
}

/**
 * The first required argument of a tool's input schema that `stored` has no
 * value for; null also when the schema is not one the editor shows as rows.
 */
export function firstMissingRequiredArgument(
  inputSchema: unknown,
  stored: JsonObject
): string | null {
  const form = readToolArgumentForm(inputSchema);
  if (form.kind !== "fields") return null;
  const missing = form.fields.find((field) =>
    isRequiredArgumentMissing(field, readArgument(stored, field.name))
  );
  return missing?.name ?? null;
}
