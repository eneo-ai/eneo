import type { FlowStep } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";

type InputType = FlowStep["input_type"];
type InputSource = FlowStep["input_source"];
type OutputMode = FlowStep["output_mode"];
type OutputType = FlowStep["output_type"];

export function outputModeUsesCompletionModel(mode: OutputMode): boolean {
  return mode === "pass_through" || mode === "http_post";
}

type OutputOption<TValue extends string> = {
  value: TValue;
  readonly label: string;
};

export type SelectableOutputOption<TValue extends string> = OutputOption<TValue> & {
  legacyInvalid: boolean;
};

export const OUTPUT_TYPES: OutputOption<OutputType>[] = [
  {
    value: "text",
    get label() {
      return m.flow_output_type_text();
    }
  },
  {
    value: "json",
    get label() {
      return m.flow_output_type_json();
    }
  },
  {
    value: "pdf",
    get label() {
      return m.flow_output_type_pdf();
    }
  },
  {
    value: "docx",
    get label() {
      return m.flow_output_type_docx();
    }
  }
];

const OUTPUT_MODE_LABELS: Record<OutputMode, () => string> = {
  pass_through: () => m.flow_output_mode_pass_through(),
  compose_text: () => m.flow_output_mode_compose_text(),
  transcribe_only: () => m.flow_output_mode_transcribe_only(),
  template_fill: () => m.flow_output_mode_template_fill(),
  render_verbatim: () => m.flow_output_mode_render_verbatim(),
  http_post: () => m.flow_output_mode_http_post()
};

const OUTPUT_MODE_ORDER: OutputMode[] = [
  "pass_through",
  "compose_text",
  "transcribe_only",
  "template_fill",
  "render_verbatim",
  "http_post"
];

// Exhaustive over the generated backend union: a new runtime mode must gain a
// deliberate authoring label here instead of silently disappearing from the UI.
export const OUTPUT_MODES: OutputOption<OutputMode>[] = OUTPUT_MODE_ORDER.map((value) => ({
  value,
  get label() {
    return OUTPUT_MODE_LABELS[value]();
  }
}));

export type OutputModeCompatibilityIssue =
  | "compose_text_requires_text"
  | "render_verbatim_requires_text_document"
  | "template_fill_requires_docx"
  | "transcribe_only_requires_audio_text"
  | "text_document_requires_render_verbatim";

export type FlowStepLike = Pick<
  FlowStep,
  "step_order" | "input_source" | "input_type" | "output_type"
>;

export type FlowStepValidationIssue = {
  code: string;
  field: "input_source" | "input_type" | "step_order";
  stepOrder: number;
  previousOutputType?: OutputType;
};

export type SelectableInputTypeOption = {
  value: InputType;
  disabled: boolean;
  legacyInvalid: boolean;
};

export type SelectableInputSourceOption = {
  value: InputSource;
  legacyInvalid: boolean;
};

const INPUT_TYPE_ORDER: InputType[] = ["text", "json", "document", "file", "image", "audio", "any"];

const INPUT_SOURCE_ORDER: InputSource[] = [
  "flow_input",
  "previous_step",
  "all_previous_steps",
  "http_get"
];

const ADVANCED_ONLY_INPUT_TYPES = new Set<InputType>(["file", "any"]);
const OUTBOUND_DELIVERY_OUTPUT_MODES = new Set<OutputMode>(["http_post"]);

const COMPATIBLE_COERCIONS: Record<OutputType, InputType[]> = {
  text: ["text", "json", "any"],
  json: ["text", "json", "any"],
  pdf: ["text", "any"],
  docx: ["text", "any"]
};

export function mapOutputToInputType(outputType?: OutputType): InputType {
  if (!outputType) return "text";
  const validInputTypes = new Set<InputType>([
    "text",
    "json",
    "image",
    "audio",
    "document",
    "file",
    "any"
  ]);
  return validInputTypes.has(outputType as InputType) ? (outputType as InputType) : "text";
}

export function hasOutboundDeliveryOutputMode(outputMode: OutputMode): boolean {
  return OUTBOUND_DELIVERY_OUTPUT_MODES.has(outputMode);
}

export function getValidInputTypes(
  inputSource: InputSource,
  previousOutputType?: OutputType
): InputType[] {
  switch (inputSource) {
    case "flow_input":
      return ["text", "json", "document", "file", "audio", "any"];
    case "all_previous_steps":
      return ["text", "any"];
    case "http_get":
      return ["text", "json", "any"];
    case "previous_step":
      return previousOutputType
        ? [...(COMPATIBLE_COERCIONS[previousOutputType] ?? ["text", "any"])]
        : ["text", "any"];
    default:
      return ["text"];
  }
}

export function getValidInputSources(params: {
  steps: FlowStepLike[];
  stepOrder: number;
}): InputSource[] {
  if (params.stepOrder === 1) {
    return ["flow_input", "http_get"];
  }
  return ["previous_step", "all_previous_steps", "http_get"];
}

export function getSelectableInputSourceOptions(params: {
  steps: FlowStepLike[];
  stepOrder: number;
  currentInputSource?: InputSource;
}): SelectableInputSourceOption[] {
  const { steps, stepOrder, currentInputSource } = params;
  const visible = getValidInputSources({ steps, stepOrder });
  let options = INPUT_SOURCE_ORDER.filter((value) => visible.includes(value)).map((value) => ({
    value,
    legacyInvalid: false
  }));

  if (currentInputSource && !options.some((option) => option.value === currentInputSource)) {
    options = [{ value: currentInputSource, legacyInvalid: true }, ...options];
  }

  return options;
}

function insertInCanonicalOrder(values: InputType[], value: InputType): InputType[] {
  if (values.includes(value)) return values;
  const next = [...values, value];
  return INPUT_TYPE_ORDER.filter((candidate) => next.includes(candidate));
}

export function getSelectableInputTypeOptions(params: {
  inputSource: InputSource;
  previousOutputType?: OutputType;
  currentInputType?: InputType;
  isAdvancedMode: boolean;
}): SelectableInputTypeOption[] {
  const { inputSource, previousOutputType, currentInputType, isAdvancedMode } = params;
  const valid = getValidInputTypes(inputSource, previousOutputType);
  let visible = INPUT_TYPE_ORDER.filter((value) => {
    if (value === "image") return false;
    if (!valid.includes(value)) return false;
    if (!isAdvancedMode && ADVANCED_ONLY_INPUT_TYPES.has(value)) return false;
    return true;
  });

  if (isAdvancedMode && inputSource === "flow_input") {
    visible = insertInCanonicalOrder(visible, "image");
  }

  let options = visible.map((value) => ({
    value,
    disabled: value === "image",
    legacyInvalid: false
  }));

  if (currentInputType && !options.some((option) => option.value === currentInputType)) {
    const currentIsValid = valid.includes(currentInputType);
    if (currentIsValid) {
      const merged = insertInCanonicalOrder(
        options.map((option) => option.value),
        currentInputType
      );
      options = merged.map((value) => ({
        value,
        disabled: value === "image",
        legacyInvalid: false
      }));
    } else {
      options = [
        {
          value: currentInputType,
          disabled: false,
          legacyInvalid: true
        },
        ...options
      ];
    }
  }

  return options;
}

export function getFlowStepValidationIssues(steps: FlowStepLike[]): FlowStepValidationIssue[] {
  if (steps.length === 0) return [];

  const issues: FlowStepValidationIssue[] = [];
  const sortedSteps = [...steps].sort((left, right) => left.step_order - right.step_order);
  const stepOrders = sortedSteps.map((step) => step.step_order);

  if (stepOrders.length !== new Set(stepOrders).size) {
    issues.push({
      code: "typed_io_duplicate_step_order",
      field: "step_order",
      stepOrder: stepOrders[0] ?? 1
    });
    return issues;
  }

  const expectedOrders = Array.from({ length: sortedSteps.length }, (_, index) => index + 1);
  if (stepOrders.some((stepOrder, index) => stepOrder !== expectedOrders[index])) {
    issues.push({
      code: "typed_io_non_contiguous_step_order",
      field: "step_order",
      stepOrder: stepOrders.find((stepOrder, index) => stepOrder !== expectedOrders[index]) ?? 1
    });
    return issues;
  }

  const stepByOrder = new Map(sortedSteps.map((step) => [step.step_order, step]));
  const flowInputSteps = sortedSteps.filter((step) => step.input_source === "flow_input");
  if (flowInputSteps.length > 1) {
    issues.push({
      code: "typed_io_multiple_flow_input_steps",
      field: "input_source",
      stepOrder: flowInputSteps[1].step_order
    });
  } else if (flowInputSteps.length === 1 && flowInputSteps[0].step_order !== 1) {
    issues.push({
      code: "typed_io_flow_input_position_invalid",
      field: "input_source",
      stepOrder: flowInputSteps[0].step_order
    });
  }

  for (const step of sortedSteps) {
    if (
      step.step_order === 1 &&
      (step.input_source === "previous_step" || step.input_source === "all_previous_steps")
    ) {
      issues.push({
        code: "typed_io_invalid_input_source_position",
        field: "input_source",
        stepOrder: step.step_order
      });
      continue;
    }

    if (step.input_type === "image") {
      issues.push({
        code: "typed_io_unsupported_type",
        field: "input_type",
        stepOrder: step.step_order
      });
      continue;
    }

    if (step.input_type === "document" && step.input_source !== "flow_input") {
      issues.push({
        code: "typed_io_document_source_unsupported",
        field: "input_type",
        stepOrder: step.step_order
      });
      continue;
    }

    if (step.input_type === "audio" && step.input_source !== "flow_input") {
      issues.push({
        code: "typed_io_audio_source_unsupported",
        field: "input_type",
        stepOrder: step.step_order
      });
      continue;
    }

    if (step.input_type === "file" && step.input_source !== "flow_input") {
      issues.push({
        code: "typed_io_file_source_unsupported",
        field: "input_type",
        stepOrder: step.step_order
      });
      continue;
    }

    if (step.input_type === "json" && step.input_source === "all_previous_steps") {
      issues.push({
        code: "typed_io_invalid_input_source_combination",
        field: "input_type",
        stepOrder: step.step_order
      });
      continue;
    }

    if (step.input_source === "previous_step" && step.step_order > 1) {
      const previousStep = stepByOrder.get(step.step_order - 1);
      if (!previousStep) {
        issues.push({
          code: "typed_io_missing_previous_step",
          field: "input_source",
          stepOrder: step.step_order
        });
        continue;
      }
      const validInputTypes = getValidInputTypes("previous_step", previousStep.output_type);
      if (!validInputTypes.includes(step.input_type)) {
        issues.push({
          code: "typed_io_incompatible_type_chain",
          field: "input_type",
          stepOrder: step.step_order,
          previousOutputType: previousStep.output_type
        });
      }
    }
  }

  return issues;
}

export function getAvailableOutputTypes(
  step: Pick<FlowStep, "output_mode" | "output_type"> | null | undefined
): SelectableOutputOption<OutputType>[] {
  if (!step) return OUTPUT_TYPES.map((type) => ({ ...type, legacyInvalid: false }));

  const allowedTypes: OutputType[] =
    step.output_mode === "transcribe_only" || step.output_mode === "compose_text"
      ? ["text"]
      : step.output_mode === "template_fill"
        ? ["docx"]
        : step.output_mode === "render_verbatim"
          ? ["pdf", "docx"]
          : OUTPUT_TYPES.map((type) => type.value);

  return OUTPUT_TYPES.filter(
    (type) => allowedTypes.includes(type.value) || type.value === step.output_type
  ).map((type) => ({
    ...type,
    legacyInvalid: type.value === step.output_type && !allowedTypes.includes(type.value)
  }));
}

export function getAvailableOutputModes(params: {
  step: Pick<FlowStep, "input_type" | "output_type" | "output_mode"> | null | undefined;
  isAdvancedMode: boolean;
}): SelectableOutputOption<OutputMode>[] {
  const { step, isAdvancedMode } = params;
  if (!step) return OUTPUT_MODES.map((mode) => ({ ...mode, legacyInvalid: false }));

  return OUTPUT_MODES.filter((mode) => {
    const isCurrent = mode.value === step.output_mode;
    if (!isAdvancedMode && mode.value === "template_fill" && !isCurrent) return false;
    if (!isAdvancedMode && mode.value === "http_post" && !isCurrent) return false;
    if (isCurrent) return true;
    if (mode.value === "compose_text" || mode.value === "render_verbatim") {
      return step.input_type === "text";
    }
    if (mode.value === "transcribe_only") return step.input_type === "audio";
    return true;
  }).map((mode) => ({
    ...mode,
    legacyInvalid: mode.value === step.output_mode && getOutputModeCompatibilityIssue(step) !== null
  }));
}

export function getOutputModeCompatibilityIssue(
  step: Pick<FlowStep, "input_type" | "output_type" | "output_mode">
): OutputModeCompatibilityIssue | null {
  if (step.output_mode === "compose_text") {
    return step.input_type === "text" && step.output_type === "text"
      ? null
      : "compose_text_requires_text";
  }
  if (step.output_mode === "render_verbatim") {
    return step.input_type === "text" && (step.output_type === "pdf" || step.output_type === "docx")
      ? null
      : "render_verbatim_requires_text_document";
  }
  if (step.output_mode === "template_fill") {
    return step.output_type === "docx" ? null : "template_fill_requires_docx";
  }
  if (step.output_mode === "transcribe_only") {
    return step.input_type === "audio" && step.output_type === "text"
      ? null
      : "transcribe_only_requires_audio_text";
  }
  if (
    step.output_mode === "pass_through" &&
    step.input_type === "text" &&
    (step.output_type === "pdf" || step.output_type === "docx")
  ) {
    return "text_document_requires_render_verbatim";
  }
  return null;
}
