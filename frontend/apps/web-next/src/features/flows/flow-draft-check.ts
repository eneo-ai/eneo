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
import {
  hasHttpConfig,
  isStructuredTemplateBinding,
  readHttpConfig,
  readInputBindings,
  readSpeakerMapping,
  readTemplateFill,
  readToolConfig,
  toolArguments
} from "./editor/step-configs";
import {
  chainIssue,
  outputModeIssue,
  stepUsesModel,
  type ChainIssue,
  type OutputModeIssue
} from "./editor/step-rules";
import type { FlowAssistant, StepClassification, ToolOption } from "./editor/step-types";
import type { FlowPublic, FlowStep } from "./flows-api";
import {
  speakerServiceState,
  speakersRequired,
  transcriptionModelMissing,
  transcriptionSettingsOf,
  flowTakesAudio,
  type SpeakerServiceLink
} from "./flow-transcription";

export type StepProblem =
  | { code: "chain"; issue: ChainIssue }
  | { code: "output_mode"; issue: OutputModeIssue }
  | { code: "name_missing" }
  | { code: "http_url_missing" }
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
  | { code: "deleted_reference" }
  | { code: "classification"; violation: NonNullable<StepClassification["violation"]> };

export type FlowProblem =
  | { code: "no_steps" }
  | { code: "transcription_model_missing" }
  | { code: "speaker_service_missing" };

export type DraftCheck = {
  flow: FlowProblem[];
  steps: { step: FlowStep; problems: StepProblem[] }[];
};

/** What the core answered for the draft; a part not answered yet is left out of the check. */
export type DraftFacts = {
  assistants: ReadonlyMap<string, FlowAssistant>;
  toolOptions: readonly ToolOption[] | null;
  classification: readonly StepClassification[] | null;
  speakerServices: readonly SpeakerServiceLink[];
};

/** A reference to a step a change removed, as the reference editor marks it. */
const DELETED_STEP_TOKEN = /\{\{\s*step_\d+_deleted/;

function deletedReference(step: FlowStep, assistant: FlowAssistant | undefined): boolean {
  const bindings = readInputBindings(step.input_bindings);
  if (bindings.status === "valid") {
    if (DELETED_STEP_TOKEN.test(bindings.question)) return true;
    if (bindings.sourceRefs.some((ref) => /^step_\d+_deleted/.test(ref.stepRef))) return true;
  }
  const tool = readToolConfig(step.input_config);
  if (
    tool &&
    Object.values(tool.arguments).some(
      (value) => typeof value === "string" && DELETED_STEP_TOKEN.test(value)
    )
  ) {
    return true;
  }
  return DELETED_STEP_TOKEN.test(assistant?.prompt?.text ?? "");
}

function stepProblems(
  step: FlowStep,
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
    if (!url.trim()) problems.push({ code: "http_url_missing" });
  }
  if (step.output_mode === "http_post") {
    const url = hasHttpConfig(step.output_config)
      ? readHttpConfig(step.output_config, "output").url
      : "";
    if (!url.trim()) problems.push({ code: "http_url_missing" });
  }

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
      if (template.placeholders.some((name) => !(name in bindings))) {
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
  if (stepUsesModel(step) && assistant && !assistant.completion_model) {
    problems.push({ code: "model_missing" });
  }
  if (deletedReference(step, assistant)) problems.push({ code: "deleted_reference" });

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
  if (
    required &&
    flowTakesAudio(ordered) &&
    speakerServiceState(transcription, facts.speakerServices, required).picked === null
  ) {
    problems.push({ code: "speaker_service_missing" });
  }
  return {
    flow: problems,
    steps: ordered
      .map((step) => ({ step, problems: stepProblems(step, ordered, facts) }))
      .filter((entry) => entry.problems.length > 0)
  };
}

export function problemCount(check: DraftCheck): number {
  return check.flow.length + check.steps.reduce((sum, entry) => sum + entry.problems.length, 0);
}
