export type FlowFormFieldType =
  | "text"
  | "number"
  | "date"
  | "select"
  | "multiselect"
  | "email"
  | "textarea"
  | "string";

export type FlowFormField = {
  name: string;
  type: FlowFormFieldType | string;
  required?: boolean;
  options?: string[];
  order?: number;
};

export type NormalizedFlowFormFieldType = "text" | "number" | "date" | "select" | "multiselect";

export type NormalizedFlowFormField = {
  name: string;
  type: NormalizedFlowFormFieldType;
  required: boolean;
  options: string[];
  order: number;
};

const LEGACY_TEXT_TYPES = new Set(["email", "textarea", "string"]);
const OPTION_FIELD_TYPES = new Set<NormalizedFlowFormFieldType>(["select", "multiselect"]);
const FLOW_FORM_RESERVED_VARIABLE_NAMES = new Set([
  "flow",
  "flow_input",
  "transkribering",
  "föregående_steg",
  "indata_text",
  "indata_json",
  "indata_filer",
]);
const FLOW_FORM_RESERVED_VARIABLE_NAMES_NORMALIZED = new Set(
  [...FLOW_FORM_RESERVED_VARIABLE_NAMES].map((name) => name.toLowerCase()),
);
const FLOW_FORM_STEP_ALIAS_PATTERN = /^step_\d+($|[._])/i;

export type FlowFormFieldNameIssue = "reserved" | "step_alias" | "dot";

export function normalizeFlowFormFieldType(
  type: FlowFormFieldType | string | undefined,
): NormalizedFlowFormFieldType {
  const normalized = (type ?? "text").trim().toLowerCase();
  if (LEGACY_TEXT_TYPES.has(normalized)) return "text";
  if (normalized === "number") return "number";
  if (normalized === "date") return "date";
  if (normalized === "select") return "select";
  if (normalized === "multiselect") return "multiselect";
  return "text";
}

export function flowFormFieldHasOptions(
  type: FlowFormFieldType | string | undefined,
): boolean {
  return OPTION_FIELD_TYPES.has(normalizeFlowFormFieldType(type));
}

export function normalizeFlowFormFields(fields: FlowFormField[]): NormalizedFlowFormField[] {
  return [...fields]
    .map((field, index) => ({
      name: typeof field.name === "string" ? field.name : "",
      type: normalizeFlowFormFieldType(field.type),
      required: Boolean(field.required),
      options: Array.isArray(field.options)
        ? field.options
            .filter((option): option is string => typeof option === "string")
            .map((option) => option.trim())
            .filter((option) => option.length > 0)
        : [],
      order: typeof field.order === "number" ? field.order : index + 1,
    }))
    .sort((left, right) => left.order - right.order)
    .map((field, index) => ({ ...field, order: index + 1 }));
}

export function toPersistedFlowFormFields(
  fields: Array<
    Pick<NormalizedFlowFormField, "name" | "type" | "required" | "options"> & {
      type: FlowFormFieldType | string;
    }
  >,
): FlowFormField[] {
  return fields.map((field, index) => {
    const type = normalizeFlowFormFieldType(field.type);
    const normalized: FlowFormField = {
      name: getFlowFormFieldRuntimeKey(field.name),
      type,
      required: Boolean(field.required),
      order: index + 1,
    };
    if (flowFormFieldHasOptions(type)) {
      normalized.options = (field.options ?? [])
        .map((option) => option.trim())
        .filter((option) => option.length > 0);
    }
    return normalized;
  });
}

export function getFlowFormStats(
  fields: Array<Pick<FlowFormField, "required">>,
): { definedCount: number; requiredCount: number } {
  return {
    definedCount: fields.length,
    requiredCount: fields.filter((field) => Boolean(field.required)).length,
  };
}

export function getFlowFormFieldRuntimeKey(name: string): string {
  return name.trim();
}

export function getFlowFormFieldNameIssue(name: string): FlowFormFieldNameIssue | null {
  const normalized = getFlowFormFieldRuntimeKey(name);
  if (!normalized) return null;
  if (FLOW_FORM_RESERVED_VARIABLE_NAMES_NORMALIZED.has(normalized.toLowerCase())) return "reserved";
  if (FLOW_FORM_STEP_ALIAS_PATTERN.test(normalized)) return "step_alias";
  if (normalized.includes(".")) return "dot";
  return null;
}

export function isFlowFormFieldNameUsableAsVariable(name: string): boolean {
  const normalized = getFlowFormFieldRuntimeKey(name);
  return normalized.length > 0 && getFlowFormFieldNameIssue(normalized) === null;
}

export function getFlowFormFieldVariableToken(name: string): string {
  const trimmed = getFlowFormFieldRuntimeKey(name);
  return isFlowFormFieldNameUsableAsVariable(trimmed) ? `{{${trimmed}}}` : "";
}
