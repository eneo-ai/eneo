import type { components } from "@/lib/api/schema";

/**
 * The flow core's step and step-assistant shapes as the editor reads and
 * writes them. Everything comes from the generated API types; the editor's
 * own shapes (`StepConfig`, `AssistantConfig`) are normalised views of them
 * with `null` for every absent value, so a draft compares field by field.
 */

type Schemas = components["schemas"];

export type FlowPublic = Schemas["FlowPublic"];
export type FlowStep = Schemas["FlowStepPublic"];
export type StepPatch = Schemas["PartialFlowEditorStepPatch"];
export type FlowAssistant = Schemas["FlowAssistantPublic"];
export type AssistantUpdate = Schemas["FlowAssistantUpdateRequest"];
export type EditorUpdate = Schemas["FlowEditorUpdateRequest"];
export type InputSource = Schemas["FlowInputSource"];
export type InputType = Schemas["FlowInputType"];
export type OutputMode = Schemas["FlowOutputMode"];
export type OutputType = Schemas["FlowOutputType"];
export type ReviewPolicy = Schemas["FlowStepReviewPolicy"];
export type ModelKwargs = Schemas["ModelKwargs"];
export type Collection = Schemas["CollectionPublic"];
export type Website = Schemas["WebsitePublic"];
export type IntegrationKnowledge = Schemas["IntegrationKnowledgePublic"];
export type AttachmentFile = Schemas["FilePublic"];
export type ToolOption = Schemas["FlowToolOptionPublic"];
export type ToolOptions = Schemas["FlowToolOptionsPublic"];
export type TemplateAsset = Schemas["FlowTemplateAssetPublic"];
export type TemplateInspection = Schemas["FlowTemplateInspectionPublic"];
export type TemplatePlaceholder = Schemas["FlowTemplatePlaceholderPublic"];
export type ClassificationPreview = Schemas["FlowSecurityClassificationPreviewPublic"];
export type StepClassification = Schemas["FlowStepSecurityClassificationPublic"];
export type SecurityClassification = Schemas["SecurityClassificationPublic"];

export type JsonObject = Record<string, unknown>;

export function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** A copy of `value` when it is an object, else an empty object. */
export function objectOf(value: unknown): JsonObject {
  return isJsonObject(value) ? { ...value } : {};
}

/** The step fields the editor can change; identity and order stay the core's. */
export const EDITABLE_STEP_FIELDS = [
  "user_description",
  "input_source",
  "input_type",
  "input_contract",
  "input_bindings",
  "input_config",
  "output_mode",
  "output_type",
  "output_contract",
  "output_config",
  "output_classification_override",
  "review_policy",
  "timeout_seconds"
] as const;

export type EditableStepField = (typeof EDITABLE_STEP_FIELDS)[number];

/** One step's configuration, every absent value as null. */
export type StepConfig = {
  user_description: string | null;
  input_source: InputSource;
  input_type: InputType;
  input_contract: JsonObject | null;
  input_bindings: JsonObject | null;
  input_config: JsonObject | null;
  output_mode: OutputMode;
  output_type: OutputType;
  output_contract: JsonObject | null;
  output_config: JsonObject | null;
  output_classification_override: number | null;
  review_policy: ReviewPolicy | null;
  timeout_seconds: number | null;
};

export function stepConfigOf(step: FlowStep): StepConfig {
  return {
    user_description: step.user_description ?? null,
    input_source: step.input_source,
    input_type: step.input_type,
    input_contract: step.input_contract ?? null,
    input_bindings: step.input_bindings ?? null,
    input_config: step.input_config ?? null,
    output_mode: step.output_mode,
    output_type: step.output_type,
    output_contract: step.output_contract ?? null,
    output_config: step.output_config ?? null,
    output_classification_override: step.output_classification_override ?? null,
    review_policy: step.review_policy ?? null,
    timeout_seconds: step.timeout_seconds ?? null
  };
}

/** The step-assistant settings the editor can change, as the API lists them. */
export type AssistantConfig = {
  prompt: string;
  completion_model_id: string | null;
  completion_model_kwargs: ModelKwargs;
  groups: Collection[];
  websites: Website[];
  integration_knowledge_list: IntegrationKnowledge[];
  attachments: AttachmentFile[];
};

export type EditableAssistantField = keyof AssistantConfig;

export function assistantConfigOf(assistant: FlowAssistant): AssistantConfig {
  return {
    prompt: assistant.prompt?.text ?? "",
    completion_model_id: assistant.completion_model?.id ?? null,
    completion_model_kwargs: assistant.completion_model_kwargs ?? {},
    groups: assistant.groups ?? [],
    websites: assistant.websites ?? [],
    integration_knowledge_list: assistant.integration_knowledge_list ?? [],
    attachments: assistant.attachments ?? []
  };
}

/** JSON text with each object's keys sorted: the server's jsonb keeps no key order. */
function canonicalJson(value: unknown): string {
  return JSON.stringify(value ?? null, (_key, inner: unknown) =>
    isJsonObject(inner)
      ? Object.fromEntries(
          Object.entries(inner).sort(([left], [right]) =>
            left < right ? -1 : left > right ? 1 : 0
          )
        )
      : inner
  );
}

/** True when two values are stored as the same JSON, whatever order an object's keys come in. */
export function sameJson(left: unknown, right: unknown): boolean {
  return canonicalJson(left) === canonicalJson(right);
}

export function sortedIds(items: readonly { id: string }[]): string[] {
  return items.map((item) => item.id).sort();
}
