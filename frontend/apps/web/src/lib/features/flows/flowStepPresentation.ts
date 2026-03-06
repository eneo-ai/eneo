import type { FlowStep } from "@intric/intric-js";
import type { SelectableInputTypeOption } from "./flowStepTypes";

type InputSource = FlowStep["input_source"];
type InputType = FlowStep["input_type"];
type OutputType = FlowStep["output_type"];

export type FlowPresentationStepLike = Pick<
  FlowStep,
  "step_order" | "input_source" | "input_type" | "output_type" | "output_mode" | "user_description"
>;

export type FlowSourceHintKind =
  | "flow_input"
  | "previous_step_text"
  | "previous_step_json"
  | "previous_step_document_text"
  | "all_previous_steps"
  | "http_source";

export type FlowOutputHintKind = "plain" | "structured_json" | "document_artifact";

export type FlowDownstreamKind = "text" | "text_and_structured";

export type FlowEdgePayloadKind = "flow_input" | "text" | "structured" | "none";

export type FlowRuntimeFileOriginKind =
  | "flow_input_runtime"
  | "no_runtime_upload"
  | "static_step_context";

export type FlowStepSummaryModel = {
  sourceKind: FlowSourceHintKind;
  sourceStepOrder: number | null;
  inputFormat: InputType;
  outputFormat: OutputType;
  downstreamKind: FlowDownstreamKind;
  usesInputTemplate: boolean;
  hasKnowledge: boolean;
  hasAttachments: boolean;
};

const DISPLAY_PRIORITY_BY_SOURCE: Partial<Record<FlowSourceHintKind, InputType[]>> = {
  previous_step_json: ["json", "text", "any"]
};

const INPUT_TYPE_FALLBACK_ORDER: InputType[] = [
  "text",
  "json",
  "document",
  "file",
  "image",
  "audio",
  "any"
];

export function getSourceHintKind(params: {
  inputSource: InputSource;
  previousOutputType?: OutputType;
}): FlowSourceHintKind {
  const { inputSource, previousOutputType } = params;
  switch (inputSource) {
    case "flow_input":
      return "flow_input";
    case "all_previous_steps":
      return "all_previous_steps";
    case "http_get":
    case "http_post":
      return "http_source";
    case "previous_step":
      if (previousOutputType === "json") return "previous_step_json";
      if (previousOutputType === "pdf" || previousOutputType === "docx")
        return "previous_step_document_text";
      return "previous_step_text";
    default:
      return "flow_input";
  }
}

export function getOutputHintKind(outputType: OutputType): FlowOutputHintKind {
  switch (outputType) {
    case "json":
      return "structured_json";
    case "pdf":
    case "docx":
      return "document_artifact";
    default:
      return "plain";
  }
}

export function getDownstreamKindForOutput(outputType: OutputType): FlowDownstreamKind {
  return outputType === "json" ? "text_and_structured" : "text";
}

export function sortSelectableInputTypeOptionsForDisplay(params: {
  options: SelectableInputTypeOption[];
  inputSource: InputSource;
  previousOutputType?: OutputType;
}): SelectableInputTypeOption[] {
  const { options, inputSource, previousOutputType } = params;
  const hintKind = getSourceHintKind({ inputSource, previousOutputType });
  const preferredOrder = DISPLAY_PRIORITY_BY_SOURCE[hintKind];

  const legacyOptions = options.filter((option) => option.legacyInvalid);
  const normalOptions = options.filter((option) => !option.legacyInvalid);

  if (!preferredOrder) {
    return [...legacyOptions, ...normalOptions];
  }

  const priority = new Map<InputType, number>();
  preferredOrder.forEach((value, index) => priority.set(value, index));

  const sortedNormal = [...normalOptions].sort((left, right) => {
    const leftPriority = priority.get(left.value) ?? INPUT_TYPE_FALLBACK_ORDER.indexOf(left.value);
    const rightPriority =
      priority.get(right.value) ?? INPUT_TYPE_FALLBACK_ORDER.indexOf(right.value);
    return leftPriority - rightPriority;
  });

  return [...legacyOptions, ...sortedNormal];
}

export function getRecommendedDisplayedInputType(params: {
  options: SelectableInputTypeOption[];
  inputSource: InputSource;
  previousOutputType?: OutputType;
}): InputType {
  const ordered = sortSelectableInputTypeOptionsForDisplay(params);
  return ordered.find((option) => !option.disabled)?.value ?? "text";
}

export function getEdgePayloadKind(params: {
  edgeKind: "flow_input" | "previous_step" | "all_previous_steps" | "flow_output";
  sourceStep?: FlowPresentationStepLike;
  targetStep?: FlowPresentationStepLike | null;
}): FlowEdgePayloadKind {
  const { edgeKind, sourceStep, targetStep } = params;

  if (edgeKind === "flow_output") return "none";
  if (edgeKind === "flow_input") return "flow_input";
  if (edgeKind === "all_previous_steps") return "text";

  if (sourceStep?.output_type === "json" && targetStep?.input_type === "json") {
    return "structured";
  }

  return "text";
}

export function getRuntimeFileOriginKind(params: {
  needsFileUpload: boolean;
  hasFlowInputStep: boolean;
}): FlowRuntimeFileOriginKind {
  const { needsFileUpload, hasFlowInputStep } = params;
  if (needsFileUpload) return "flow_input_runtime";
  if (!hasFlowInputStep) return "no_runtime_upload";
  return "static_step_context";
}

export function getStepSummaryModel(params: {
  step: FlowPresentationStepLike;
  previousStep?: FlowPresentationStepLike | null;
  hasInputTemplateOverride: boolean;
  hasKnowledge: boolean;
  hasAttachments: boolean;
}): FlowStepSummaryModel {
  const { step, previousStep, hasInputTemplateOverride, hasKnowledge, hasAttachments } = params;
  return {
    sourceKind: getSourceHintKind({
      inputSource: step.input_source,
      previousOutputType: previousStep?.output_type
    }),
    sourceStepOrder: previousStep?.step_order ?? null,
    inputFormat: step.input_type,
    outputFormat: step.output_type,
    downstreamKind: getDownstreamKindForOutput(step.output_type),
    usesInputTemplate: hasInputTemplateOverride,
    hasKnowledge,
    hasAttachments
  };
}
