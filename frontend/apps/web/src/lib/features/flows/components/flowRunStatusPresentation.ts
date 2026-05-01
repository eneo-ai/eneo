import { getFlowRunStatusLabel, type FlowRunStatusTranslations } from "./flowRunStatusLabel";

export type FlowRunStatusView = {
  label: string;
  textClass: string;
  dotClass: string;
  pulseDot: boolean;
};

function getFlowRunStatusColor(status: string): string {
  switch (status) {
    case "completed":
      return "text-positive-stronger";
    case "failed":
      return "text-negative-stronger";
    case "running":
      return "text-accent-stronger";
    case "cancelled":
      return "text-warning-stronger";
    case "queued":
    case "pending":
    default:
      return "text-secondary";
  }
}

function getFlowRunStatusDotColor(status: string): string {
  switch (status) {
    case "completed":
      return "bg-positive-default";
    case "failed":
      return "bg-negative-default";
    case "running":
      return "bg-accent-default";
    case "cancelled":
      return "bg-warning-default";
    case "queued":
    case "pending":
    default:
      return "bg-secondary";
  }
}

function shouldPulseFlowRunStatusDot(status: string): boolean {
  return status === "running";
}

export function getFlowRunStatusView(
  status: string,
  translations: FlowRunStatusTranslations
): FlowRunStatusView {
  return {
    label: getFlowRunStatusLabel(status, translations),
    textClass: getFlowRunStatusColor(status),
    dotClass: getFlowRunStatusDotColor(status),
    pulseDot: shouldPulseFlowRunStatusDot(status)
  };
}
