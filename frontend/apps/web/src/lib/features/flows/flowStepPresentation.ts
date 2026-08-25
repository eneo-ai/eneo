import type { FlowStep } from "@eneo/eneo-js";
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
  "flow_input_runtime" | "no_runtime_upload" | "static_step_context";

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

export type FlowEdgeKind =
  "flow_input" | "previous_step" | "all_previous_steps" | "flow_output" | "http_get" | "http_post";

export function getEdgePayloadKind(params: {
  edgeKind: FlowEdgeKind;
  sourceStep?: FlowPresentationStepLike;
  targetStep?: FlowPresentationStepLike | null;
}): FlowEdgePayloadKind {
  const { edgeKind, sourceStep, targetStep } = params;

  if (edgeKind === "flow_output" || edgeKind === "http_post") return "none";
  if (edgeKind === "flow_input") return "flow_input";
  if (edgeKind === "all_previous_steps") return "text";
  if (edgeKind === "http_get") {
    return targetStep?.input_type === "json" ? "structured" : "text";
  }

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

export type FlowGraphTopologyStepLike = Pick<
  FlowStep,
  "id" | "step_order" | "input_source" | "output_mode"
>;

export type FlowGraphTopologyNode =
  | { id: "input"; kind: "input" }
  | { id: "output"; kind: "output" }
  | { id: "http-source"; kind: "http_source" }
  | { id: "http-target"; kind: "http_target" }
  | { id: string; kind: "step"; stepOrder: number };

export type FlowGraphTopologyEdge = {
  source: string;
  target: string;
  kind: FlowEdgeKind;
  sourceStepOrder: number;
  targetStepOrder: number | null;
};

/**
 * The pure node/edge contract behind Flödesvy. All HTTP endpoints share one
 * external-source and one external-receiver node: the graph answers "where
 * does data come from and go", while each step's own summary names its URL,
 * so per-endpoint nodes would only add clutter.
 */
export function buildFlowGraphTopology(steps: FlowGraphTopologyStepLike[]): {
  nodes: FlowGraphTopologyNode[];
  edges: FlowGraphTopologyEdge[];
} {
  const orderedSteps = [...steps].sort((a, b) => a.step_order - b.step_order);
  const stepId = (step: FlowGraphTopologyStepLike) => step.id ?? `step-${step.step_order}`;
  const byOrder = new Map(orderedSteps.map((step) => [step.step_order, step]));

  const nodes: FlowGraphTopologyNode[] = [];
  const edges: FlowGraphTopologyEdge[] = [];

  // The flow-input node appears only when something actually consumes it
  // (or the flow is empty), so a flow fed purely by HTTP shows no orphan
  // input anchor.
  const needsInputNode =
    orderedSteps.length === 0 ||
    orderedSteps.some(
      (step) =>
        step.input_source === "flow_input" ||
        (step.input_source === "previous_step" && !byOrder.has(step.step_order - 1))
    );
  if (needsInputNode) {
    nodes.push({ id: "input", kind: "input" });
  }
  for (const step of orderedSteps) {
    nodes.push({ id: stepId(step), kind: "step", stepOrder: step.step_order });
  }
  nodes.push({ id: "output", kind: "output" });

  let hasHttpSource = false;
  for (const step of orderedSteps) {
    const id = stepId(step);
    if (step.input_source === "http_get") {
      if (!hasHttpSource) {
        hasHttpSource = true;
        nodes.push({ id: "http-source", kind: "http_source" });
      }
      edges.push({
        source: "http-source",
        target: id,
        kind: "http_get",
        sourceStepOrder: 0,
        targetStepOrder: step.step_order
      });
      continue;
    }
    if (step.input_source === "flow_input") {
      edges.push({
        source: "input",
        target: id,
        kind: "flow_input",
        sourceStepOrder: 0,
        targetStepOrder: step.step_order
      });
      continue;
    }
    if (step.input_source === "previous_step") {
      const prevStep = byOrder.get(step.step_order - 1);
      if (prevStep) {
        edges.push({
          source: stepId(prevStep),
          target: id,
          kind: "previous_step",
          sourceStepOrder: prevStep.step_order,
          targetStepOrder: step.step_order
        });
      } else {
        edges.push({
          source: "input",
          target: id,
          kind: "flow_input",
          sourceStepOrder: 0,
          targetStepOrder: step.step_order
        });
      }
      continue;
    }
    if (step.input_source === "all_previous_steps") {
      for (const prevStep of orderedSteps) {
        if (prevStep.step_order >= step.step_order) continue;
        edges.push({
          source: stepId(prevStep),
          target: id,
          kind: "all_previous_steps",
          sourceStepOrder: prevStep.step_order,
          targetStepOrder: step.step_order
        });
      }
    }
  }

  if (orderedSteps.length > 0) {
    const outgoingSteps = new Set<string>();
    for (const edge of edges) {
      if (edge.source !== "input" && edge.source !== "http-source" && edge.target !== "output") {
        outgoingSteps.add(edge.source);
      }
    }
    let hasHttpTarget = false;
    for (const step of orderedSteps) {
      const id = stepId(step);
      if (step.output_mode === "http_post") {
        // The delivery step still produces the flow result; the HTTP
        // delivery is an additional external receiver, so both edges are
        // the truthful picture.
        if (!hasHttpTarget) {
          hasHttpTarget = true;
          nodes.push({ id: "http-target", kind: "http_target" });
        }
        edges.push({
          source: id,
          target: "http-target",
          kind: "http_post",
          sourceStepOrder: step.step_order,
          targetStepOrder: null
        });
      }
      if (outgoingSteps.has(id)) continue;
      edges.push({
        source: id,
        target: "output",
        kind: "flow_output",
        sourceStepOrder: step.step_order,
        targetStepOrder: null
      });
    }
  } else {
    edges.push({
      source: "input",
      target: "output",
      kind: "flow_output",
      sourceStepOrder: 0,
      targetStepOrder: null
    });
  }

  return { nodes, edges };
}
