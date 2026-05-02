import { getFlowRunStatusLabel, type FlowRunStatusTranslations } from "./flowRunStatusLabel";
import type { FlowRunStatus } from "./flowRunStatusSets";

export type FlowRunStatusView = {
  label: string;
  textClass: string;
  dotClass: string;
  pulseDot: boolean;
};

type FlowRunStatusVisual = Omit<FlowRunStatusView, "label">;

// The shared badge also renders step results, whose not-started state is `pending`.
type FlowStatusVisualKey = FlowRunStatus | "pending";

const FLOW_STATUS_VISUALS = {
  queued: {
    textClass: "text-secondary",
    dotClass: "bg-secondary",
    pulseDot: false
  },
  pending: {
    textClass: "text-secondary",
    dotClass: "bg-secondary",
    pulseDot: false
  },
  running: {
    textClass: "text-accent-stronger",
    dotClass: "bg-accent-default",
    pulseDot: true
  },
  awaiting_review: {
    textClass: "text-accent-stronger",
    dotClass: "bg-accent-default",
    pulseDot: false
  },
  completed: {
    textClass: "text-positive-stronger",
    dotClass: "bg-positive-default",
    pulseDot: false
  },
  failed: {
    textClass: "text-negative-stronger",
    dotClass: "bg-negative-default",
    pulseDot: false
  },
  cancelled: {
    textClass: "text-warning-stronger",
    dotClass: "bg-warning-default",
    pulseDot: false
  }
} satisfies Record<FlowStatusVisualKey, FlowRunStatusVisual>;

const UNKNOWN_FLOW_STATUS_VISUAL = {
  textClass: "text-secondary",
  dotClass: "bg-secondary",
  pulseDot: false
} satisfies FlowRunStatusVisual;

function getFlowRunStatusVisual(status: string): FlowRunStatusVisual {
  if (Object.prototype.hasOwnProperty.call(FLOW_STATUS_VISUALS, status)) {
    return FLOW_STATUS_VISUALS[status as FlowStatusVisualKey];
  }
  return UNKNOWN_FLOW_STATUS_VISUAL;
}

export function getFlowRunStatusView(
  status: string,
  translations: FlowRunStatusTranslations
): FlowRunStatusView {
  const visual = getFlowRunStatusVisual(status);
  return {
    label: getFlowRunStatusLabel(status, translations),
    textClass: visual.textClass,
    dotClass: visual.dotClass,
    pulseDot: visual.pulseDot
  };
}
