import {
  isJsonObject,
  objectOf,
  type InputType,
  type JsonObject,
  type OutputMode,
  type ReviewPolicy,
  type StepConfig
} from "./step-types";

/**
 * Readers and writers for the parts of a step's JSON configuration the editor
 * shows. Every writer starts from the stored object and changes only the keys
 * it owns, so settings the editor does not show (another mode's settings, a
 * key a newer core added) survive an edit. Ported from the reference editor
 * (apps/web `features/flows`), which is the behavioural reference.
 */

// ---------------------------------------------------------------------------
// Input bindings: the step's own text (`question`) and chosen results
// (`source_refs`). Together they are the step's "underlag" and replace what
// its input source would give.
// ---------------------------------------------------------------------------

export type SourceRef = {
  stepRef: string;
  output: "text" | "structured";
  fieldPath: string | null;
  /** The stored object, so keys the editor does not show (label, item_template) stay. */
  raw: JsonObject;
};

export type InputBindingsState =
  { status: "valid"; question: string; sourceRefs: SourceRef[] } | { status: "unsupported" };

const BINDING_KEYS = new Set(["question", "source_refs"]);
const STEP_REF = /^step_(\d+)$/;

export function readInputBindings(bindings: unknown): InputBindingsState {
  if (bindings === null || bindings === undefined) {
    return { status: "valid", question: "", sourceRefs: [] };
  }
  if (!isJsonObject(bindings)) return { status: "unsupported" };
  if (Object.keys(bindings).some((key) => !BINDING_KEYS.has(key))) {
    return { status: "unsupported" };
  }
  const question = bindings.question;
  if (question !== undefined && question !== null && typeof question !== "string") {
    return { status: "unsupported" };
  }
  const rawRefs = bindings.source_refs;
  if (rawRefs !== undefined && rawRefs !== null && !Array.isArray(rawRefs)) {
    return { status: "unsupported" };
  }
  const sourceRefs: SourceRef[] = [];
  for (const raw of (rawRefs as unknown[] | undefined) ?? []) {
    if (!isJsonObject(raw)) return { status: "unsupported" };
    const stepRef = typeof raw.step_ref === "string" ? raw.step_ref.trim() : "";
    const output = raw.output;
    if (!stepRef || (output !== "text" && output !== "structured")) {
      return { status: "unsupported" };
    }
    const fieldPath =
      typeof raw.field_path === "string" && raw.field_path.trim() ? raw.field_path.trim() : null;
    sourceRefs.push({ stepRef, output, fieldPath, raw });
  }
  return { status: "valid", question: typeof question === "string" ? question : "", sourceRefs };
}

/** The bindings for this question and these refs; null when both are empty. */
export function writeInputBindings(question: string, sourceRefs: SourceRef[]): JsonObject | null {
  const next: JsonObject = {};
  if (question.trim()) next.question = question;
  if (sourceRefs.length > 0) next.source_refs = sourceRefs.map((ref) => ref.raw);
  return Object.keys(next).length > 0 ? next : null;
}

export function sourceRefKey(ref: Pick<SourceRef, "stepRef" | "output" | "fieldPath">): string {
  return `${ref.stepRef}:${ref.output}:${ref.fieldPath ?? "*"}`;
}

export function newSourceRef(
  stepOrder: number,
  output: "text" | "structured",
  fieldPath: string | null
): SourceRef {
  const raw: JsonObject = { step_ref: `step_${stepOrder}`, output };
  if (fieldPath) raw.field_path = fieldPath;
  return { stepRef: `step_${stepOrder}`, output, fieldPath, raw };
}

export function sourceRefStepOrder(ref: Pick<SourceRef, "stepRef">): number | null {
  const match = STEP_REF.exec(ref.stepRef);
  return match ? Number(match[1]) : null;
}

/** True when the step has an underlag that replaces its input source. */
export function hasUnderlag(bindings: unknown): boolean {
  const state = readInputBindings(bindings);
  if (state.status !== "valid") return isJsonObject(bindings);
  return state.question.trim().length > 0 || state.sourceRefs.length > 0;
}

// ---------------------------------------------------------------------------
// Uploads when the flow runs: `input_config.runtime_input`.
// ---------------------------------------------------------------------------

export type RuntimeInputFormat = "document" | "audio" | "file";

export type RuntimeInput = {
  enabled: boolean;
  required: boolean;
  maxFiles: number | null;
  inputFormat: RuntimeInputFormat;
  label: string;
  description: string;
  acceptedMimetypes: string[];
};

export const FILE_INPUT_TYPES: ReadonlySet<InputType> = new Set(["document", "file", "audio"]);

export function readRuntimeInput(inputConfig: unknown): RuntimeInput {
  const raw = isJsonObject(inputConfig) ? inputConfig.runtime_input : undefined;
  const value = raw === true ? { enabled: true } : isJsonObject(raw) ? raw : {};
  const format = value.input_format;
  return {
    enabled: value.enabled === true,
    required: value.required === true,
    maxFiles:
      typeof value.max_files === "number" && value.max_files > 0
        ? Math.floor(value.max_files)
        : null,
    inputFormat: format === "audio" || format === "file" ? format : "document",
    label: typeof value.label === "string" ? value.label : "",
    description: typeof value.description === "string" ? value.description : "",
    acceptedMimetypes: Array.isArray(value.accepted_mimetypes_override)
      ? value.accepted_mimetypes_override.filter(
          (item): item is string => typeof item === "string" && item.trim().length > 0
        )
      : []
  };
}

export type RuntimeInputChange = Partial<{
  inputFormat: RuntimeInputFormat;
  acceptedMimetypes: string[];
  enabled: boolean;
  required: boolean;
  maxFiles: number | null;
  label: string;
  description: string;
}>;

/**
 * `input_config` with its upload settings changed. File-based steps keep their
 * input type as the upload format; text and JSON steps can choose it. Turning uploads off keeps the stored label,
 * description and limits (with `enabled: false`), so turning them on again
 * brings them back.
 */
export function withRuntimeInput(
  inputConfig: unknown,
  inputType: InputType,
  change: RuntimeInputChange
): JsonObject {
  const config = objectOf(inputConfig);
  const stored = config.runtime_input;
  const runtime: JsonObject = stored === true ? { enabled: true } : objectOf(stored);
  if (change.enabled !== undefined) runtime.enabled = change.enabled;
  if (change.required !== undefined) runtime.required = change.required;
  if (change.maxFiles !== undefined) {
    if (change.maxFiles === null) delete runtime.max_files;
    else runtime.max_files = change.maxFiles;
  }
  for (const [key, value] of [
    ["label", change.label],
    ["description", change.description]
  ] as const) {
    if (value === undefined) continue;
    if (value.trim()) runtime[key] = value;
    else delete runtime[key];
  }
  if (change.inputFormat !== undefined) runtime.input_format = change.inputFormat;
  if (change.acceptedMimetypes !== undefined) {
    if (change.acceptedMimetypes.length === 0) delete runtime.accepted_mimetypes_override;
    else runtime.accepted_mimetypes_override = [...change.acceptedMimetypes];
  }
  if (FILE_INPUT_TYPES.has(inputType)) runtime.input_format = inputType;
  if (runtime.enabled === undefined) runtime.enabled = false;
  if (runtime.required === undefined) runtime.required = false;
  config.runtime_input = runtime;
  return config;
}

// ---------------------------------------------------------------------------
// Reading mode: `input_config.text_processing`.
// ---------------------------------------------------------------------------

export type TextProcessingMode = "process_each_section" | "summarize";

export function readTextProcessingMode(inputConfig: unknown): TextProcessingMode | null {
  const mode = isJsonObject(inputConfig) ? objectOf(inputConfig.text_processing).mode : undefined;
  return mode === "process_each_section" || mode === "summarize" ? mode : null;
}

export function withTextProcessingMode(
  inputConfig: unknown,
  mode: TextProcessingMode | null
): JsonObject | null {
  const config = objectOf(inputConfig);
  if (mode === null) delete config.text_processing;
  else config.text_processing = { ...objectOf(config.text_processing), mode };
  return Object.keys(config).length > 0 ? config : null;
}

/**
 * Whether the step can read its material section by section: only an AI step
 * that passes its answer on in a fixed format and does not already run per
 * file or per item (the core's step_mapped_execution rule).
 */
export function textProcessingEligibility(
  step: Pick<StepConfig, "output_mode" | "output_type" | "input_config">
): "eligible" | "output" | "mapped" {
  if (step.output_mode !== "pass_through" || step.output_type !== "json") return "output";
  const config = objectOf(step.input_config);
  const runtime = objectOf(config.runtime_input);
  if (
    (runtime.enabled === true && runtime.execution_mode === "per_source") ||
    objectOf(config.item_map).enabled === true
  ) {
    return "mapped";
  }
  return "eligible";
}

// ---------------------------------------------------------------------------
// Long material: `input_config.long_material = {"mode": "digest"}`. Input
// larger than the step's model reads at once is read in segments; the model
// answers over notes made from them (`long_material.py`).
// ---------------------------------------------------------------------------

export function readLongMaterial(inputConfig: unknown): boolean {
  const value = isJsonObject(inputConfig) ? inputConfig.long_material : undefined;
  return isJsonObject(value) && value.mode === "digest";
}

export function withLongMaterial(inputConfig: unknown, on: boolean): JsonObject | null {
  const config = objectOf(inputConfig);
  if (on) config.long_material = { mode: "digest" };
  else delete config.long_material;
  return Object.keys(config).length > 0 ? config : null;
}

/**
 * Whether the core accepts long material on the step: a completion step
 * (`pass_through` or `http_post`) that does not read its material by
 * section, per item or per file (`step_mapped_execution.py`).
 */
export function longMaterialEligibility(
  step: Pick<StepConfig, "output_mode" | "input_config">
): "eligible" | "output" | "text_processing" | "mapped" {
  if (step.output_mode !== "pass_through" && step.output_mode !== "http_post") return "output";
  const config = objectOf(step.input_config);
  if (config.text_processing !== undefined && config.text_processing !== null) {
    return "text_processing";
  }
  const runtime = objectOf(config.runtime_input);
  if (
    (runtime.enabled === true && runtime.execution_mode === "per_source") ||
    objectOf(config.item_map).enabled === true
  ) {
    return "mapped";
  }
  return "eligible";
}

// ---------------------------------------------------------------------------
// HTTP: the authored config of `http_get` input and `http_post` output.
// Credentials are write-only: the API returns `{"$secret": "stored"}` for a
// stored secret, and sending the sentinel back keeps it.
// ---------------------------------------------------------------------------

export type SecretSentinel = { $secret: "stored" };
export type SecretValue = string | SecretSentinel;

export function isSecretSentinel(value: unknown): value is SecretSentinel {
  return isJsonObject(value) && value.$secret === "stored";
}

export type HttpAuthMode = "none" | "bearer_token" | "api_key" | "basic_auth";
export type HttpBodyMode = "auto" | "json_template" | "text_template" | "none";

export const HTTP_CONFIG_KEYS = [
  "url",
  "auth",
  "timeout_seconds",
  "body",
  "custom_headers",
  "response_format"
] as const;

export type HttpHeader = { name: string; value: SecretValue; secret: boolean };

export type HttpConfig = {
  url: string;
  auth:
    | { mode: "none" }
    | { mode: "bearer_token"; token: SecretValue }
    | { mode: "api_key"; header_name: string; key: SecretValue }
    | { mode: "basic_auth"; username: string; password: SecretValue };
  timeout_seconds: number;
  body: { mode: HttpBodyMode; template?: string | null };
  custom_headers: HttpHeader[];
  response_format: "text" | "json" | null;
};

export function defaultHttpConfig(direction: "input" | "output"): HttpConfig {
  return {
    url: "",
    auth: { mode: "none" },
    timeout_seconds: 30,
    body: { mode: direction === "output" ? "auto" : "none" },
    custom_headers: [],
    response_format: direction === "input" ? "text" : null
  };
}

function secretOf(value: unknown): SecretValue {
  if (typeof value === "string") return value;
  return isSecretSentinel(value) ? { $secret: "stored" } : "";
}

export function readHttpConfig(config: unknown, direction: "input" | "output"): HttpConfig {
  const defaults = defaultHttpConfig(direction);
  const record = objectOf(config);
  const auth = objectOf(record.auth);
  const body = objectOf(record.body);
  const bodyMode = body.mode;
  return {
    url: typeof record.url === "string" ? record.url : "",
    auth:
      auth.mode === "bearer_token"
        ? { mode: "bearer_token", token: secretOf(auth.token) }
        : auth.mode === "api_key"
          ? {
              mode: "api_key",
              header_name: typeof auth.header_name === "string" ? auth.header_name : "X-API-Key",
              key: secretOf(auth.key)
            }
          : auth.mode === "basic_auth"
            ? {
                mode: "basic_auth",
                username: typeof auth.username === "string" ? auth.username : "",
                password: secretOf(auth.password)
              }
            : { mode: "none" },
    timeout_seconds:
      typeof record.timeout_seconds === "number" && Number.isFinite(record.timeout_seconds)
        ? record.timeout_seconds
        : defaults.timeout_seconds,
    body: {
      mode:
        bodyMode === "auto" ||
        bodyMode === "json_template" ||
        bodyMode === "text_template" ||
        bodyMode === "none"
          ? bodyMode
          : defaults.body.mode,
      template: typeof body.template === "string" ? body.template : null
    },
    custom_headers: Array.isArray(record.custom_headers)
      ? record.custom_headers.flatMap((item) =>
          isJsonObject(item)
            ? [
                {
                  name: typeof item.name === "string" ? item.name : "",
                  value: secretOf(item.value),
                  secret: item.secret === true
                }
              ]
            : []
        )
      : [],
    response_format:
      record.response_format === "text" || record.response_format === "json"
        ? record.response_format
        : record.response_format === null
          ? null
          : defaults.response_format
  };
}

/** `config` with its HTTP keys replaced; the step's other keys stay. */
export function withHttpConfig(config: unknown, http: HttpConfig): JsonObject {
  const next = objectOf(config);
  next.url = http.url;
  next.auth = { ...http.auth };
  next.timeout_seconds = http.timeout_seconds;
  next.body =
    http.body.template === undefined || http.body.template === null
      ? { mode: http.body.mode }
      : { mode: http.body.mode, template: http.body.template };
  next.custom_headers = http.custom_headers.map((header) => ({ ...header }));
  next.response_format = http.response_format;
  return next;
}

/** True when the config already holds an authored HTTP config (an `auth` key). */
export function hasHttpConfig(config: unknown): boolean {
  return isJsonObject(config) && "auth" in config;
}

/** A local check of an authored URL, as the core's normalizer does it. */
export function httpUrlProblem(url: string): "missing" | "invalid" | null {
  const trimmed = url.trim();
  if (!trimmed) return "missing";
  const scheme = /^[A-Za-z][A-Za-z0-9+.-]*:/.exec(trimmed);
  if (scheme && !["http:", "https:"].includes(scheme[0].toLowerCase())) return "invalid";
  const separator = trimmed.indexOf("://");
  if (separator !== -1) {
    let authority = trimmed.slice(separator + 3);
    for (const end of ["/", "?", "#"]) {
      const index = authority.indexOf(end);
      if (index !== -1) authority = authority.slice(0, index);
    }
    if (authority.includes("@")) return "invalid";
  }
  if (trimmed.includes("{{")) return null;
  try {
    return ["http:", "https:"].includes(new URL(trimmed).protocol) ? null : "invalid";
  } catch {
    return "invalid";
  }
}

// ---------------------------------------------------------------------------
// Tool input: `input_config.tool` names one MCP tool and its arguments.
// ---------------------------------------------------------------------------

export type ToolConfig = {
  mcp_server_id: string;
  tool_id: string;
  arguments: JsonObject;
};

export function readToolConfig(inputConfig: unknown): ToolConfig | null {
  const stored = isJsonObject(inputConfig) ? inputConfig.tool : null;
  if (!isJsonObject(stored)) return null;
  const { mcp_server_id, tool_id } = stored;
  if (typeof mcp_server_id !== "string" || !mcp_server_id) return null;
  if (typeof tool_id !== "string" || !tool_id) return null;
  return {
    mcp_server_id,
    tool_id,
    arguments: isJsonObject(stored.arguments) ? stored.arguments : {}
  };
}

/**
 * `input_config` with its tool replaced, or removed for null. An editable
 * step stores exactly these three keys (the core refuses others), so the
 * tool object is written whole; the step's other input settings stay.
 */
export function withToolConfig(inputConfig: unknown, tool: ToolConfig | null): JsonObject | null {
  const next = objectOf(inputConfig);
  delete next.tool;
  if (tool) {
    next.tool = {
      mcp_server_id: tool.mcp_server_id,
      tool_id: tool.tool_id,
      arguments: tool.arguments
    };
  }
  return Object.keys(next).length > 0 ? next : null;
}

/** `arguments` with one argument set, or left out for undefined. */
export function withArgument(stored: JsonObject, name: string, value: unknown): JsonObject {
  const entries = Object.entries(stored).filter(([key]) => key !== name);
  return Object.fromEntries(value === undefined ? entries : [...entries, [name, value]]);
}

export type ToolArgumentSpec = {
  name: string;
  required: boolean;
  type: string | null;
  description: string | null;
  /** What the approved schema says about the value; shown to the author, never enforced here. */
  items: string | null;
  format: string | null;
  minimum: number | null;
  maximum: number | null;
  default: unknown;
};

/** The arguments a tool's approved input schema declares, required first. */
export function toolArguments(inputSchema: unknown): ToolArgumentSpec[] {
  const schema = objectOf(inputSchema);
  const properties = objectOf(schema.properties);
  const required = new Set(
    Array.isArray(schema.required)
      ? schema.required.filter((item): item is string => typeof item === "string")
      : []
  );
  return Object.entries(properties)
    .map(([name, property]) => {
      const spec = objectOf(property);
      return {
        name,
        required: required.has(name),
        type: typeof spec.type === "string" ? spec.type : null,
        description: typeof spec.description === "string" ? spec.description : null,
        items:
          typeof objectOf(spec.items).type === "string"
            ? (objectOf(spec.items).type as string)
            : null,
        format: typeof spec.format === "string" ? spec.format : null,
        minimum: typeof spec.minimum === "number" ? spec.minimum : null,
        maximum: typeof spec.maximum === "number" ? spec.maximum : null,
        default: spec.default
      };
    })
    .sort((left, right) => Number(right.required) - Number(left.required));
}

/** An argument's stored value as the text a field shows: a string as is, else JSON. */
export function argumentText(value: unknown): string {
  if (value === undefined) return "";
  return typeof value === "string" ? value : JSON.stringify(value);
}

/**
 * What a field's text stores for an argument of `type`: a string argument
 * keeps the text, others read it as JSON (a number, a list, true), and empty
 * text leaves the argument out. A reference (`{{…}}`) is always text.
 */
export function argumentValue(
  text: string,
  type: string | null
): { ok: true; value: unknown } | { ok: false } {
  if (!text.trim()) return { ok: true, value: undefined };
  if (type === "string" || text.trim().startsWith("{{")) return { ok: true, value: text };
  try {
    return { ok: true, value: JSON.parse(text) };
  } catch {
    return type === null ? { ok: true, value: text } : { ok: false };
  }
}

// ---------------------------------------------------------------------------
// Word template fill: `output_config` holds the template and its bindings.
// ---------------------------------------------------------------------------

export type TemplateFillConfig = {
  templateAssetId: string | null;
  templateName: string | null;
  placeholders: string[];
  bindings: Record<string, string>;
};

export function readTemplateFill(outputConfig: unknown): TemplateFillConfig {
  const config = objectOf(outputConfig);
  return {
    templateAssetId: typeof config.template_asset_id === "string" ? config.template_asset_id : null,
    templateName: typeof config.template_name === "string" ? config.template_name : null,
    placeholders: Array.isArray(config.placeholders)
      ? config.placeholders.filter((item): item is string => typeof item === "string")
      : [],
    bindings: Object.fromEntries(
      Object.entries(objectOf(config.bindings)).filter(
        (entry): entry is [string, string] => typeof entry[1] === "string"
      )
    )
  };
}

/**
 * `output_config` with the chosen template: its id, name and placeholders.
 * Bindings of placeholders it still has stay; a new template drops the
 * checksum of the old one, which publish takes from the asset.
 */
export function withTemplate(
  outputConfig: unknown,
  template: { assetId: string; name: string; placeholders: string[] } | null
): JsonObject | null {
  const next = objectOf(outputConfig);
  const sameTemplate = template !== null && next.template_asset_id === template.assetId;
  if (!sameTemplate) delete next.template_checksum;
  if (template === null) {
    delete next.template_asset_id;
    delete next.template_file_id;
    delete next.template_name;
    next.placeholders = [];
    next.bindings = {};
  } else {
    next.template_asset_id = template.assetId;
    next.template_name = template.name;
    next.placeholders = template.placeholders;
    next.bindings = Object.fromEntries(
      Object.entries(objectOf(next.bindings)).filter(([name]) =>
        template.placeholders.includes(name)
      )
    );
  }
  return next;
}

/** `output_config` with one placeholder's binding set, or removed for null. */
export function withTemplateBinding(
  outputConfig: unknown,
  placeholder: string,
  expression: string | null
): JsonObject {
  const next = objectOf(outputConfig);
  const bindings = objectOf(next.bindings);
  if (expression === null) delete bindings[placeholder];
  else bindings[placeholder] = expression;
  next.bindings = bindings;
  return next;
}

/** A whole output object, which the renderer refuses for one placeholder. */
export function isStructuredTemplateBinding(binding: string): boolean {
  return /^\s*\{\{\s*(?:step_\d+\.output(?:\.structured)?|flow_input|flow\.input)\s*\}\}\s*$/.test(
    binding
  );
}

// ---------------------------------------------------------------------------
// Speaker mapping: `output_config.speaker_mapping`.
// ---------------------------------------------------------------------------

export type SpeakerMapping = {
  participantsField: string | null;
  speakerCountField: string | null;
  inferNames: boolean;
};

export function readSpeakerMapping(outputConfig: unknown): SpeakerMapping {
  const block = objectOf(objectOf(outputConfig).speaker_mapping);
  const field = (key: string) => {
    const value = block[key];
    return typeof value === "string" && value.trim() ? value : null;
  };
  return {
    participantsField: field("participants_field"),
    speakerCountField: field("speaker_count_field"),
    inferNames: block.infer_names === true
  };
}

export function withSpeakerMapping(outputConfig: unknown, mapping: SpeakerMapping): JsonObject {
  const next = objectOf(outputConfig);
  next.speaker_mapping = {
    ...objectOf(next.speaker_mapping),
    participants_field: mapping.participantsField,
    speaker_count_field: mapping.speakerCountField,
    infer_names: mapping.inferNames
  };
  return next;
}

// ---------------------------------------------------------------------------
// Citations and the retrieval policy: both only for AI-written output.
// ---------------------------------------------------------------------------

export function outputModeUsesCompletionModel(mode: OutputMode): boolean {
  return mode === "pass_through" || mode === "http_post" || mode === "speaker_mapping";
}

export function supportsCitations(step: Pick<StepConfig, "output_type" | "output_mode">): boolean {
  return step.output_type === "text" && outputModeUsesCompletionModel(step.output_mode);
}

export function readCitationsOn(outputConfig: unknown): boolean {
  return objectOf(outputConfig).citation_mode === "inline_inref_sidecar";
}

export function withCitations(outputConfig: unknown, on: boolean): JsonObject | null {
  const next = objectOf(outputConfig);
  if (on) next.citation_mode = "inline_inref_sidecar";
  else delete next.citation_mode;
  return Object.keys(next).length > 0 ? next : null;
}

export type RetrievalPolicyMode = "best_effort" | "fail_closed";

/** The core accepts a retrieval policy only where a model answers with knowledge. */
export function supportsRetrievalPolicy(mode: OutputMode): boolean {
  return mode === "pass_through" || mode === "http_post";
}

export function readRetrievalPolicy(outputConfig: unknown): RetrievalPolicyMode | null {
  const mode = objectOf(objectOf(outputConfig).retrieval_policy).mode;
  return mode === "best_effort" || mode === "fail_closed" ? mode : null;
}

export function withRetrievalPolicy(
  outputConfig: unknown,
  mode: RetrievalPolicyMode | null
): JsonObject | null {
  const next = objectOf(outputConfig);
  if (mode === null) delete next.retrieval_policy;
  else next.retrieval_policy = { version: 1, mode };
  return Object.keys(next).length > 0 ? next : null;
}

// ---------------------------------------------------------------------------
// Review after the step.
// ---------------------------------------------------------------------------

export type ReviewChoice = "none" | "view" | "edit";

export function reviewChoiceOf(policy: ReviewPolicy | null): ReviewChoice {
  return policy?.mode === "view" || policy?.mode === "edit" ? policy.mode : "none";
}

/** The policy for a choice; a stored expiry stays when only the mode changes. */
export function withReviewChoice(
  policy: ReviewPolicy | null,
  choice: ReviewChoice
): ReviewPolicy | null {
  if (choice === "none") return null;
  return { ...(policy ?? {}), mode: choice };
}

export function withReviewExpiry(
  policy: ReviewPolicy | null,
  seconds: number | null
): ReviewPolicy | null {
  if (!policy) return null;
  const next: ReviewPolicy = { ...policy };
  if (seconds === null) delete next.expires_after_seconds;
  else next.expires_after_seconds = seconds;
  return next;
}

/** Review cannot follow a step that sends its result away over HTTP. */
export function reviewSupported(mode: OutputMode): boolean {
  return mode !== "http_post";
}

/** A speaker mapping is always reviewed and edited by a person. */
export function reviewLocked(mode: OutputMode): boolean {
  return mode === "speaker_mapping";
}
