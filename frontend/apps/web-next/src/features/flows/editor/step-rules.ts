import {
  FILE_INPUT_TYPES,
  hasUnderlag,
  outputModeUsesCompletionModel,
  readRuntimeInput,
  readSpeakerMapping,
  readTemplateFill,
  readToolConfig,
  defaultHttpConfig,
  hasHttpConfig,
  readHttpConfig,
  reviewLocked,
  reviewSupported,
  supportsCitations,
  supportsRetrievalPolicy,
  withCitations,
  withHttpConfig,
  withRetrievalPolicy,
  withRuntimeInput,
  withSpeakerMapping,
  withToolConfig,
  readTextProcessingMode,
  withTextProcessingMode,
  textProcessingEligibility,
  longMaterialEligibility,
  readLongMaterial,
  withLongMaterial
} from "./step-configs";
import type { InputSource, InputType, OutputMode, OutputType, StepConfig } from "./step-types";

/**
 * The choices each setting of a saved step offers at its place, and what
 * changing one setting does to the others. The core's rules (`enums.py`,
 * `step_chain_rules.py`, `output_modes.py`) decide; this is the editor's copy
 * of them for the field pickers, ported from the reference editor's
 * `flowStepTypes.ts` and `flowStepTransitionPolicy.ts` so a choice never
 * leaves the step in a state a save refuses. Which kinds of step may be added
 * where is the core's own answer (`step-kinds.ts`).
 */

export const INPUT_SOURCES: readonly InputSource[] = [
  "flow_input",
  "previous_step",
  "all_previous_steps",
  "http_get",
  "tool"
];

export const INPUT_TYPES: readonly InputType[] = [
  "text",
  "json",
  "document",
  "file",
  "audio",
  "any",
  "image"
];

export const OUTPUT_MODES: readonly OutputMode[] = [
  "pass_through",
  "compose_text",
  "copy_input",
  "render_verbatim",
  "template_fill",
  "transcribe_only",
  "speaker_mapping",
  "http_post"
];

export const OUTPUT_TYPES: readonly OutputType[] = ["text", "json", "pdf", "docx"];

/** What a previous step's output can feed, without an explicit underlag. */
const CHAIN_COMPATIBLE: Record<OutputType, readonly InputType[]> = {
  text: ["text", "json", "any"],
  json: ["text", "json", "any"],
  pdf: ["text", "any"],
  docx: ["text", "any"]
};

function chainCompatible(outputType: OutputType, inputType: InputType): boolean {
  return CHAIN_COMPATIBLE[outputType].includes(inputType);
}

/** The input type a step reading `outputType` starts with. */
function inputTypeForOutput(outputType: OutputType | null | undefined): InputType {
  return outputType === "json" ? "json" : "text";
}

/** Only step 1 reads what the flow is sent; only later steps read earlier ones. */
export function validInputSources(position: number): InputSource[] {
  return position === 1
    ? ["flow_input", "http_get", "tool"]
    : ["previous_step", "all_previous_steps", "http_get", "tool"];
}

export function validInputTypes(
  source: InputSource,
  previousOutputType: OutputType | null,
  underlag: boolean
): InputType[] {
  if ((source === "previous_step" || source === "all_previous_steps") && underlag) {
    return ["text", "json", "any"];
  }
  switch (source) {
    case "flow_input":
      return ["text", "json", "document", "file", "audio", "any"];
    case "all_previous_steps":
      return ["text", "any"];
    case "http_get":
      return ["text", "json", "any"];
    case "tool":
      return ["text", "json"];
    case "previous_step":
      return previousOutputType ? [...CHAIN_COMPATIBLE[previousOutputType]] : ["text", "any"];
  }
}

export type Option<T extends string> = { value: T; invalid: boolean };

/** Valid choices in their order, plus the stored value marked invalid when it is not one. */
function withCurrent<T extends string>(
  order: readonly T[],
  valid: readonly T[],
  current: T
): Option<T>[] {
  const options = order
    .filter((value) => valid.includes(value))
    .map((value) => ({ value, invalid: false }));
  return valid.includes(current) ? options : [{ value: current, invalid: true }, ...options];
}

export function inputSourceOptions(position: number, current: InputSource): Option<InputSource>[] {
  return withCurrent(INPUT_SOURCES, validInputSources(position), current);
}

export function inputTypeOptions(
  step: Pick<StepConfig, "input_source" | "input_type" | "input_bindings">,
  previousOutputType: OutputType | null
): Option<InputType>[] {
  const valid = validInputTypes(
    step.input_source,
    previousOutputType,
    hasUnderlag(step.input_bindings)
  );
  return withCurrent(INPUT_TYPES, valid, step.input_type);
}

export type OutputModeIssue =
  | "copy_input_requires_json"
  | "compose_text_requires_text"
  | "render_verbatim_requires_text_document"
  | "template_fill_requires_docx"
  | "transcribe_only_requires_audio_text"
  | "speaker_mapping_requires_text_json"
  | "text_document_requires_render_verbatim"
  | "http_post_must_be_last";

/** Why the step's output mode does not fit its types, or null when it does. */
export function outputModeIssue(
  step: Pick<StepConfig, "input_source" | "input_type" | "output_mode" | "output_type">,
  isLast = true
): OutputModeIssue | null {
  const { input_type: input, output_type: output } = step;
  switch (step.output_mode) {
    case "copy_input":
      return input === "json" && output === "json" ? null : "copy_input_requires_json";
    case "compose_text":
      return input === "text" && output === "text" ? null : "compose_text_requires_text";
    case "render_verbatim":
      return input === "text" && (output === "pdf" || output === "docx")
        ? null
        : "render_verbatim_requires_text_document";
    case "template_fill":
      return output === "docx" ? null : "template_fill_requires_docx";
    case "transcribe_only":
      return input === "audio" && output === "text" ? null : "transcribe_only_requires_audio_text";
    case "speaker_mapping":
      return step.input_source === "previous_step" && input === "text" && output === "json"
        ? null
        : "speaker_mapping_requires_text_json";
    case "http_post":
      return isLast ? null : "http_post_must_be_last";
    case "pass_through":
      return input === "text" && (output === "pdf" || output === "docx")
        ? "text_document_requires_render_verbatim"
        : null;
  }
}

/** The output modes the step can switch to; the stored one is always listed. */
export function outputModeOptions(
  step: Pick<StepConfig, "input_source" | "input_type" | "output_mode" | "output_type">,
  isLast: boolean
): Option<OutputMode>[] {
  return OUTPUT_MODES.filter((mode) => {
    if (mode === step.output_mode) return true;
    switch (mode) {
      case "compose_text":
      case "render_verbatim":
        return step.input_type === "text";
      case "copy_input":
        return step.input_type === "json";
      case "transcribe_only":
        return step.input_type === "audio";
      case "speaker_mapping":
        return step.input_type === "text" && step.input_source === "previous_step";
      case "template_fill":
        return step.input_source !== "tool";
      case "http_post":
        return isLast;
      case "pass_through":
        return true;
    }
  }).map((value) => ({
    value,
    invalid: value === step.output_mode && outputModeIssue(step, isLast) !== null
  }));
}

export function outputTypeOptions(
  step: Pick<StepConfig, "input_type" | "output_mode" | "output_type">
): Option<OutputType>[] {
  const allowed: readonly OutputType[] =
    step.output_mode === "transcribe_only" || step.output_mode === "compose_text"
      ? ["text"]
      : step.output_mode === "template_fill"
        ? ["docx"]
        : step.output_mode === "render_verbatim"
          ? ["pdf", "docx"]
          : step.output_mode === "speaker_mapping" || step.output_mode === "copy_input"
            ? ["json"]
            : step.output_mode === "pass_through" && step.input_type === "text"
              ? ["text", "json"]
              : OUTPUT_TYPES;
  return withCurrent(OUTPUT_TYPES, allowed, step.output_type);
}

/** Problems the chain rules find in this step at its place (`step_chain_rules.py`). */
export type ChainIssue =
  | "flow_input_not_first"
  | "previous_on_first"
  | "file_type_needs_flow_input"
  | "json_from_all_previous"
  | "outside_source_with_underlag"
  | "incompatible_previous"
  | "image_unsupported";

export function chainIssue(
  step: Pick<StepConfig, "input_source" | "input_type" | "input_bindings">,
  position: number,
  previousOutputType: OutputType | null
): ChainIssue | null {
  const underlag = hasUnderlag(step.input_bindings);
  if (step.input_source === "flow_input" && position !== 1) return "flow_input_not_first";
  if (
    position === 1 &&
    (step.input_source === "previous_step" || step.input_source === "all_previous_steps")
  ) {
    return "previous_on_first";
  }
  if (step.input_type === "image") return "image_unsupported";
  if (FILE_INPUT_TYPES.has(step.input_type) && step.input_source !== "flow_input") {
    return "file_type_needs_flow_input";
  }
  if (step.input_type === "json" && step.input_source === "all_previous_steps" && !underlag) {
    return "json_from_all_previous";
  }
  if ((step.input_source === "http_get" || step.input_source === "tool") && underlag) {
    return "outside_source_with_underlag";
  }
  if (
    step.input_source === "previous_step" &&
    position > 1 &&
    !underlag &&
    previousOutputType !== null &&
    !chainCompatible(previousOutputType, step.input_type)
  ) {
    return "incompatible_previous";
  }
  return null;
}

// ---------------------------------------------------------------------------
// Transitions: one setting changes, the others follow so the step stays valid.
// ---------------------------------------------------------------------------

/**
 * Settings that belong to one output mode and that the core refuses under
 * another: citations and the retrieval policy need a model's answer, review
 * cannot follow outbound delivery, a speaker mapping is always reviewed.
 */
function settle(step: StepConfig): StepConfig {
  let next = step;
  if (!supportsCitations(next)) {
    const output_config = withCitations(next.output_config, false);
    if (output_config !== next.output_config) next = { ...next, output_config };
  }
  if (!supportsRetrievalPolicy(next.output_mode)) {
    const output_config = withRetrievalPolicy(next.output_config, null);
    if (output_config !== next.output_config) next = { ...next, output_config };
  }
  if (reviewLocked(next.output_mode)) {
    if (next.review_policy?.mode !== "edit") {
      next = { ...next, review_policy: { ...(next.review_policy ?? {}), mode: "edit" } };
    }
  } else if (!reviewSupported(next.output_mode) && next.review_policy !== null) {
    next = { ...next, review_policy: null };
  }
  if (
    readTextProcessingMode(next.input_config) !== null &&
    textProcessingEligibility(next) !== "eligible"
  ) {
    next = { ...next, input_config: withTextProcessingMode(next.input_config, null) };
  }
  // A mode change that leaves no model answer, or a mapped read, ends long
  // material; a stored conflict with section reading is left for the author.
  const longMaterial = longMaterialEligibility(next);
  if (
    readLongMaterial(next.input_config) &&
    (longMaterial === "output" || longMaterial === "mapped")
  ) {
    next = { ...next, input_config: withLongMaterial(next.input_config, false) };
  }
  return next;
}

/**
 * Uploads follow a file-based input type: on when one is chosen, off when it
 * is left (unless the author customised them), and always off for a source
 * outside the flow, which the core refuses uploads beside. Turning them off
 * keeps their stored settings.
 */
function syncUploads(step: StepConfig, previousType: InputType): StepConfig {
  const runtime = readRuntimeInput(step.input_config);
  const nowFile = FILE_INPUT_TYPES.has(step.input_type) && step.input_source === "flow_input";
  const wasFile = FILE_INPUT_TYPES.has(previousType);
  const customised =
    runtime.label.trim() !== "" ||
    runtime.description.trim() !== "" ||
    runtime.maxFiles !== null ||
    runtime.acceptedMimetypes.length > 0;
  if (nowFile) {
    return {
      ...step,
      input_config: withRuntimeInput(
        step.input_config,
        step.input_type,
        runtime.enabled ? {} : { enabled: true, required: true }
      )
    };
  }
  if (
    runtime.enabled &&
    (step.input_source !== "flow_input" ||
      (wasFile && previousType !== step.input_type && !customised))
  ) {
    return {
      ...step,
      input_config: withRuntimeInput(step.input_config, step.input_type, { enabled: false })
    };
  }
  return step;
}

export function applyInputSourceChange(
  step: StepConfig,
  source: InputSource,
  previousOutputType: OutputType | null
): StepConfig {
  let next: StepConfig = { ...step, input_source: source };
  if (source === "http_get" && !hasHttpConfig(step.input_config)) {
    next.input_config = withHttpConfig(step.input_config, defaultHttpConfig("input"));
  }
  if (source === "http_get" || source === "tool") {
    // The fetched answer is the whole input: an underlag would replace it.
    next.input_bindings = null;
  }
  if (source === "tool") {
    // A step that turns to a tool starts without one: a tool chosen before
    // the step had another source is not brought back unseen.
    next.input_config = withToolConfig(next.input_config, readToolConfig(step.input_config));
  }
  const valid = validInputTypes(source, previousOutputType, hasUnderlag(next.input_bindings));
  if (!valid.includes(next.input_type)) {
    next.input_type =
      source === "previous_step" && previousOutputType
        ? inputTypeForOutput(previousOutputType)
        : valid.includes("text")
          ? "text"
          : (valid[0] ?? "text");
  }
  next = syncUploads(next, step.input_type);
  if (next.input_type !== "audio" && next.output_mode === "transcribe_only") {
    next = { ...next, output_mode: "pass_through" };
  }
  if (next.output_mode === "template_fill" && source === "tool") {
    next = { ...next, output_mode: "pass_through", output_type: "text" };
  }
  return settle(next);
}

export function applyInputTypeChange(step: StepConfig, type: InputType): StepConfig {
  let next: StepConfig = { ...step, input_type: type };
  if (FILE_INPUT_TYPES.has(type) && step.input_source !== "flow_input") {
    next.input_source = "flow_input";
  }
  if (type === "audio") {
    next.output_mode = "transcribe_only";
    next.output_type = "text";
  } else if (step.output_mode === "transcribe_only") {
    next.output_mode = "pass_through";
  }
  if (next.output_mode === "pass_through" && type === "text" && isDocument(next.output_type)) {
    next.output_mode = "render_verbatim";
  }
  if (next.output_mode === "compose_text" && type !== "text") next.output_mode = "pass_through";
  if (next.output_mode === "render_verbatim" && type !== "text") next.output_mode = "pass_through";
  if (next.output_mode === "copy_input" && type !== "json") next.output_mode = "pass_through";
  if (next.output_mode === "speaker_mapping" && type !== "text") {
    next.output_mode = "pass_through";
  }
  next = syncUploads(next, step.input_type);
  return settle(next);
}

function isDocument(type: OutputType): boolean {
  return type === "pdf" || type === "docx";
}

export function applyOutputModeChange(step: StepConfig, mode: OutputMode): StepConfig {
  let next: StepConfig = { ...step, output_mode: mode };
  switch (mode) {
    case "transcribe_only":
      next = { ...next, input_source: "flow_input", input_type: "audio", output_type: "text" };
      next = syncUploads(next, step.input_type);
      break;
    case "template_fill":
      next = { ...next, output_type: "docx", output_contract: null };
      break;
    case "render_verbatim":
      next = {
        ...next,
        output_type: isDocument(step.output_type) ? step.output_type : "pdf",
        output_contract: null
      };
      break;
    case "copy_input":
      next = {
        ...next,
        output_type: "json",
        output_contract: step.output_type === "json" ? step.output_contract : null
      };
      break;
    case "compose_text":
      next = { ...next, output_type: "text", output_contract: null };
      break;
    case "speaker_mapping":
      // The mapping reads the transcript of the step before and is always
      // confirmed by a person; both are set at once so the draft holds.
      next = {
        ...next,
        input_source: "previous_step",
        input_type: "text",
        output_type: "json",
        output_contract: null,
        review_policy: { ...(step.review_policy ?? {}), mode: "edit" },
        output_config: withSpeakerMapping(
          step.output_config,
          readSpeakerMapping(step.output_config)
        )
      };
      break;
    case "http_post":
      if (!hasHttpConfig(step.output_config)) {
        next.output_config = withHttpConfig(step.output_config, defaultHttpConfig("output"));
      } else {
        next.output_config = withHttpConfig(
          step.output_config,
          readHttpConfig(step.output_config, "output")
        );
      }
      if (isDocument(next.output_type)) next.output_type = "text";
      break;
    case "pass_through":
      if (step.input_type === "text" && isDocument(step.output_type)) next.output_type = "text";
      break;
  }
  return settle(next);
}

export function applyOutputTypeChange(step: StepConfig, type: OutputType): StepConfig {
  let mode = step.output_mode;
  if (
    (mode === "template_fill" && type !== "docx") ||
    (mode === "speaker_mapping" && type !== "json") ||
    (mode === "copy_input" && type !== "json") ||
    (mode === "compose_text" && type !== "text") ||
    (mode === "render_verbatim" && !isDocument(type))
  ) {
    mode = "pass_through";
  }
  if (mode === "pass_through" && step.input_type === "text" && isDocument(type)) {
    mode = "render_verbatim";
  }
  const next: StepConfig = {
    ...step,
    output_type: type,
    output_mode: mode,
    output_contract: type === "json" ? step.output_contract : null
  };
  return settle(next);
}

/** Whether the step runs an AI model, and so has an instruction and a model. */
export function stepUsesModel(step: Pick<StepConfig, "output_mode">): boolean {
  return outputModeUsesCompletionModel(step.output_mode);
}

/** Whether a template step has chosen a template and bound every placeholder. */
export function templateReadiness(step: Pick<StepConfig, "output_config">) {
  const config = readTemplateFill(step.output_config);
  const bound = config.placeholders.filter((name) => name in config.bindings).length;
  return { hasTemplate: config.templateAssetId !== null, total: config.placeholders.length, bound };
}
