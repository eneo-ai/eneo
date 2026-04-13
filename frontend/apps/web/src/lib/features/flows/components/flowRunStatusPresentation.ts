import { getFlowRunStatusLabel, type FlowRunStatusTranslations } from "./flowRunStatusLabel";

export function getFlowRunStatusColor(status: string): string {
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

export function getFlowRunStatusDotColor(status: string): string {
  switch (status) {
    case "completed":
      return "bg-positive-default";
    case "failed":
      return "bg-negative-default";
    case "running":
      return "bg-accent-default animate-pulse";
    case "cancelled":
      return "bg-warning-default";
    case "queued":
    case "pending":
    default:
      return "bg-secondary";
  }
}

export function getFlowRunLocalizedStatusLabel(
  status: string,
  translations: FlowRunStatusTranslations
): string {
  return getFlowRunStatusLabel(status, translations);
}
