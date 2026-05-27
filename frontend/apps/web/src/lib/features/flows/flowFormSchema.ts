import flowVariableDefinitions from "./flowVariableDefinitions.generated.json";

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
  label?: string | null;
  type: FlowFormFieldType | string;
  required?: boolean;
  options?: string[];
  order?: number;
};

export type FlowFormFieldInput = {
  name: string;
  label?: string | null;
  type?: FlowFormFieldType | string | null;
  required?: boolean | null;
  options?: string[] | null;
  order?: number | null;
};

export type FlowFormSchemaMetadata = {
  fields: FlowFormField[];
};

export type NormalizedFlowFormFieldType = "text" | "number" | "date" | "select" | "multiselect";

export type NormalizedFlowFormField = {
  name: string;
  label: string;
  type: NormalizedFlowFormFieldType;
  required: boolean;
  options: string[];
  order: number;
};

const LEGACY_TEXT_TYPES = new Set(["email", "textarea", "string"]);
const OPTION_FIELD_TYPES = new Set<NormalizedFlowFormFieldType>(["select", "multiselect"]);
const RESERVED_RUNTIME_VARIABLE_NAMES = new Set(flowVariableDefinitions.reservedRuntimeVariables);
const FORM_FIELD_NAMESPACE_HEADS = new Set(flowVariableDefinitions.formFieldNamespaceHeads);
export const PRIMARY_FLOW_INPUT_KEYS = new Set(flowVariableDefinitions.primaryFlowInputKeys);
const FLOW_FORM_STEP_ALIAS_PATTERN = /^step_\d+($|[._])/i;

export type FlowFormFieldNameIssue = "namespace_head" | "primary_input_key" | "step_alias" | "dot";

export function normalizeFlowFormFieldType(
  type: FlowFormFieldType | string | null | undefined
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
  type: FlowFormFieldType | string | null | undefined
): boolean {
  return OPTION_FIELD_TYPES.has(normalizeFlowFormFieldType(type));
}

export function normalizeFlowFormFields(
  fields: ReadonlyArray<FlowFormFieldInput>
): NormalizedFlowFormField[] {
  return [...fields]
    .map((field, index) => ({
      name: typeof field.name === "string" ? field.name : "",
      label: getFlowFormFieldLabel(field),
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
    const name = getFlowFormFieldRuntimeKey(field.name);
    const normalized: FlowFormField = {
      name,
      label: getFlowFormFieldLabel(field),
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

export function getFlowFormSchemaSignature(fields: ReadonlyArray<FlowFormFieldInput>): string {
  return JSON.stringify(
    toPersistedFlowFormFields(normalizeFlowFormFields(fields)).map((field) => [
      field.order,
      field.name,
      field.label ?? "",
      field.type,
      Boolean(field.required),
      field.options ?? []
    ])
  );
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

export function getFlowFormFieldLabel(
  field: Pick<FlowFormField, "name"> & { label?: string | null }
): string {
  const label = typeof field.label === "string" ? field.label.trim() : "";
  return label || getFlowFormFieldRuntimeKey(field.name);
}

export function getSuggestedFlowFormFieldRuntimeKey(
  label: string,
  existingNames: string[] = []
): string {
  const existing = new Set(
    existingNames
      .map((name) => getFlowFormFieldRuntimeKey(name).toLowerCase())
      .filter((name) => name.length > 0)
  );
  const rawBase =
    label
      .trim()
      .normalize("NFKC")
      .toLowerCase()
      .replace(/\s+/g, "_")
      .replace(/[^\p{L}\p{N}_]+/gu, "_")
      .replace(/_+/g, "_")
      .replace(/^_+|_+$/g, "") || "field";
  const base = getFlowFormFieldNameIssue(rawBase) === null ? rawBase : `user_${rawBase}`;
  let candidate = getFlowFormFieldNameIssue(base) === null ? base : "user_field";
  let suffix = 2;
  while (existing.has(candidate.toLowerCase())) {
    candidate = `${base}_${suffix}`;
    suffix += 1;
  }
  return candidate;
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
