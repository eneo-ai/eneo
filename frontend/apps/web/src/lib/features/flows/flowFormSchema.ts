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

export type FlowFormSchemaMetadata = {
  fields: FlowFormField[];
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
// Keep this UX mirror aligned with backend/src/intric/flows/flow_variable_definitions.py.
const RESERVED_RUNTIME_VARIABLE_NAMES = new Set([
  "datum",
  "flow",
  "flow_input",
  "step_input",
  "transkribering",
  "föregående_steg",
  "indata_text",
  "indata_json",
  "indata_filer"
]);
const FORM_FIELD_NAMESPACE_HEADS = new Set(["flow", "flow_input", "step_input"]);
export const PRIMARY_FLOW_INPUT_KEYS = new Set([
  "file_ids",
  "json",
  "structured",
  "text",
  "transcribed_text",
  "transcription",
  "transcript",
  "transkribering"
]);
const FLOW_FORM_STEP_ALIAS_PATTERN = /^step_\d+($|[._])/i;

export type FlowFormFieldNameIssue = "namespace_head" | "primary_input_key" | "step_alias" | "dot";

export function normalizeFlowFormFieldType(
  type: FlowFormFieldType | string | undefined
): NormalizedFlowFormFieldType {
  const normalized = (type ?? "text").trim().toLowerCase();
  if (LEGACY_TEXT_TYPES.has(normalized)) return "text";
  if (normalized === "number") return "number";
  if (normalized === "date") return "date";
  if (normalized === "select") return "select";
  if (normalized === "multiselect") return "multiselect";
  return "text";
}

export function flowFormFieldHasOptions(type: FlowFormFieldType | string | undefined): boolean {
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
      order: typeof field.order === "number" ? field.order : index + 1
    }))
    .sort((left, right) => left.order - right.order)
    .map((field, index) => ({ ...field, order: index + 1 }));
}

export function toPersistedFlowFormFields(fields: FlowFormField[]): FlowFormField[] {
  return fields.map((field, index) => {
    const type = normalizeFlowFormFieldType(field.type);
    const normalized: FlowFormField = {
      name: getFlowFormFieldRuntimeKey(field.name),
      type,
      required: Boolean(field.required),
      order: index + 1
    };
    if (flowFormFieldHasOptions(type)) {
      normalized.options = (field.options ?? [])
        .map((option) => option.trim())
        .filter((option) => option.length > 0);
    }
    return normalized;
  });
}

export function buildFlowFormSchemaMetadata(
  metadata: Record<string, unknown> | null | undefined,
  fields: FlowFormField[]
): Record<string, unknown> {
  return {
    ...(metadata ?? {}),
    form_schema: { fields }
  };
}

export function getFlowFormSchemaMetadata(
  metadata: Record<string, unknown> | null | undefined
): FlowFormSchemaMetadata | undefined {
  const formSchema = metadata?.form_schema;
  if (typeof formSchema !== "object" || formSchema === null) return undefined;

  const fields = (formSchema as { fields?: unknown }).fields;
  if (!Array.isArray(fields)) return undefined;

  return { fields: fields as FlowFormField[] };
}

export function getFlowFormSchemaFields(
  metadata: Record<string, unknown> | null | undefined
): FlowFormField[] {
  return getFlowFormSchemaMetadata(metadata)?.fields ?? [];
}

export function getFlowFormStats(fields: Array<Pick<FlowFormField, "required">>): {
  definedCount: number;
  requiredCount: number;
} {
  return {
    definedCount: fields.length,
    requiredCount: fields.filter((field) => Boolean(field.required)).length
  };
}

export function getFlowFormFieldRuntimeKey(name: string): string {
  return name.trim();
}

export function getFlowFormFieldNameIssue(name: string): FlowFormFieldNameIssue | null {
  const normalized = getFlowFormFieldRuntimeKey(name);
  if (!normalized) return null;
  const key = normalized.toLowerCase();
  if (FORM_FIELD_NAMESPACE_HEADS.has(key)) return "namespace_head";
  if (PRIMARY_FLOW_INPUT_KEYS.has(key)) return "primary_input_key";
  if (FLOW_FORM_STEP_ALIAS_PATTERN.test(normalized)) return "step_alias";
  if (normalized.includes(".")) return "dot";
  return null;
}

export function isFlowFormFieldNameUsableAsVariable(name: string): boolean {
  const normalized = getFlowFormFieldRuntimeKey(name);
  return normalized.length > 0 && getFlowFormFieldNameIssue(normalized) === null;
}

export function isFlowFormFieldBareAliasSafe(name: string): boolean {
  const normalized = getFlowFormFieldRuntimeKey(name);
  if (!normalized || getFlowFormFieldNameIssue(normalized) !== null) return false;
  return !RESERVED_RUNTIME_VARIABLE_NAMES.has(normalized.toLowerCase());
}

export function getFlowFormFieldVariableToken(name: string): string {
  const expression = getFlowFormFieldVariableExpression(name);
  return expression ? `{{${expression}}}` : "";
}

export function getFlowFormFieldVariableExpression(name: string): string {
  const trimmed = getFlowFormFieldRuntimeKey(name);
  return isFlowFormFieldNameUsableAsVariable(trimmed) ? `flow_input.${trimmed}` : "";
}
