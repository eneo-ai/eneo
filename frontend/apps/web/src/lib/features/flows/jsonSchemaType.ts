import { m } from "$lib/paraglide/messages";

/** The JSON Schema types the editor names to an author, in their words. */
const TYPE_LABELS = {
  string: m.flow_json_type_string,
  number: m.flow_json_type_number,
  integer: m.flow_json_type_integer,
  boolean: m.flow_json_type_boolean,
  array: m.flow_json_type_array,
  object: m.flow_json_type_object
};

export type JsonSchemaType = keyof typeof TYPE_LABELS;

function isJsonSchemaType(value: unknown): value is JsonSchemaType {
  return typeof value === "string" && Object.hasOwn(TYPE_LABELS, value);
}

/** The one type a schema's `type` keyword names; null for a list of types, `null` or none. */
export function readJsonSchemaType(type: unknown): JsonSchemaType | null {
  return isJsonSchemaType(type) ? type : null;
}

export function jsonSchemaTypeLabel(type: JsonSchemaType): string {
  return TYPE_LABELS[type]();
}
