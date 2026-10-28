/**
 * The flow's run form (`metadata_json.form_schema.fields`), its evidence
 * export switch (`metadata_json.evidence_policy.allow_export`) and its care
 * data policy (`metadata_json.care_data_policy`), as the reference editor
 * reads and writes them (`flowFormSchema.ts`, `flowEvidencePolicy.ts`,
 * `flowCareDataPolicy.ts` in apps/web). Pure and unit-tested.
 */

export const FORM_FIELD_TYPES = [
  "text",
  "number",
  "date",
  "select",
  "multiselect",
  "list"
] as const;
export type FormFieldType = (typeof FORM_FIELD_TYPES)[number];

/**
 * What a field's value is to the run besides an input: its name (a text field)
 * or its day (a date field). Eneo names and dates each run by them, in the
 * run lists and in the names of the documents it generates.
 */
export type FormFieldRole = "run_label" | "run_date";
const ROLE_OF_TYPE: Partial<Record<FormFieldType, FormFieldRole>> = {
  text: "run_label",
  date: "run_date"
};

/** The role a field of this type can hold, if any. */
export function roleFor(type: FormFieldType): FormFieldRole | undefined {
  return ROLE_OF_TYPE[type];
}

/** A form field while it is edited; `key` tells rows apart while names change. */
export type FormFieldDraft = {
  key: string;
  name: string;
  label: string;
  type: FormFieldType;
  required: boolean;
  options: string[];
  /** The author typed the name; until then it follows the label. */
  nameEdited: boolean;
  role?: FormFieldRole;
};

/** A form field as the flow stores it. */
export type PersistedFormField = {
  name: string;
  label: string;
  type: FormFieldType;
  required: boolean;
  order: number;
  options?: string[];
  role?: FormFieldRole;
};

type Metadata = Record<string, unknown> | null | undefined;

/** Older flows stored these; they are plain text fields. */
const LEGACY_TEXT_TYPES = new Set(["email", "textarea", "string"]);
const OPTION_TYPES = new Set<FormFieldType>(["select", "multiselect"]);
/** Names a step reads in another way; a field cannot take them. */
const NAMESPACE_HEADS = new Set(["flow", "flow_input", "step_input"]);
const RESERVED_INPUT_KEYS = new Set([
  "expected_flow_version",
  "file_ids",
  "json",
  "max_speakers",
  "speaker_labels",
  "step_inputs",
  "structured",
  "text",
  "transcribed_text",
  "transcript",
  "transcript_regeneration",
  "transcription",
  "transkribering"
]);
const STEP_ALIAS = /^step_\d+($|[._])/i;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function hasOptions(type: FormFieldType): boolean {
  return OPTION_TYPES.has(type);
}

function normalizedType(value: unknown): FormFieldType {
  if (typeof value !== "string") return "text";
  if (LEGACY_TEXT_TYPES.has(value)) return "text";
  return (FORM_FIELD_TYPES as readonly string[]).includes(value)
    ? (value as FormFieldType)
    : "text";
}

/** The run form's fields, in their order. */
export function formFieldsOf(metadata: Metadata): FormFieldDraft[] {
  const schema = isRecord(metadata?.form_schema) ? metadata.form_schema : {};
  const fields = Array.isArray(schema.fields) ? schema.fields.filter(isRecord) : [];
  return fields
    .map((field, index) => ({ field, index }))
    .sort(
      (a, b) =>
        (typeof a.field.order === "number" ? a.field.order : a.index + 1) -
        (typeof b.field.order === "number" ? b.field.order : b.index + 1)
    )
    .map(({ field }, index) => {
      const name = typeof field.name === "string" ? field.name.trim() : "";
      const label = typeof field.label === "string" ? field.label.trim() : "";
      const type = normalizedType(field.type);
      const role = roleFor(type) === field.role ? roleFor(type) : undefined;
      return {
        key: `saved-${index}`,
        name,
        label: label || name,
        type,
        required: field.required === true,
        options: Array.isArray(field.options)
          ? field.options.flatMap((option) =>
              typeof option === "string" && option.trim() ? [option.trim()] : []
            )
          : [],
        nameEdited: true,
        ...(role ? { role } : {})
      };
    });
}

/** The fields as the flow stores them: trimmed, numbered, options only where they apply. */
export function persistedFormFields(fields: readonly FormFieldDraft[]): PersistedFormField[] {
  return fields.map((field, index) => {
    const name = field.name.trim();
    const persisted: PersistedFormField = {
      name,
      label: field.label.trim() || name,
      type: field.type,
      required: field.required,
      order: index + 1
    };
    if (hasOptions(field.type)) {
      persisted.options = field.options.map((option) => option.trim()).filter(Boolean);
    }
    if (field.role && roleFor(field.type) === field.role) persisted.role = field.role;
    return persisted;
  });
}

/** `fields` with `next` in place of its row; a role it takes leaves the field that had it. */
export function withFieldChanged(
  fields: readonly FormFieldDraft[],
  next: FormFieldDraft
): FormFieldDraft[] {
  return fields.map((field) => {
    if (field.key === next.key) return next;
    if (next.role && field.role === next.role) return { ...field, role: undefined };
    return field;
  });
}

/**
 * The saved fields the edit renames, from the saved name to the new one, for
 * `form_field_renames`: the core then moves the steps' reads of each field
 * along with it. A row is the same field while its `key` stays.
 */
export function renamedFormFields(
  saved: readonly FormFieldDraft[],
  fields: readonly FormFieldDraft[]
): Record<string, string> {
  const savedNames = new Map(saved.map((field) => [field.key, field.name.trim()]));
  const renames: Record<string, string> = {};
  for (const field of fields) {
    const before = savedNames.get(field.key);
    const after = field.name.trim();
    if (before && after && before !== after) renames[before] = after;
  }
  return renames;
}

export type FieldNameIssue = "namespace_head" | "reserved" | "step_alias" | "dot";

export function fieldNameIssue(name: string): FieldNameIssue | null {
  const trimmed = name.trim();
  const key = trimmed.toLowerCase();
  if (!trimmed) return null;
  if (NAMESPACE_HEADS.has(key)) return "namespace_head";
  if (RESERVED_INPUT_KEYS.has(key)) return "reserved";
  if (STEP_ALIAS.test(trimmed)) return "step_alias";
  if (trimmed.includes(".")) return "dot";
  return null;
}

/** A technical name made from the label, unused among `existing` (case does not count). */
export function suggestedFieldName(label: string, existing: readonly string[]): string {
  const taken = new Set(existing.map((name) => name.trim().toLowerCase()).filter(Boolean));
  const raw =
    label
      .trim()
      .normalize("NFKC")
      .toLowerCase()
      .replace(/\s+/g, "_")
      .replace(/[^\p{L}\p{N}_]+/gu, "_")
      .replace(/_+/g, "_")
      .replace(/^_+|_+$/g, "") || "field";
  const base = fieldNameIssue(raw) === null ? raw : `user_${raw}`;
  let candidate = fieldNameIssue(base) === null ? base : "user_field";
  for (let suffix = 2; taken.has(candidate.toLowerCase()); suffix += 1) {
    candidate = `${base}_${suffix}`;
  }
  return candidate;
}

export type FormFieldProblem =
  | { key: string; part: "name"; problem: "required" | "duplicate" | FieldNameIssue }
  | { key: string; part: "options"; problem: "options_required" };

/** What keeps the fields from being saved, at the field and part it concerns. */
export function formFieldProblems(fields: readonly FormFieldDraft[]): FormFieldProblem[] {
  const problems: FormFieldProblem[] = [];
  const seen = new Set<string>();
  for (const field of fields) {
    const name = field.name.trim();
    const issue = fieldNameIssue(name);
    if (!name) problems.push({ key: field.key, part: "name", problem: "required" });
    else if (issue) problems.push({ key: field.key, part: "name", problem: issue });
    else if (seen.has(name.toLowerCase())) {
      problems.push({ key: field.key, part: "name", problem: "duplicate" });
    }
    seen.add(name.toLowerCase());
    if (hasOptions(field.type) && !field.options.some((option) => option.trim())) {
      problems.push({ key: field.key, part: "options", problem: "options_required" });
    }
  }
  return problems;
}

/** Only an explicit yes allows exporting run evidence. */
export function evidenceExportAllowed(metadata: Metadata): boolean {
  const policy = isRecord(metadata?.evidence_policy) ? metadata.evidence_policy : {};
  return policy.allow_export === true;
}

/**
 * A sensitive flow whose material only the uploader and the reviewers may
 * handle until its result is approved.
 */
export function restrictedBeforeApproval(metadata: Metadata): boolean {
  const policy = isRecord(metadata?.care_data_policy) ? metadata.care_data_policy : {};
  return policy.sensitive === true && policy.pre_approval_visibility === "uploader_and_reviewers";
}

/**
 * The flow's metadata with the edited form and export switch; everything else
 * in it (transcription settings, the builder's origin) is kept as it is.
 */
export function metadataWithSettings(
  metadata: Metadata,
  fields: readonly FormFieldDraft[],
  allowExport: boolean
): Record<string, unknown> {
  const next: Record<string, unknown> = { ...(metadata ?? {}) };
  const schema = isRecord(next.form_schema) ? next.form_schema : null;
  if (fields.length > 0 || schema) {
    next.form_schema = { ...schema, fields: persistedFormFields(fields) };
  }
  const policy = isRecord(next.evidence_policy) ? next.evidence_policy : null;
  if (allowExport || policy) next.evidence_policy = { ...policy, allow_export: allowExport };
  return next;
}
