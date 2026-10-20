/**
 * The flow models as the generated schema has them
 * (`backend/src/eneo/flows/{definition,flow_models}.py`), under the names
 * the components use. `FlowDefinition` lists its form fields and steps as
 * optional (Pydantic defaults); read them through `formFieldsOf` / `stepsOf`.
 */
import type { Schema } from "@/lib/api/models";

export type FormFieldType = Schema<"FormFieldType">;
export type FormField = Schema<"FormField">;
export type StepKind = Schema<"StepKind">;
export type LlmOutput = Schema<"TextOutput"> | Schema<"JsonOutput">;
export type StepKnowledge = Schema<"StepKnowledge">;
export type LlmStep = Schema<"LlmStep">;
export type ComposeStep = Schema<"ComposeStep">;
export type DocumentFormat = Schema<"DocumentFormat">;
export type DocumentStep = Schema<"DocumentStep">;
export type ReviewMode = Schema<"ReviewMode">;
export type ReviewStep = Schema<"ReviewStep">;
export type SpeakerMapping = Schema<"SpeakerMapping">;
export type TranscribeStep = Schema<"TranscribeStep">;
export type FlowStep = LlmStep | ComposeStep | DocumentStep | ReviewStep | TranscribeStep;
export type FlowDefinition = Schema<"FlowDefinition">;

export type FlowRunStatus = Schema<"FlowRunStatus">;
export type StepResultStatus = Schema<"StepResultStatus">;
export type ReviewCheckpointState = Schema<"ReviewCheckpointState">;
export type PrincipalType = Schema<"PrincipalType">;

export type FlowSparsePublic = Schema<"FlowSparsePublic">;
export type FlowPublic = Schema<"FlowPublic">;
export type FlowAuthoringAssistantPublic = Schema<"FlowAuthoringAssistantPublic">;
export type FlowRunContractPublic = Schema<"FlowRunContractPublic">;
export type FlowRunCreateRequest = Schema<"FlowRunCreateRequest">;
export type FlowRunErrorPublic = Schema<"FlowRunErrorPublic">;
export type FlowRunFilePublic = Schema<"FlowRunFilePublic">;
export type FlowRunSummaryPublic = Schema<"FlowRunSummaryPublic">;
export type FlowRunStepPublic = Schema<"FlowRunStepPublic">;
export type FlowRunReviewCheckpointPublic = Schema<"FlowRunReviewCheckpointPublic">;
export type FlowRunPublic = Schema<"FlowRunPublic">;
export type FlowRunReviewCheckpointResumeResponse = Schema<"FlowRunReviewCheckpointResumeResponse">;

const NO_FIELDS: FormField[] = [];
const NO_STEPS: FlowStep[] = [];

/** The run inputs a definition asks for (an empty list when it has none). */
export function formFieldsOf(definition: FlowDefinition): FormField[] {
  return definition.form_fields ?? NO_FIELDS;
}

/** The steps of a definition, in run order (an empty list when it has none). */
export function stepsOf(definition: FlowDefinition): FlowStep[] {
  return definition.steps ?? NO_STEPS;
}
