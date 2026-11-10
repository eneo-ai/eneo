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
import { httpAnchor, type FieldAnchor } from "./editor/field-problems";
import { readMeaning, readTone, type ReadMeaning, type TextPlace } from "./editor/request-preview";
import { formFieldsOf } from "./editor/step-variables";
import {
  hasHttpConfig,
  headerSent,
  isStructuredTemplateBinding,
  readHttpConfig,
  readInputBindings,
  readSpeakerMapping,
  readTemplateFill,
  readTextProcessingMode,
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
import {
  isJsonObject,
  objectOf,
  type FlowAssistant,
  type StepClassification,
  type ToolOption
} from "./editor/step-types";
import type { FlowPublic, FlowStep } from "./flows-api";
import { tokensOf } from "./flow-steps";
import {
  flowTakesAudio,
  liveModelState,
  speakerServiceState,
  speakersRequired,
  transcriptionModelMissing,
  transcriptionSettingsOf,
  type TranscriptionResources
} from "./flow-transcription";

/** A reference in a step that reads nothing the run has, and what it names. */
export type UnreadReference = { token: string; meaning: ReadMeaning };

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
  /** Fixed argument values the tool's input schema refuses. */
  | { code: "tool_arguments_invalid"; names: string[] }
  | { code: "template_missing" }
  /** The Word fields, by their tags, that nothing fills. */
  | { code: "template_unbound"; names: string[] }
  | { code: "template_orphaned" }
  | { code: "template_structured" }
  | { code: "speaker_participants_missing" }
  | { code: "model_missing" }
  /** Every reference in one field of the step that reads nothing the run has. */
  | { code: "reference"; anchor: FieldAnchor; reads: UnreadReference[] }
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
    case "reference":
      return problem.anchor;
    case "tool_missing":
    case "tool_unavailable":
    case "tool_refused":
    case "tool_arguments_missing":
    case "tool_arguments_invalid":
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

/** The core's runtime variables (`RESERVED_RUNTIME_VARIABLES`). */
const RUNTIME_HEADS = new Set([
  "datum",
  "flow",
  "flow_input",
  "step_input",
  "transkribering",
  "föregående_steg",
  "indata_text",
  "indata_json"
]);

/** The run input's own keys (`PRIMARY_FLOW_INPUT_KEYS`). */
const FLOW_INPUT_KEYS = new Set([
  "file_ids",
  "json",
  "structured",
  "text",
  "transcribed_text",
  "transcription",
  "transcript",
  "transkribering"
]);

/**
 * Whether publish resolves a reference the editor has no name for
 * (`_analyze_expression` in the core): a runtime variable, a step by number
 * (`step_1.status`) or a form field by its bare name. The run input
 * (`flow_input.x`, `flow.input.x`) holds only its own keys and the form's
 * fields; anything else in it is refused.
 */
function coreKnowsHead(token: string, flow: Pick<FlowPublic, "metadata_json">): boolean {
  const [head = "", ...tail] = token.split(".").map((part) => part.trim());
  const isField = (name: string) => formFieldsOf(flow).some((field) => field.name === name);
  const inputKey =
    head === "flow_input" ? tail[0] : head === "flow" && tail[0] === "input" ? tail[1] : null;
  if (inputKey !== null)
    return inputKey === undefined || FLOW_INPUT_KEYS.has(inputKey) || isField(inputKey);
  return RUNTIME_HEADS.has(head) || /^step_\d+$/.test(head) || isField(head);
}

/**
 * The references of a step that read nothing the run has, per field: the
 * places publish reads them (`_validate_template_reads`,
 * `_validate_binding_references` and the tool's rule in the core). Its
 * instruction only when the step runs a model, its underlag, its tool
 * arguments and the texts of its HTTP call. A webhook is built once the step
 * has answered, so it reads the step's own result too. A Word step's fields
 * are the template rule's (`template_unbound`).
 */
function unreadReferences(
  step: FlowStep,
  flow: Pick<FlowPublic, "steps" | "metadata_json">,
  assistant: FlowAssistant | undefined
): StepProblem[] {
  const sites: { anchor: FieldAnchor; tokens: string[]; order: number; place?: TextPlace }[] = [];
  if (stepUsesModel(step) && assistant) {
    sites.push({
      anchor: "prompt",
      tokens: tokensOf(assistant.prompt?.text ?? ""),
      order: step.step_order,
      place: { sectionIndex: readTextProcessingMode(step.input_config) === "process_each_section" }
    });
  }
  const bindings = readInputBindings(step.input_bindings);
  if (bindings.status === "valid") {
    sites.push({
      anchor: "input_bindings",
      tokens: [...tokensOf(bindings.question), ...bindings.sourceRefs.map((ref) => ref.stepRef)],
      order: step.step_order
    });
  }
  const tool = step.input_source === "tool" ? readToolConfig(step.input_config) : null;
  if (tool) {
    sites.push({
      anchor: "input_config.tool",
      tokens: Object.values(tool.arguments).flatMap((value) =>
        typeof value === "string" ? tokensOf(value) : []
      ),
      order: step.step_order
    });
  }
  const calls = [
    step.input_source === "http_get" && hasHttpConfig(step.input_config)
      ? { base: "input_config.http" as const, config: step.input_config, order: step.step_order }
      : null,
    step.output_mode === "http_post" && hasHttpConfig(step.output_config)
      ? {
          base: "output_config.http" as const,
          config: step.output_config,
          order: step.step_order + 1
        }
      : null
  ];
  for (const call of calls) {
    if (!call) continue;
    const http = readHttpConfig(
      call.config,
      call.base === "input_config.http" ? "input" : "output"
    );
    const at = (anchor: FieldAnchor, texts: string[]) =>
      sites.push({ anchor, tokens: texts.flatMap(tokensOf), order: call.order });
    at(call.base, [http.url]);
    at(httpAnchor(call.base, "auth"), [
      http.auth.mode === "api_key" ? http.auth.header_name : "",
      http.auth.mode === "basic_auth" ? http.auth.username : ""
    ]);
    at(
      httpAnchor(call.base, "more"),
      http.custom_headers.flatMap((header) =>
        headerSent(header) && !header.secret && typeof header.value === "string"
          ? [header.value]
          : []
      )
    );
    if (http.body.mode === "json_template" || http.body.mode === "text_template") {
      at(httpAnchor(call.base, "body"), [http.body.template ?? ""]);
    }
  }

  const unread = new Map<FieldAnchor, UnreadReference[]>();
  for (const site of sites) {
    for (const token of new Set(site.tokens)) {
      const meaning = readMeaning(token, site.order, flow, site.place);
      if (readTone(meaning) === "reads") continue;
      if (meaning.kind === "other" && coreKnowsHead(token, flow)) continue;
      const reads = unread.get(site.anchor) ?? [];
      if (!reads.some((read) => read.token === token)) reads.push({ token, meaning });
      unread.set(site.anchor, reads);
    }
  }
  return [...unread].map(([anchor, reads]) => ({ code: "reference", anchor, reads }));
}

/** What publish checks of a fixed argument's value against its property schema. */
const JSON_TYPES: Record<string, (value: unknown) => boolean> = {
  string: (value) => typeof value === "string",
  number: (value) => typeof value === "number",
  integer: (value) => Number.isInteger(value),
  boolean: (value) => typeof value === "boolean",
  array: (value) => Array.isArray(value),
  object: isJsonObject,
  null: (value) => value === null
};

/**
 * Whether a fixed argument value fits its property in the tool's input
 * schema: its type, its allowed values and its bounds. A reference is read
 * when the step runs and is judged then.
 */
// ponytail: type, enum and bounds only; publish runs the full JSON Schema
// (`check_fixed_tool_properties`). Add rules here when an author meets one.
function fitsProperty(value: unknown, property: unknown): boolean {
  if (typeof value === "string" && tokensOf(value).length > 0) return true;
  const schema = objectOf(property);
  const types = typeof schema.type === "string" ? [schema.type] : schema.type;
  if (
    Array.isArray(types) &&
    types.length > 0 &&
    !types.some((type) => typeof type !== "string" || (JSON_TYPES[type]?.(value) ?? true))
  ) {
    return false;
  }
  if (
    Array.isArray(schema.enum) &&
    !schema.enum.some((option) => JSON.stringify(option) === JSON.stringify(value))
  ) {
    return false;
  }
  if (typeof value === "number") {
    if (typeof schema.minimum === "number" && value < schema.minimum) return false;
    if (typeof schema.maximum === "number" && value > schema.maximum) return false;
  }
  return true;
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
        const given = (name: string) => {
          const value = tool.arguments[name];
          return value !== undefined && value !== null && value !== "";
        };
        const declared = toolArguments(option.input_schema);
        const names = declared
          .filter((argument) => argument.required && !given(argument.name))
          .map((argument) => argument.name);
        if (names.length > 0) problems.push({ code: "tool_arguments_missing", names });
        const properties = objectOf(objectOf(option.input_schema).properties);
        const invalid = declared
          .filter(
            (argument) =>
              given(argument.name) &&
              !fitsProperty(tool.arguments[argument.name], properties[argument.name])
          )
          .map((argument) => argument.name);
        if (invalid.length > 0) problems.push({ code: "tool_arguments_invalid", names: invalid });
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
      const unbound = templateReadiness(step, flow).unbound.filter((name) => {
        const binding = bindings[name];
        return binding === undefined || !isStructuredTemplateBinding(binding);
      });
      if (unbound.length > 0) problems.push({ code: "template_unbound", names: unbound });
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
  problems.push(...unreadReferences(step, flow, assistant));

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
