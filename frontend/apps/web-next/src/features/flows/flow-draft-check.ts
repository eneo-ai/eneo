/**
 * What would stop a draft from being published, per step: the reference
 * editor's draft check (`FlowDraftCheck.svelte`, `flowStepConfigValidation.ts`
 * and `getFlowStepValidationIssues` in apps/web) over the saved draft. The
 * core already refused anything a draft save refuses; these are the rules
 * publication adds, judged with what the core answers for the draft: its step
 * assistants (the model each AI step uses), its tool options (which tools
 * the space allows and what they require) and its classification preview.
 * Pure and unit-tested.
 */
import { stepConnections } from "./chat/connections";
import type { FieldAnchor } from "./editor/field-problems";
import { removedReads } from "./editor/reference-repair";
import {
  hasHttpConfig,
  isStructuredTemplateBinding,
  readHttpConfig,
  readSpeakerMapping,
  readTemplateFill,
  readToolConfig,
  toolArguments
} from "./editor/step-configs";
import {
  chainIssue,
  outputModeIssue,
  stepUsesModel,
  templateReadiness,
  type ChainIssue,
  type OutputModeIssue
} from "./editor/step-rules";
import type { FlowAssistant, StepClassification, ToolOption } from "./editor/step-types";
import type { FlowPublic, FlowStep } from "./flows-api";
import { readTarget, tokensOf } from "./flow-steps";
import {
  flowTakesAudio,
  liveModelState,
  speakerServiceState,
  speakersRequired,
  transcriptionModelMissing,
  transcriptionSettingsOf,
  type TranscriptionResources
} from "./flow-transcription";

export type StepProblem =
  | { code: "chain"; issue: ChainIssue }
  | { code: "output_mode"; issue: OutputModeIssue }
  | { code: "name_missing" }
  | { code: "prompt_missing" }
  | { code: "http_url_missing"; anchor: FieldAnchor }
  | { code: "http_credential_missing"; anchor: FieldAnchor }
  | { code: "tool_missing" }
  | { code: "tool_unavailable" }
  | { code: "tool_refused"; refusal: NonNullable<ToolOption["refusal"]> }
  | { code: "tool_arguments_missing"; names: string[] }
  | { code: "template_missing" }
  | { code: "template_unbound" }
  | { code: "template_orphaned" }
  | { code: "template_structured" }
  | { code: "speaker_participants_missing" }
  | { code: "model_missing" }
  | { code: "deleted_reference"; anchor: FieldAnchor }
  | { code: "classification"; violation: NonNullable<StepClassification["violation"]> };

export type FlowProblem =
  | { code: "no_steps" }
  | { code: "transcription_model_missing" }
  | { code: "speaker_service_missing" }
  | { code: "live_model_unavailable" };

export type DraftCheck = {
  flow: FlowProblem[];
  steps: { step: FlowStep; problems: StepProblem[] }[];
};

/** What the core answered for the draft; a part not answered yet is left out of the check. */
export type DraftFacts = {
  assistants: ReadonlyMap<string, FlowAssistant>;
  toolOptions: readonly ToolOption[] | null;
  classification: readonly StepClassification[] | null;
  /** The space's transcription models and services. */
  transcription: TranscriptionResources;
};

/** The editor field that fixes a problem, for "Öppna steget" to focus; null for the step's top. */
export function problemAnchor(problem: StepProblem): FieldAnchor | null {
  switch (problem.code) {
    case "chain":
      return "input_source";
    case "output_mode":
      return "output_mode";
    case "name_missing":
      return "user_description";
    case "prompt_missing":
      return "prompt";
    case "http_url_missing":
    case "http_credential_missing":
    case "deleted_reference":
      return problem.anchor;
    case "tool_missing":
    case "tool_unavailable":
    case "tool_refused":
    case "tool_arguments_missing":
      return "input_config.tool";
    case "template_missing":
    case "template_unbound":
    case "template_orphaned":
    case "template_structured":
      return "output_config.template";
    case "speaker_participants_missing":
      return "output_config.speaker_mapping";
    case "model_missing":
      return "completion_model";
    case "classification":
      return null;
  }
}

/**
 * Where the step still reads a step a change removed (`step_2_deleted`): its
 * underlag, its tool arguments or its prompt; null when it reads none.
 */
function deletedReference(
  step: FlowStep,
  steps: readonly FlowStep[],
  assistant: FlowAssistant | undefined
): FieldAnchor | null {
  if (removedReads(step, steps).length > 0) return "input_bindings";
  const readsRemoved = (text: string) =>
    tokensOf(text).some((token) => readTarget(token, step, steps).kind === "deleted");
  const tool = readToolConfig(step.input_config);
  if (
    tool &&
    Object.values(tool.arguments).some((value) => typeof value === "string" && readsRemoved(value))
  ) {
    return "input_config.tool";
  }
  return readsRemoved(assistant?.prompt?.text ?? "") ? "prompt" : null;
}

function stepProblems(
  step: FlowStep,
  flow: Pick<FlowPublic, "steps" | "metadata_json">,
  ordered: readonly FlowStep[],
  facts: DraftFacts
): StepProblem[] {
  const problems: StepProblem[] = [];
  const previous = ordered.filter((other) => other.step_order < step.step_order).at(-1) ?? null;
  const isLast = ordered.every((other) => other.step_order <= step.step_order);
  const chain = chainIssue(
    {
      input_source: step.input_source,
      input_type: step.input_type,
      input_bindings: step.input_bindings ?? null
    },
    step.step_order,
    previous?.output_type ?? null
  );
  if (chain) problems.push({ code: "chain", issue: chain });
  const mode = outputModeIssue(step, isLast);
  if (mode) problems.push({ code: "output_mode", issue: mode });
  if (!step.user_description?.trim()) problems.push({ code: "name_missing" });

  if (step.input_source === "http_get") {
    const url = hasHttpConfig(step.input_config)
      ? readHttpConfig(step.input_config, "input").url
      : "";
    if (!url.trim()) problems.push({ code: "http_url_missing", anchor: "input_config.http" });
  }
  if (step.output_mode === "http_post") {
    const url = hasHttpConfig(step.output_config)
      ? readHttpConfig(step.output_config, "output").url
      : "";
    if (!url.trim()) problems.push({ code: "http_url_missing", anchor: "output_config.http" });
  }
  // The auth mode is declared before the credential exists (the chat builds
  // it that way); publish waits for the key, token or password.
  const waiting = stepConnections(step).find(
    (connection) => connection.host && !connection.configured
  );
  if (waiting) problems.push({ code: "http_credential_missing", anchor: waiting.anchor });

  if (step.input_source === "tool") {
    const tool = readToolConfig(step.input_config);
    if (!tool) {
      problems.push({ code: "tool_missing" });
    } else if (facts.toolOptions) {
      const option = facts.toolOptions.find(
        (item) => item.mcp_server_id === tool.mcp_server_id && item.tool_id === tool.tool_id
      );
      if (!option) problems.push({ code: "tool_unavailable" });
      else if (option.refusal) problems.push({ code: "tool_refused", refusal: option.refusal });
      else {
        const names = toolArguments(option.input_schema)
          .filter((argument) => argument.required)
          .map((argument) => argument.name)
          .filter((name) => {
            const value = tool.arguments[name];
            return value === undefined || value === null || value === "";
          });
        if (names.length > 0) problems.push({ code: "tool_arguments_missing", names });
      }
    }
  }

  if (step.output_mode === "template_fill") {
    const template = readTemplateFill(step.output_config);
    if (!template.templateAssetId) {
      problems.push({ code: "template_missing" });
    } else {
      const bindings = template.bindings;
      if (Object.values(bindings).some(isStructuredTemplateBinding)) {
        problems.push({ code: "template_structured" });
      }
      // A field filled from a source the flow no longer has is as unfilled as
      // one never chosen: the editor's field count says the same.
      if (
        templateReadiness(step, flow)
          .unbound.map((name) => bindings[name])
          .some((binding) => binding === undefined || !isStructuredTemplateBinding(binding))
      ) {
        problems.push({ code: "template_unbound" });
      }
      if (
        template.placeholders.length > 0 &&
        Object.keys(bindings).some((name) => !template.placeholders.includes(name))
      ) {
        problems.push({ code: "template_orphaned" });
      }
    }
  }

  if (step.output_mode === "speaker_mapping") {
    const mapping = readSpeakerMapping(step.output_config);
    if (mapping.participantsField === null && !mapping.inferNames) {
      problems.push({ code: "speaker_participants_missing" });
    }
  }

  const assistant = facts.assistants.get(step.assistant_id);
  // The editor's own exception: a speaker step names speakers without an instruction.
  if (
    stepUsesModel(step) &&
    step.output_mode !== "speaker_mapping" &&
    assistant &&
    !assistant.prompt?.text?.trim()
  ) {
    problems.push({ code: "prompt_missing" });
  }
  if (stepUsesModel(step) && assistant && !assistant.completion_model) {
    problems.push({ code: "model_missing" });
  }
  const removed = deletedReference(step, ordered, assistant);
  if (removed) problems.push({ code: "deleted_reference", anchor: removed });

  const classification =
    facts.classification?.find((item) => item.step_id === step.id) ??
    facts.classification?.find((item) => item.step_order === step.step_order);
  if (classification?.violation) {
    problems.push({ code: "classification", violation: classification.violation });
  }
  return problems;
}

/** The draft's problems: the flow's own first, then each step's in run order. */
export function checkDraft(
  flow: Pick<FlowPublic, "steps" | "metadata_json">,
  facts: DraftFacts
): DraftCheck {
  const ordered = [...flow.steps].sort((a, b) => a.step_order - b.step_order);
  const problems: FlowProblem[] = [];
  if (ordered.length === 0) problems.push({ code: "no_steps" });
  const transcription = transcriptionSettingsOf(flow.metadata_json);
  if (transcriptionModelMissing(transcription, ordered)) {
    problems.push({ code: "transcription_model_missing" });
  }
  const required = speakersRequired(ordered);
  const takesAudio = flowTakesAudio(ordered);
  if (
    required &&
    takesAudio &&
    speakerServiceState(transcription, facts.transcription.services, required).picked === null
  ) {
    problems.push({ code: "speaker_service_missing" });
  }
  // The core refuses to publish a live model the space cannot stream through.
  if (takesAudio && liveModelState(transcription, facts.transcription.models).kind === "lost") {
    problems.push({ code: "live_model_unavailable" });
  }
  return {
    flow: problems,
    steps: ordered
      .map((step) => ({ step, problems: stepProblems(step, flow, ordered, facts) }))
      .filter((entry) => entry.problems.length > 0)
  };
}

export function problemCount(check: DraftCheck): number {
  return check.flow.length + check.steps.reduce((sum, entry) => sum + entry.problems.length, 0);
}
