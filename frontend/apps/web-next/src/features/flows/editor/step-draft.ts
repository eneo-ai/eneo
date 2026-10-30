import {
  filterSupportedKwargs,
  type ModelWithKwargs
} from "@/features/assistants/editor/model-kwargs";
import { tokensOf } from "../flow-steps";
import { readRuntimeInput } from "./step-configs";
import {
  EDITABLE_STEP_FIELDS,
  objectOf,
  sameJson,
  sortedIds,
  stepConfigOf,
  type AssistantConfig,
  type AssistantUpdate,
  type EditorUpdate,
  type FlowAssistant,
  type FlowPublic,
  type FlowStep,
  type JsonObject,
  type StepConfig,
  type StepPatch
} from "./step-types";

/**
 * The editor's draft is the saved step and step assistant plus the user's
 * edits, kept as overrides of whole fields. A save sends the fields whose
 * draft value differs from the saved one and nothing else; a field the user
 * changed back is not sent. Every JSON field is edited from its stored
 * object, so keys the editor does not show stay in what is sent. Rebasing
 * onto a newer revision (after `stale_revision`) keeps the overrides and
 * puts them on top of the newer saved values.
 */

export type StepEdits = Partial<StepConfig>;
export type AssistantEdits = Partial<AssistantConfig>;

export function draftStep(saved: StepConfig, edits: StepEdits): StepConfig {
  return { ...saved, ...edits };
}

export function draftAssistant(saved: AssistantConfig, edits: AssistantEdits): AssistantConfig {
  return { ...saved, ...edits };
}

/** The sparse step patch: only the fields whose draft differs from the saved step. */
export function stepChanges(saved: StepConfig, draft: StepConfig): StepPatch | null {
  const changes: JsonObject = {};
  for (const field of EDITABLE_STEP_FIELDS) {
    if (!sameJson(saved[field], draft[field])) changes[field] = draft[field];
  }
  return Object.keys(changes).length > 0 ? (changes as StepPatch) : null;
}

/**
 * The sparse assistant update. Model settings are one field: when the user
 * changed them, or chose a model that supports fewer of them, the whole
 * object the chosen model supports is sent (the core keeps only those);
 * settings the user did not touch are not sent for a model that keeps them.
 */
export function assistantChanges(
  saved: AssistantConfig,
  draft: AssistantConfig,
  options: {
    promptDescription?: string | null;
    models?: readonly (ModelWithKwargs & { id: string })[];
  } = {}
): AssistantUpdate | null {
  const changes: AssistantUpdate = {};
  if (saved.prompt !== draft.prompt) {
    changes.prompt = { text: draft.prompt, description: options.promptDescription ?? null };
  }
  const modelChanged = saved.completion_model_id !== draft.completion_model_id;
  if (modelChanged && draft.completion_model_id) {
    changes.completion_model = { id: draft.completion_model_id };
  }
  if (modelChanged || !sameJson(saved.completion_model_kwargs, draft.completion_model_kwargs)) {
    const model = options.models?.find((candidate) => candidate.id === draft.completion_model_id);
    const kwargs = model
      ? filterSupportedKwargs(draft.completion_model_kwargs, model)
      : draft.completion_model_kwargs;
    if (!sameJson(saved.completion_model_kwargs, kwargs)) changes.completion_model_kwargs = kwargs;
  }
  for (const field of [
    "groups",
    "websites",
    "integration_knowledge_list",
    "attachments"
  ] as const) {
    if (!sameJson(sortedIds(saved[field]), sortedIds(draft[field]))) {
      changes[field] = draft[field].map((item) => ({ id: item.id }));
    }
  }
  return Object.keys(changes).length > 0 ? changes : null;
}

/** Whether the draft takes audio, which the core transcribes only when the flow turns it on. */
export function takesAudio(
  step: Pick<StepConfig, "input_source" | "input_type" | "input_config">
): boolean {
  if (step.input_source === "flow_input" && step.input_type === "audio") return true;
  const runtime = readRuntimeInput(step.input_config);
  return runtime.enabled && runtime.inputFormat === "audio";
}

export function transcriptionEnabled(metadata: unknown): boolean {
  return objectOf(objectOf(metadata).wizard).transcription_enabled === true;
}

/**
 * The flow metadata with transcription turned on, for a save that adds the
 * flow's first audio step: the core refuses an audio step otherwise. The model
 * and language stay the flow settings' to choose.
 */
export function withTranscriptionEnabled(metadata: unknown): JsonObject {
  const next = objectOf(metadata);
  next.wizard = { ...objectOf(next.wizard), transcription_enabled: true };
  return next;
}

/** One revision-fenced editor update for one step and its assistant. */
export function buildEditorUpdate(params: {
  flow: FlowPublic;
  stepId: string;
  stepPatch: StepPatch | null;
  assistantId: string;
  assistantUpdate: AssistantUpdate | null;
  draft: StepConfig;
}): EditorUpdate {
  const { flow, stepId, stepPatch, assistantId, assistantUpdate, draft } = params;
  const update: EditorUpdate = { expected_revision: flow.draft_revision, definition: {} };
  if (stepPatch) update.step_edits = [{ step_id: stepId, changes: stepPatch }];
  // Naming the step gives it its own copy when other steps share the assistant.
  if (assistantUpdate)
    update.assistants = [{ assistant_id: assistantId, step_id: stepId, changes: assistantUpdate }];
  if (stepPatch && takesAudio(draft) && !transcriptionEnabled(flow.metadata_json)) {
    update.definition = { metadata_json: withTranscriptionEnabled(flow.metadata_json) };
  }
  return update;
}

type StepUpdateRequest = Omit<FlowStep, "created_at" | "updated_at"> & { assistant_id: string };

/** A step as a full update would send it: the fields a flow update accepts. */
function updateRequestOf(
  step: FlowStep,
  config: StepConfig = stepConfigOf(step)
): StepUpdateRequest {
  return {
    id: step.id ?? null,
    assistant_id: step.assistant_id,
    step_order: step.step_order,
    ...config
  };
}

/** The references a prompt reads, as a text of them alone. */
function promptReads(prompt: string): string {
  return tokensOf(prompt)
    .map((token) => `{{${token}}}`)
    .join(" ");
}

/**
 * The classification preview of the draft: every step as saved with this
 * step's draft in place, and the assistant's model, knowledge and prompt as
 * drafted. The assistant change names the step, as the save does, so a step
 * that shares its assistant is explained with its own copy and the other
 * steps with the assistant as saved. The rule reads the prompt only for the
 * steps it refers to, so the preview sends those references alone: typing
 * prose asks nothing, a new or removed reference asks again.
 */
export function classificationPreviewRequest(params: {
  flow: FlowPublic;
  stepId: string;
  draft: StepConfig;
  assistantId: string;
  assistant: AssistantConfig | null;
  savedAssistant: AssistantConfig | null;
}) {
  const { flow, stepId, draft, assistantId, assistant, savedAssistant } = params;
  const steps = flow.steps.map((step) =>
    step.id === stepId ? updateRequestOf(step, draft) : updateRequestOf(step)
  );
  const update: AssistantUpdate = {};
  if (assistant && savedAssistant) {
    const reads = promptReads(assistant.prompt);
    if (reads !== promptReads(savedAssistant.prompt)) {
      update.prompt = { text: reads, description: null };
    }
    if (
      assistant.completion_model_id &&
      assistant.completion_model_id !== savedAssistant.completion_model_id
    ) {
      update.completion_model = { id: assistant.completion_model_id };
    }
    for (const field of ["groups", "websites", "integration_knowledge_list"] as const) {
      if (!sameJson(sortedIds(savedAssistant[field]), sortedIds(assistant[field]))) {
        update[field] = assistant[field].map((item) => ({ id: item.id }));
      }
    }
  }
  return {
    steps: steps as never,
    assistants:
      Object.keys(update).length > 0 ? [{ assistant_id: assistantId, step_id: stepId, update }] : []
  };
}

/** The classification preview of the draft as saved: every step, no assistant changes. */
export function savedFlowPreviewRequest(flow: FlowPublic) {
  return { steps: flow.steps.map((step) => updateRequestOf(step)) as never, assistants: [] };
}

/** The edits that still change something on top of `saved`, for "N changes" and rebasing. */
export function changedStepFields(saved: StepConfig, edits: StepEdits): (keyof StepConfig)[] {
  return (Object.keys(edits) as (keyof StepConfig)[]).filter(
    (field) => !sameJson(saved[field], edits[field])
  );
}

export function findStep(flow: FlowPublic, stepId: string): FlowStep | null {
  return flow.steps.find((step) => step.id === stepId) ?? null;
}

/** The step before this one in the flow, by order. */
export function previousStepOf(
  flow: FlowPublic,
  step: Pick<FlowStep, "step_order">
): FlowStep | null {
  return flow.steps.find((candidate) => candidate.step_order === step.step_order - 1) ?? null;
}

export function isLastStep(flow: FlowPublic, step: Pick<FlowStep, "step_order">): boolean {
  return flow.steps.every((candidate) => candidate.step_order <= step.step_order);
}

export function promptDescriptionOf(assistant: FlowAssistant | null | undefined): string | null {
  return assistant?.prompt?.description ?? null;
}
