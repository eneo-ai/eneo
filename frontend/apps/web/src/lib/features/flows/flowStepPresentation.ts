import type { FlowStep } from "@eneo/eneo-js";
import { getFlowStepUnderlag } from "./flowInputBindings";
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
  | "flow_input"
  | "previous_step"
  | "all_previous_steps"
  | "input_bindings"
  | "flow_output"
  | "http_get"
  | "http_post";

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
  "id" | "step_order" | "input_source" | "output_mode" | "input_bindings"
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
 * The step fields whose change must rebuild the graph layout. Underlag is
 * part of it: a binding-only edit moves edges.
 */
export function flowGraphLayoutKey(steps: FlowStep[]): string {
  return JSON.stringify(
    steps.map((step) => ({
      id: step.id,
      step_order: step.step_order,
      user_description: step.user_description,
      input_source: step.input_source,
      input_bindings: step.input_bindings ?? null,
      input_type: step.input_type,
      output_type: step.output_type,
      output_mode: step.output_mode,
      assistant_id: step.assistant_id,
      // The graph draws these too, so an edit to either has to rebuild it.
      // Without them, turning review on left the old node badge in place --
      // and, once the graph could be exported, in the image as well.
      review_policy: step.review_policy ?? null,
      output_classification_override: step.output_classification_override ?? null
    }))
  );
}

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

  // Explicit underlag is the whole step input, so its step references decide
  // the edges alone; `input_source` describes only a step without underlag.
  const underlagByStep = new Map(
    orderedSteps.map((step) => [step.step_order, getFlowStepUnderlag(step)])
  );
  const readsFlowInput = (step: FlowGraphTopologyStepLike): boolean => {
    const underlag = underlagByStep.get(step.step_order) ?? null;
    if (underlag !== null) return underlag.readsFlowInput;
    return (
      step.input_source === "flow_input" ||
      (step.input_source === "previous_step" && !byOrder.has(step.step_order - 1))
    );
  };

  // The flow-input node appears only when something actually consumes it
  // (or the flow is empty), so a flow fed purely by HTTP shows no orphan
  // input anchor.
  const needsInputNode = orderedSteps.length === 0 || orderedSteps.some(readsFlowInput);
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
    const underlag = underlagByStep.get(step.step_order) ?? null;
    if (underlag !== null) {
      if (underlag.readsFlowInput) {
        edges.push({
          source: "input",
          target: id,
          kind: "flow_input",
          sourceStepOrder: 0,
          targetStepOrder: step.step_order
        });
      }
      for (const order of underlag.stepOrders) {
        const sourceStep = byOrder.get(order);
        if (!sourceStep || order >= step.step_order) continue;
        edges.push({
          source: stepId(sourceStep),
          target: id,
          kind: "input_bindings",
          sourceStepOrder: order,
          targetStepOrder: step.step_order
        });
      }
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

export type FlowGraphEmphasisEdge = { id: string; source: string; target: string };

export type FlowGraphEmphasis = {
  litNodes: Record<string, true>;
  litEdges: Record<string, true>;
  /** True only while someone is pointing at or tabbed to a step. */
  isPreview: boolean;
  /** Whether anything should be quieted at all. */
  hasFocus: boolean;
};

/**
 * Decides what the graph emphasises, given what is selected and what is being
 * pointed at.
 *
 * Two questions, two answers, on the gestures a reader already has:
 *
 * - Pointing at or tabbing to a step answers "what feeds this step": its
 *   underlag, one hop back. A wider answer would bury the one being asked for
 *   while the step is being configured.
 * - Selecting a step answers "where does this step sit in the flow": the whole
 *   path it lies on, following edges to both ends.
 *
 * Forward means what a step's output reaches, not what runs next. The runtime
 * executes in step order regardless of the edges, so the graph claims only
 * what the edges say and the numbers carry the order.
 *
 * Either way this is the underlag configured in this flow, not every reference
 * the runtime resolves, so it is emphasis and never a claim of complete
 * provenance.
 */
/**
 * What the reader is currently pointing at or tabbed to, and which of those
 * gestures has already been spent opening a step.
 *
 * Activation has to stop previewing the step it opened, or the reader asks for
 * the path through a step and keeps being shown the one hop back into it:
 * focus stays on a node after Enter and the pointer stays over it after a
 * click. But the suppression belongs to the gesture that caused it, not to the
 * step -- tabbing away and back is a new gesture and must preview again.
 */
export type FlowGraphPreviewState = {
  hoveredId: string | null;
  focusedId: string | null;
  pointerSpentOn: string | null;
  focusSpentOn: string | null;
};

export type FlowGraphPreviewEvent =
  | { type: "hover"; id: string }
  | { type: "unhover" }
  | { type: "focus"; id: string }
  | { type: "blur" }
  | { type: "activate"; id: string };

export function emptyFlowGraphPreviewState(): FlowGraphPreviewState {
  return { hoveredId: null, focusedId: null, pointerSpentOn: null, focusSpentOn: null };
}

export function reduceFlowGraphPreview(
  state: FlowGraphPreviewState,
  event: FlowGraphPreviewEvent
): FlowGraphPreviewState {
  switch (event.type) {
    // Entering a node is always a fresh pointer gesture.
    case "hover":
      return { ...state, hoveredId: event.id, pointerSpentOn: null };
    case "unhover":
      return { ...state, hoveredId: null, pointerSpentOn: null };
    // So is moving focus, including moving it back to where it was.
    case "focus":
      return { ...state, focusedId: event.id, focusSpentOn: null };
    case "blur":
      return { ...state, focusedId: null, focusSpentOn: null };
    // Opening a step spends whichever gestures are currently on it.
    case "activate":
      return {
        ...state,
        pointerSpentOn: state.hoveredId === event.id ? event.id : state.pointerSpentOn,
        focusSpentOn: state.focusedId === event.id ? event.id : state.focusSpentOn
      };
  }
}

/** The step being previewed, or null when the gesture on it has been spent. */
export function resolveFlowGraphPreviewId(state: FlowGraphPreviewState): string | null {
  if (state.hoveredId !== null) {
    return state.hoveredId === state.pointerSpentOn ? null : state.hoveredId;
  }
  if (state.focusedId !== null) {
    return state.focusedId === state.focusSpentOn ? null : state.focusedId;
  }
  return null;
}

export function computeFlowGraphEmphasis(params: {
  edges: FlowGraphEmphasisEdge[];
  activeId: string | null;
  previewId: string | null;
}): FlowGraphEmphasis {
  const { edges, activeId, previewId } = params;
  const litNodes: Record<string, true> = {};
  const litEdges: Record<string, true> = {};

  if (previewId !== null) {
    litNodes[previewId] = true;
    for (const edge of edges) {
      if (edge.target === previewId) {
        litEdges[edge.id] = true;
        litNodes[edge.source] = true;
      }
    }
  } else if (activeId !== null) {
    litNodes[activeId] = true;
    const bySource = new Map<string, FlowGraphEmphasisEdge[]>();
    const byTarget = new Map<string, FlowGraphEmphasisEdge[]>();
    for (const edge of edges) {
      (bySource.get(edge.source) ?? bySource.set(edge.source, []).get(edge.source)!).push(edge);
      (byTarget.get(edge.target) ?? byTarget.set(edge.target, []).get(edge.target)!).push(edge);
    }
    walkFlowGraph(byTarget, activeId, "source", litNodes, litEdges);
    walkFlowGraph(bySource, activeId, "target", litNodes, litEdges);
  }

  return {
    litNodes,
    litEdges,
    isPreview: previewId !== null,
    hasFocus: Object.keys(litNodes).length > 0
  };
}

/**
 * Follows edges from one node to the end of the graph in one direction,
 * over a prebuilt adjacency index so each edge is looked at once.
 */
function walkFlowGraph(
  adjacency: Map<string, FlowGraphEmphasisEdge[]>,
  startId: string,
  to: "source" | "target",
  litNodes: Record<string, true>,
  litEdges: Record<string, true>
): void {
  const queue = [startId];
  // An index rather than shift(), which is linear in the queue on every step.
  for (let head = 0; head < queue.length; head += 1) {
    for (const edge of adjacency.get(queue[head]) ?? []) {
      if (litEdges[edge.id] === true) continue;
      litEdges[edge.id] = true;
      const next = edge[to];
      if (litNodes[next] !== true) {
        litNodes[next] = true;
        queue.push(next);
      }
    }
  }
}

/**
 * Decides what fits in an exported image's caption, from widths the caller has
 * measured.
 *
 * A caption that loses its own words is worse than none, and it is drawn on a
 * canvas that has no wrapping, clipping or overflow of its own -- so every
 * decision is made here first. A heavily reduced graph can produce an image
 * only a few dozen pixels wide, where the dashed key cannot fit beside its own
 * label; it is dropped rather than drawn past the edge.
 */
export function planFlowExportCaption(params: {
  availableWidth: number;
  titleWidth: number;
  captionWidth: number;
  legendLabelWidth: number | null;
  keyWidth: number;
  gap: number;
  minimumTextWidth: number;
}): {
  showTitle: boolean;
  showCaption: boolean;
  showLegend: boolean;
  legendSharesCaptionRow: boolean;
  captionWidth: number;
  legendLabelWidth: number;
  rows: number;
} {
  const {
    availableWidth,
    titleWidth,
    captionWidth,
    legendLabelWidth,
    keyWidth,
    gap,
    minimumTextWidth
  } = params;

  /**
   * A readable minimum is about what survives truncation, not about how much
   * the text had to say. A flow called "HR" needs no room to spare and must
   * not be dropped for being short, so the minimum applies only when the text
   * would have to be cut to fit.
   */
  const fits = (width: number, budget: number) =>
    width > 0 && (width <= budget || budget >= minimumTextWidth);

  const showTitle = fits(titleWidth, availableWidth);

  // The key needs its own line plus a gap before anything is left for a label.
  const legendBudget = availableWidth - keyWidth - gap;
  const showLegend = legendLabelWidth !== null && fits(legendLabelWidth, legendBudget);
  const legendWidth = showLegend
    ? Math.min(legendLabelWidth ?? 0, legendBudget) + gap + keyWidth
    : 0;

  // Sharing a row is for when everything genuinely fits. Allowing it whenever
  // some readable minimum survives would hand the sentence four characters and
  // call that a caption, so if anything would have to be cut, each gets a row.
  const captionBudgetBeside = availableWidth - legendWidth - gap * 2;
  const legendSharesCaptionRow =
    showLegend && captionWidth + gap * 2 + legendWidth <= availableWidth;
  const captionBudget = legendSharesCaptionRow ? captionBudgetBeside : availableWidth;
  const showCaption = fits(captionWidth, captionBudget);

  const rows =
    (showTitle ? 1 : 0) +
    (showCaption ? 1 : 0) +
    (showLegend && !(legendSharesCaptionRow && showCaption) ? 1 : 0);

  return {
    showTitle,
    showCaption,
    showLegend,
    legendSharesCaptionRow: legendSharesCaptionRow && showCaption,
    captionWidth: captionBudget,
    legendLabelWidth: showLegend ? legendBudget : 0,
    rows
  };
}

/** Longest side a browser will reliably allocate for a canvas, with margin. */
const FLOW_EXPORT_MAX_EDGE = 8192;
/**
 * And the area, because a long thin flow can clear the edge bound and not
 * this. Both bound the captured graph; a caller that adds a caption band
 * adds its height on top, which is a fixed strip rather than a factor.
 */
const FLOW_EXPORT_MAX_PIXELS = 16_000_000;
/** Twice design size reads well in a document without being wasteful. */
const FLOW_EXPORT_SCALE = 2;
const FLOW_EXPORT_MARGIN = 32;

/**
 * Picks the pixel size of an exported flow image from the laid-out graph.
 *
 * The scale is applied through the viewport transform rather than a pixel
 * ratio, so the image is of the flow at a known size rather than of whatever
 * the reader had on screen. Both bounds floor rather than round: a ceiling
 * that the result may exceed is not a ceiling.
 */
export function computeFlowExportSize(bounds: { width: number; height: number }): {
  width: number;
  height: number;
  scale: number;
} | null {
  if (!(bounds.width > 0) || !(bounds.height > 0)) return null;
  const boxWidth = bounds.width + FLOW_EXPORT_MARGIN * 2;
  const boxHeight = bounds.height + FLOW_EXPORT_MARGIN * 2;
  const scale = Math.min(
    FLOW_EXPORT_SCALE,
    FLOW_EXPORT_MAX_EDGE / boxWidth,
    FLOW_EXPORT_MAX_EDGE / boxHeight,
    Math.sqrt(FLOW_EXPORT_MAX_PIXELS / (boxWidth * boxHeight))
  );
  return {
    width: Math.floor(boxWidth * scale),
    height: Math.floor(boxHeight * scale),
    scale
  };
}
